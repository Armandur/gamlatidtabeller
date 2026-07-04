"""GTFS-RT-poller: TripUpdates och ServiceAlerts i minnet.

En bakgrundstask hamtar feedsen var POLL_INTERVAL sekund och byter
referenserna atomiskt - lashandlers behover inga las. Ar feedsen nere
behalls senast kanda data; ar datat aldre an STALE_AFTER behandlas
realtid som otillganglig och appen faller tillbaka pa tidtabellstid.
"""

import asyncio
import logging
import time
from datetime import datetime

import httpx
from google.transit import gtfs_realtime_pb2

from app import config

log = logging.getLogger(__name__)

POLL_INTERVAL = 20
STALE_AFTER = 90


class RealtimeState:
    def __init__(self):
        self.trip_updates: dict[str, dict] = {}
        self.alerts: list[dict] = []
        self.vehicle_positions: dict[str, dict] = {}
        self.updated_at: float | None = None

    @property
    def fresh(self) -> bool:
        return self.updated_at is not None and time.time() - self.updated_at < STALE_AFTER


state = RealtimeState()


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
    async with httpx.AsyncClient(timeout=15, headers=headers) as client:
        while True:
            try:
                tu, sa, vp = await asyncio.gather(
                    client.get(f"{config.GTFS_RT_BASE}/TripUpdates.pb",
                               params={"key": config.TRAFIKLAB_RT_KEY}),
                    client.get(f"{config.GTFS_RT_BASE}/ServiceAlerts.pb",
                               params={"key": config.TRAFIKLAB_RT_KEY}),
                    client.get(f"{config.GTFS_RT_BASE}/VehiclePositions.pb",
                               params={"key": config.TRAFIKLAB_RT_KEY}))
                tu.raise_for_status()
                sa.raise_for_status()
                vp.raise_for_status()
                state.trip_updates = _parse_trip_updates(tu.content)
                state.alerts = _parse_alerts(sa.content)
                state.vehicle_positions = _parse_vehicle_positions(vp.content)
                state.updated_at = time.time()
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
        actual = datetime.fromtimestamp(actual_epoch, tz=config.TZ)
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
