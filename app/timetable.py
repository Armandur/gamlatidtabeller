"""Uppslag i tidtabellsdatabasen: hallplatser, linjer och kommande avgangar."""

import sqlite3
from datetime import date, datetime, timedelta

from app import config

# Avgangar vid en station (alla lagen) pa en given trafikdag.
# OBS: en trafikdags turer kan ga efter midnatt (departure_s > 86400),
# darfor slas gardagens trafikdag ihop med dagens vid uppslag.
_DEPARTURES_SQL = """
SELECT st.departure_s, r.short_name AS line, r.is_local, t.destination,
       t.trip_id, s.platform_code
FROM stop_times st
JOIN stops s ON s.stop_id = st.stop_id
JOIN trips t ON t.trip_id = st.trip_id
JOIN routes r ON r.route_id = t.route_id
JOIN service_dates sd ON sd.service_id = t.service_id
WHERE (s.parent_station = :sid OR s.stop_id = :sid)
  AND sd.date = :date AND st.is_last = 0 AND st.departure_s >= :from_s
ORDER BY st.departure_s
LIMIT :limit
"""

_LINES_SQL = """
SELECT r.short_name AS line, r.is_local, t.destination, count(*) AS n
FROM stop_times st
JOIN stops s ON s.stop_id = st.stop_id
JOIN trips t ON t.trip_id = st.trip_id
JOIN routes r ON r.route_id = t.route_id
WHERE (s.parent_station = :sid OR s.stop_id = :sid) AND st.is_last = 0
GROUP BY r.short_name, r.is_local, t.destination
"""


def _midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=config.TZ)


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

    # (trafikdag, fran-sekund): gardagens efter midnatt-turer, dagens
    # aterstaende, morgondagens fran start - tills limit ar fylld.
    plan = [(today - timedelta(days=1), now_s + 86400),
            (today, now_s),
            (today + timedelta(days=1), 0)]
    departures = []
    for service_date, from_s in plan:
        if len(departures) >= limit:
            break
        rows = db.execute(_DEPARTURES_SQL, {
            "sid": station_id, "date": service_date.isoformat(),
            "from_s": from_s, "limit": limit}).fetchall()
        for r in rows:
            when = _midnight(service_date) + timedelta(seconds=r["departure_s"])
            departures.append({
                "when": when,
                "time": when.strftime("%H:%M"),
                "in_minutes": max(0, int((when - now).total_seconds() // 60)),
                "other_day": when.date() != today,
                "line": r["line"],
                "is_local": bool(r["is_local"]),
                "destination": r["destination"],
                "platform": r["platform_code"],
                "trip_id": r["trip_id"],
            })
    departures.sort(key=lambda d: d["when"])
    return departures[:limit]
