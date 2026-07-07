"""GTFS-RT-poller: TripUpdates, ServiceAlerts och VehiclePositions i minnet.

KVOT: RT-nyckeln har 30 000 anrop per rullande 30 dagar (Bronze) - det
racker INTE for kontinuerlig pollning (lardom 2026-07-07: 3 feeds var
20:e sekund brande hela kvoten pa tva dygn). Darfor ar pollningen
behovsstyrd: feeds hamtas bara nar nagon faktiskt anvander appen
(mark_activity() satts av sidorna/API:t), TripUpdates var 30:e sekund,
ServiceAlerts var 5:e minut och VehiclePositions bara nar nagon har
kartan oppen. Vid 429 backar pollern av rejalt.

Referenserna byts atomiskt - lashandlers behover inga las. Ar feedsen
nere behalls senast kanda data; ar datat aldre an STALE_AFTER behandlas
realtid som otillganglig och appen faller tillbaka pa tidtabellstid.
"""

import asyncio
import logging
import time
from datetime import date, datetime

import httpx
from google.transit import gtfs_realtime_pb2

from app import config

log = logging.getLogger(__name__)

POLL_INTERVAL = 30        # TripUpdates/VehiclePositions nar nagon ar aktiv
ALERT_INTERVAL = 300      # ServiceAlerts andras sallan
ACTIVE_WINDOW = 90        # så lange raknas en klient som aktiv efter sidvisning
STALE_AFTER = 120
BACKOFF_429 = 30 * 60     # kvoten ar slut - lugna ner sig ordentligt


class RealtimeState:
    def __init__(self):
        self.trip_updates: dict[str, dict] = {}
        self.alerts: list[dict] = []
        self.vehicle_positions: dict[str, dict] = {}
        self.updated_at: float | None = None
        self.last_activity = 0.0
        self.map_activity = 0.0
        self.backoff_until = 0.0
        self.requests_today = 0
        self._requests_day: date | None = None
        self.wake = asyncio.Event()

    @property
    def fresh(self) -> bool:
        return self.updated_at is not None and time.time() - self.updated_at < STALE_AFTER

    def count_requests(self, n: int) -> None:
        today = datetime.now(tz=config.TZ).date()
        if self._requests_day != today:
            self._requests_day = today
            self.requests_today = 0
        self.requests_today += n


state = RealtimeState()


def mark_activity(map_interest: bool = False) -> None:
    """Kallas av sidor/API nar nagon anvander appen - styr pollningen."""
    now = time.time()
    state.last_activity = now
    if map_interest:
        state.map_activity = now
    if not state.fresh and now >= state.backoff_until:
        state.wake.set()


def _parse_trip_updates(payload: bytes) -> dict[str, dict]:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(payload)
    out: dict[str, dict] = {}
    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        tu = entity.trip_update
        updates = []
        for stu in tu.stop_time_update:
            event = stu.departure if stu.HasField("departure") else stu.arrival
            updates.append({
                "seq": stu.stop_sequence,
                "stop_id": stu.stop_id,
                "delay": event.delay if event.HasField("delay") else None,
                "time": event.time if event.HasField("time") else None,
                "skipped": stu.schedule_relationship
                           == gtfs_realtime_pb2.TripUpdate.StopTimeUpdate.SKIPPED,
            })
        updates.sort(key=lambda u: u["seq"])
        out[tu.trip.trip_id] = {
            "canceled": tu.trip.schedule_relationship
                        == gtfs_realtime_pb2.TripDescriptor.CANCELED,
            "updates": updates,
        }
    return out


def _text_sv(translated) -> str:
    for t in translated.translation:
        if t.language in ("sv", ""):
            return t.text
    return translated.translation[0].text if translated.translation else ""


def _parse_alerts(payload: bytes) -> list[dict]:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(payload)
    now = time.time()
    out = []
    for entity in feed.entity:
        if not entity.HasField("alert"):
            continue
        a = entity.alert
        if a.active_period and not any(
                (p.start or 0) <= now <= (p.end or float("inf"))
                for p in a.active_period):
            continue
        alert = {
            "header": _text_sv(a.header_text),
            "description": _text_sv(a.description_text),
            "route_ids": {ie.route_id for ie in a.informed_entity if ie.route_id},
            "stop_ids": {ie.stop_id for ie in a.informed_entity if ie.stop_id},
        }
        if alert["header"] and alert not in out:
            out.append(alert)
    return out


def _parse_vehicle_positions(payload: bytes) -> dict[str, dict]:
    """trip_id -> senaste fordonsposition (lat/lon/riktning/tidsstampel)."""
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(payload)
    out: dict[str, dict] = {}
    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue
        v = entity.vehicle
        if not v.trip.trip_id or not v.HasField("position"):
            continue
        out[v.trip.trip_id] = {
            "lat": v.position.latitude,
            "lon": v.position.longitude,
            "bearing": v.position.bearing if v.position.HasField("bearing") else None,
            "ts": v.timestamp or None,
        }
    return out


