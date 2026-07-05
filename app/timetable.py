"""Uppslag i tidtabellsdatabasen: hallplatser, linjer och kommande avgangar."""

import sqlite3
from datetime import date, datetime, timedelta

from app import config

# Avgangar vid en station (alla lagen) pa en given trafikdag.
# OBS: en trafikdags turer kan ga efter midnatt (departure_s > 86400),
# darfor slas gardagens trafikdag ihop med dagens vid uppslag.
_DEPARTURES_SQL = """
SELECT st.departure_s, st.stop_seq, st.pickup, r.short_name AS line, r.is_local,
       t.destination, t.trip_id, t.route_id, s.stop_id AS platform_stop_id, s.platform_code,
       COALESCE(br.message, '') AS booking_msg
FROM stop_times st
JOIN stops s ON s.stop_id = st.stop_id
JOIN trips t ON t.trip_id = st.trip_id
JOIN routes r ON r.route_id = t.route_id
JOIN service_dates sd ON sd.service_id = t.service_id
LEFT JOIN booking_rules br ON br.rule_id = st.booking_rule
WHERE (s.parent_station = :sid OR s.stop_id = :sid)
  AND sd.date = :date AND st.is_last = 0 AND st.pickup != 1
  AND st.departure_s >= :from_s
ORDER BY st.departure_s
LIMIT :limit
"""

_LINES_SQL = """
SELECT r.short_name AS line, r.is_local, t.destination, count(*) AS n
FROM stop_times st
JOIN stops s ON s.stop_id = st.stop_id
JOIN trips t ON t.trip_id = st.trip_id
JOIN routes r ON r.route_id = t.route_id
WHERE (s.parent_station = :sid OR s.stop_id = :sid)
  AND st.is_last = 0 AND st.pickup != 1
GROUP BY r.short_name, r.is_local, t.destination
"""


# Hela tidtabellen for en linje pa en trafikdag: alla halltider,
# grupperade per riktning i Python-lagret.
_LINE_DAY_SQL = """
SELECT t.trip_id, t.direction_id, t.destination, st.stop_seq, st.departure_s, st.pickup,
       COALESCE(NULLIF(s.parent_station, ''), s.stop_id) AS station_id,
       s.name AS stop_name, COALESCE(br.message, '') AS booking_msg
FROM trips t
JOIN routes r ON r.route_id = t.route_id
JOIN service_dates sd ON sd.service_id = t.service_id
JOIN stop_times st ON st.trip_id = t.trip_id
JOIN stops s ON s.stop_id = st.stop_id
LEFT JOIN booking_rules br ON br.rule_id = st.booking_rule
WHERE r.short_name = :line AND r.is_local = 1 AND sd.date = :date
ORDER BY t.trip_id, st.stop_seq
"""


def _midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=config.TZ)


def fmt_hhmm(dep_s: int) -> str:
    """Sekunder -> HH:MM avrundat till narmaste minut, som Din Turs
    officiella tabeller (GTFS har sekunduppslosning, t.ex. 05:59:31
    visas som 06:00). Golvning gav 1 min diff mot officiella tabellen
    pa interpolerade hallplatser."""
    m = (dep_s + 30) // 60
    return f"{m // 60 % 24:02d}:{m % 60:02d}"


def _line_sort_key(line: str):
    return (0, int(line)) if line.isdigit() else (1, line)


def list_stations(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT stop_id, name, lat, lon FROM stops WHERE is_station = 1 "
        "ORDER BY name COLLATE NOCASE").fetchall()


def get_station(db: sqlite3.Connection, station_id: str) -> sqlite3.Row | None:
    return db.execute(
        "SELECT stop_id, name, lat, lon FROM stops WHERE stop_id = ? AND is_station = 1",
        (station_id,)).fetchone()


def lines_at_station(db: sqlite3.Connection, station_id: str) -> list[dict]:
    """Linjer som trafikerar stationen, med vanligaste destinationerna."""
    lines: dict[str, dict] = {}
    for row in db.execute(_LINES_SQL, {"sid": station_id}):
        entry = lines.setdefault(row["line"], {
            "line": row["line"], "is_local": bool(row["is_local"]), "destinations": []})
        entry["destinations"].append((row["n"], row["destination"]))
    out = []
    for entry in lines.values():
        entry["destinations"] = [d for _, d in sorted(entry["destinations"], reverse=True)]
        out.append(entry)
    out.sort(key=lambda e: (not e["is_local"], _line_sort_key(e["line"])))
    return out