async def poll_loop():
    headers = {"Accept-Encoding": "gzip"}
    alerts_fetched_at = 0.0
    async with httpx.AsyncClient(timeout=15, headers=headers) as client:

        async def fetch(feed: str) -> bytes:
            resp = await client.get(f"{config.GTFS_RT_BASE}/{feed}.pb",
                                    params={"key": config.TRAFIKLAB_RT_KEY})
            resp.raise_for_status()
            return resp.content

        while True:
            now = time.time()
            idle = now - state.last_activity > ACTIVE_WINDOW
            if idle or now < state.backoff_until:
                # Ingen anvander appen (eller kvoten ar strypt) - polla inte.
                # mark_activity() vacker oss direkt nar nagon kommer.
                state.wake.clear()
                try:
                    await asyncio.wait_for(state.wake.wait(),
                                           timeout=max(10.0, state.backoff_until - now))
                except TimeoutError:
                    pass
                continue

            want_alerts = now - alerts_fetched_at > ALERT_INTERVAL
            want_vehicles = now - state.map_activity < ACTIVE_WINDOW
            feeds = ["TripUpdates"] + (["ServiceAlerts"] if want_alerts else []) \
                + (["VehiclePositions"] if want_vehicles else [])
            try:
                results = await asyncio.gather(*(fetch(f) for f in feeds))
                state.count_requests(len(feeds))
                payload = dict(zip(feeds, results))
                state.trip_updates = _parse_trip_updates(payload["TripUpdates"])
                if "ServiceAlerts" in payload:
                    state.alerts = _parse_alerts(payload["ServiceAlerts"])
                    alerts_fetched_at = now
                if "VehiclePositions" in payload:
                    state.vehicle_positions = _parse_vehicle_positions(
                        payload["VehiclePositions"])
                state.updated_at = time.time()
            except httpx.HTTPStatusError as exc:
                state.count_requests(len(feeds))
                if exc.response.status_code == 429:
                    state.backoff_until = time.time() + BACKOFF_429
                    log.warning("GTFS-RT-kvoten ar strypt (429) - pausar pollning "
                                "%d min", BACKOFF_429 // 60)
                else:
                    log.warning("GTFS-RT-hamtning misslyckades: %s", exc)
            except Exception as exc:
                # Behall gammalt state; `fresh` slar over till False av sig sjalv
                log.warning("GTFS-RT-hamtning misslyckades: %s", exc)
            await asyncio.sleep(POLL_INTERVAL)


def _resolve_update(trip_rt: dict, stop_seq: int, platform_stop_id: str) -> dict | None:
    """Senaste stop_time_update som galler vart stopp (exakt eller fore i turen)."""
    match = None
    for u in trip_rt["updates"]:
        if u["stop_id"] == platform_stop_id or u["seq"] == stop_seq:
            return u
        if u["seq"] < stop_seq:
            match = u
    return match


def enrich_departures(departures: list[dict], now: datetime) -> bool:
    """Lagg realtidsfalt pa avgangar fran upcoming_departures().

    Satter display_time/in_minutes till faktisk tid nar realtid finns.
    Returnerar om realtidsdata ar farsk.
    """
    fresh = state.fresh
    for dep in departures:
        dep["realtime"] = False
        dep["canceled"] = False
        dep["delay_min"] = 0
        dep["scheduled_time"] = dep["time"]
        dep["display_time"] = dep["time"]
        if not fresh:
            continue
        trip_rt = state.trip_updates.get(dep["trip_id"])
        if trip_rt is None:
            continue
        if trip_rt["canceled"]:
            dep["realtime"] = True
            dep["canceled"] = True
            continue
        update = _resolve_update(trip_rt, dep["stop_seq"], dep["platform_stop_id"])
        if update is None:
            continue
        dep["realtime"] = True
        if update["skipped"] and update["stop_id"] == dep["platform_stop_id"]:
            dep["canceled"] = True
            continue
        scheduled_epoch = dep["when"].timestamp()
        if update["time"]:
            actual_epoch = update["time"]
        elif update["delay"] is not None:
            actual_epoch = scheduled_epoch + update["delay"]
        else:
            continue
        # Avrunda till narmaste minut, samma konvention som tidtabellstiderna
        actual = datetime.fromtimestamp(round(actual_epoch / 60) * 60, tz=config.TZ)
        dep["delay_min"] = round((actual_epoch - scheduled_epoch) / 60)
        dep["display_time"] = actual.strftime("%H:%M")
        dep["in_minutes"] = max(0, int((actual_epoch - now.timestamp()) // 60))
    return fresh


def alerts_for(route_ids: set[str], stop_ids: set[str]) -> list[dict]:
    """Aktiva storningar som beror nagon av linjerna/hallplatserna (eller alla)."""
    if not state.fresh:
        return []
    # Din Tur publicerar ofta samma storning i lang och kort variant -
    # deduplicera per rubrik och behall den utforligaste beskrivningen.
    best: dict[str, str] = {}
    for a in state.alerts:
        affects_us = (a["route_ids"] & route_ids) or (a["stop_ids"] & stop_ids)
        is_global = not a["route_ids"] and not a["stop_ids"]
        if affects_us or is_global:
            if len(a["description"]) > len(best.get(a["header"], "")):
                best[a["header"]] = a["description"]
    return [{"header": h, "description": d} for h, d in best.items()]


def vehicles_for_departures(departures: list[dict]) -> list[dict]:
    """Fordonspositioner for avgangarnas turer (en per tur, farsk data)."""
    if not state.fresh:
        return []
    now = time.time()
    out, seen = [], set()
    for dep in departures:
        trip_id = dep["trip_id"]
        if trip_id in seen or dep.get("canceled"):
            continue
        pos = state.vehicle_positions.get(trip_id)
        if pos is None:
            continue
        seen.add(trip_id)
        out.append({
            "trip_id": trip_id,
            "line": dep["line"],
            "destination": dep["destination"],
            "lat": pos["lat"],
            "lon": pos["lon"],
            "bearing": pos["bearing"],
            "age_s": int(now - pos["ts"]) if pos["ts"] else None,
        })
    return out