def upcoming_departures(db: sqlite3.Connection, station_id: str,
                        now: datetime | None = None, limit: int = 20) -> list[dict]:
    """Kommande avgangar fran och med `now`, over dygnsgranser."""
    now = now or datetime.now(tz=config.TZ)
    today = now.date()
    now_s = int((now - _midnight(today)).total_seconds())

    # (trafikdag, fran-sekund): gardagens efter midnatt-turer, sedan dag
    # for dag upp till en vecka framat tills limit ar fylld - hallplatser
    # utan helgtrafik ska visa mandagens turer i stallet for tom lista.
    plan = [(today - timedelta(days=1), now_s + 86400)]
    plan += [(today + timedelta(days=k), now_s if k == 0 else 0) for k in range(7)]
    departures = []
    for service_date, from_s in plan:
        if len(departures) >= limit:
            break
        rows = db.execute(_DEPARTURES_SQL, {
            "sid": station_id, "date": service_date.isoformat(),
            "from_s": from_s, "limit": limit}).fetchall()
        for r in rows:
            when = _midnight(service_date) + timedelta(seconds=r["departure_s"])
            days_ahead = (when.date() - today).days
            departures.append({
                "when": when,
                "time": fmt_hhmm(r["departure_s"]),
                "in_minutes": max(0, int((when - now).total_seconds() // 60)),
                "day_label": ("" if days_ahead == 0 else
                              "i morgon" if days_ahead == 1 else
                              _WEEKDAYS_SV[when.weekday()]),
                "line": r["line"],
                "is_local": bool(r["is_local"]),
                "destination": r["destination"],
                "platform": r["platform_code"],
                "booking": r["pickup"] in (2, 3),
                "booking_msg": r["booking_msg"] if r["pickup"] in (2, 3) else "",
                "trip_id": r["trip_id"],
                "route_id": r["route_id"],
                "stop_seq": r["stop_seq"],
                "platform_stop_id": r["platform_stop_id"],
            })
    departures.sort(key=lambda d: d["when"])
    return departures[:limit]


def local_lines(db: sqlite3.Connection) -> list[str]:
    rows = db.execute("SELECT short_name FROM routes WHERE is_local = 1").fetchall()
    return sorted({r["short_name"] for r in rows}, key=_line_sort_key)


def _align_stop_orders(sequences: list[list[str]]) -> tuple[list[str], list[list[int]]]:
    """Justera turernas hallplatsfoljder mot en gemensam radlista.

    Monoton matchning: varje halltid tilldelas nasta rad (efter turens
    forra) med samma hallplats, annars skapas en ny rad dar. Klarar
    overhoppade hallplatser, grenvarianter och slinglinjer dar samma
    hallplats passeras flera ganger per tur (blir da flera rader).

    Returnerar (rader, tilldelning per tur: radindex per halltid).
    """
    rows: list[str] = []
    assignments: list[list[int]] = []
    for seq in sequences:
        last = -1
        assign = []
        for sid in seq:
            j = next((k for k in range(last + 1, len(rows)) if rows[k] == sid), None)
            if j is None:
                j = last + 1
                rows.insert(j, sid)
                for earlier in assignments:
                    for i, v in enumerate(earlier):
                        if v >= j:
                            earlier[i] = v + 1
            last = j
            assign.append(j)
        assignments.append(assign)
    return rows, assignments


def line_table(db: sqlite3.Connection, line: str, service_date: date) -> list[dict]:
    """Tidtabellsmatris per riktning: hallplatser som rader, turer som kolumner."""
    by_trip: dict[str, dict] = {}
    for r in db.execute(_LINE_DAY_SQL, {"line": line, "date": service_date.isoformat()}):
        trip = by_trip.setdefault(r["trip_id"], {
            "direction_id": r["direction_id"], "destination": r["destination"],
            "stops": []})
        trip["stops"].append((r["station_id"], r["stop_name"], r["departure_s"],
                              r["pickup"], r["booking_msg"]))

    directions = []
    for dir_id in sorted({t["direction_id"] for t in by_trip.values()}):
        trips = [t for t in by_trip.values() if t["direction_id"] == dir_id]
        trips.sort(key=lambda t: (len(t["stops"]), -t["stops"][0][2]), reverse=True)
        order, assignments = _align_stop_orders(
            [[sid for sid, _, _, _, _ in t["stops"]] for t in trips])
        names = {sid: name for t in trips for sid, name, _, _, _ in t["stops"]}

        # a = endast avstigande (pickup_type 1), f = forbestalls (2/3)
        used_marks = set()
        booking_messages = set()
        columns = []
        for t, assign in zip(trips, assignments):
            times = [""] * len(order)
            for (_, _, dep_s, pickup, booking_msg), row_idx in zip(t["stops"], assign):
                mark = "a" if pickup == 1 else "f" if pickup in (2, 3) else ""
                if mark:
                    used_marks.add(mark)
                if mark == "f" and booking_msg:
                    booking_messages.add(booking_msg)
                times[row_idx] = fmt_hhmm(dep_s) + mark
            columns.append({"destination": t["destination"],
                            "first_departure_s": t["stops"][0][2],
                            "times": times})
        # Langsta turen forst gav stabilast radordning; visa kolumnerna
        # i avgangstidsordning.
        columns.sort(key=lambda c: c["first_departure_s"])

        destinations = sorted({t["destination"] for t in trips})
        directions.append({
            "direction_id": dir_id,
            "destinations": destinations,
            "stops": [{"station_id": sid, "name": names[sid]} for sid in order],
            "trips": columns,
            "marks": sorted(used_marks),
            "booking_messages": sorted(booking_messages),
        })
    return directions


def feed_horizon(db: sqlite3.Connection) -> date | None:
    row = db.execute("SELECT max(date) AS d FROM service_dates").fetchone()
    return date.fromisoformat(row["d"]) if row["d"] else None


DAY_TYPES = {"vardag": (0, 1, 2, 3, 4), "lordag": (5,), "sondag": (6,)}


def find_service_day(db: sqlite3.Connection, line: str, day_type: str,
                     today: date) -> date | None:
    """Forsta datum (fran idag) av given dagtyp dar linjen har trafik."""
    weekdays = DAY_TYPES[day_type]
    horizon = feed_horizon(db)
    if horizon is None:
        return None
    d = today
    while d <= horizon:
        if d.weekday() in weekdays and _line_runs_on(db, line, d):
            return d
        d += timedelta(days=1)
    return None


def _line_runs_on(db: sqlite3.Connection, line: str, d: date) -> bool:
    row = db.execute(
        "SELECT 1 FROM trips t JOIN routes r ON r.route_id = t.route_id "
        "JOIN service_dates sd ON sd.service_id = t.service_id "
        "WHERE r.short_name = ? AND r.is_local = 1 AND sd.date = ? LIMIT 1",
        (line, d.isoformat())).fetchone()
    return row is not None


def _day_signature(db: sqlite3.Connection, line: str, d: date) -> frozenset:
    rows = db.execute(
        "SELECT t.direction_id, t.destination, st.departure_s FROM trips t "
        "JOIN routes r ON r.route_id = t.route_id "
        "JOIN service_dates sd ON sd.service_id = t.service_id "
        "JOIN stop_times st ON st.trip_id = t.trip_id "
        "WHERE r.short_name = ? AND r.is_local = 1 AND sd.date = ?",
        (line, d.isoformat())).fetchall()
    return frozenset((r["direction_id"], r["destination"], r["departure_s"]) for r in rows)


def next_table_change(db: sqlite3.Connection, line: str, ref_date: date) -> date | None:
    """Nasta datum (samma veckodag) da linjens tabell skiljer sig fran ref_date."""
    horizon = feed_horizon(db)
    if horizon is None:
        return None
    ref_sig = _day_signature(db, line, ref_date)
    d = ref_date + timedelta(days=7)
    while d <= horizon:
        if _day_signature(db, line, d) != ref_sig:
            return d
        d += timedelta(days=7)
    return None


_WEEKDAYS_SV = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"]
_MONTHS_SV = ["januari", "februari", "mars", "april", "maj", "juni", "juli",
              "augusti", "september", "oktober", "november", "december"]


def format_date_sv(d: date) -> str:
    return f"{_WEEKDAYS_SV[d.weekday()]} {d.day} {_MONTHS_SV[d.month - 1]}"


def station_rt_keys(db: sqlite3.Connection, station_id: str) -> tuple[set[str], set[str]]:
    """(route_ids, stop_ids) for matchning mot ServiceAlerts informed_entity."""
    stop_ids = {r["stop_id"] for r in db.execute(
        "SELECT stop_id FROM stops WHERE parent_station = ? OR stop_id = ?",
        (station_id, station_id))}
    route_ids = {r["route_id"] for r in db.execute(
        "SELECT DISTINCT t.route_id FROM stop_times st JOIN trips t ON t.trip_id = st.trip_id "
        "JOIN stops s ON s.stop_id = st.stop_id "
        "WHERE s.parent_station = ? OR s.stop_id = ?", (station_id, station_id))}
    return route_ids, stop_ids


def line_route_ids(db: sqlite3.Connection, line: str) -> set[str]:
    return {r["route_id"] for r in db.execute(
        "SELECT route_id FROM routes WHERE short_name = ? AND is_local = 1", (line,))}


# Lokala linjers avgangar fran en station en given trafikdag - underlag
# for utskrivbara stolptidtabeller.
_STOP_DAY_SQL = """
SELECT r.short_name AS line, t.direction_id, t.destination, st.departure_s, st.pickup,
       COALESCE(br.message, '') AS booking_msg
FROM stop_times st
JOIN stops s ON s.stop_id = st.stop_id
JOIN trips t ON t.trip_id = st.trip_id
JOIN routes r ON r.route_id = t.route_id
JOIN service_dates sd ON sd.service_id = t.service_id
LEFT JOIN booking_rules br ON br.rule_id = st.booking_rule
WHERE (s.parent_station = :sid OR s.stop_id = :sid)
  AND sd.date = :date AND st.is_last = 0 AND st.pickup != 1 AND r.is_local = 1
ORDER BY st.departure_s
"""


def stop_day_departures(db: sqlite3.Connection, station_id: str,
                        service_date: date) -> list[sqlite3.Row]:
    return db.execute(_STOP_DAY_SQL, {
        "sid": station_id, "date": service_date.isoformat()}).fetchall()
