"""Bygger appens SQLite-databas fran cachad GTFS-zip.

Databasen ar en engangsgenererad artefakt: den byggs om fran zippen
varje natt och byts atomiskt. Inga migrationer - schemat lever har.

Scope: hallplatser som trafikeras av de lokala linjerna (config.LOCAL_LINES)
importeras, men ALLA avgangar vid dessa hallplatser tas med, aven regionala
linjer - hallplatsvyn ska visa allt som gar fran hallplatsen.

Datakvirkar i Din Tur-feeden som hanteras har:
- calendar.txt har nollade veckodagsmasker; trafikdagar kommer i praktiken
  enbart fran calendar_dates.txt. Bada tolkas korrekt oavsett.
- trip_headsign ar tomt; destination harledas fran turens sista hallplats.
"""

import csv
import io
import json
import logging
import sqlite3
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

from app import config

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE routes (
    route_id TEXT PRIMARY KEY,
    short_name TEXT NOT NULL,
    long_name TEXT NOT NULL DEFAULT '',
    is_local INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE stops (
    stop_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    location_type INTEGER NOT NULL DEFAULT 0,
    parent_station TEXT NOT NULL DEFAULT '',
    platform_code TEXT NOT NULL DEFAULT ''
);
CREATE TABLE trips (
    trip_id TEXT PRIMARY KEY,
    route_id TEXT NOT NULL,
    service_id TEXT NOT NULL,
    direction_id INTEGER NOT NULL DEFAULT 0,
    destination TEXT NOT NULL DEFAULT ''
);
CREATE TABLE stop_times (
    trip_id TEXT NOT NULL,
    stop_seq INTEGER NOT NULL,
    stop_id TEXT NOT NULL,
    departure_s INTEGER NOT NULL,
    is_last INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (trip_id, stop_seq)
);
CREATE TABLE service_dates (
    service_id TEXT NOT NULL,
    date TEXT NOT NULL,
    PRIMARY KEY (service_id, date)
);
CREATE INDEX idx_stop_times_stop ON stop_times (stop_id);
CREATE INDEX idx_trips_route ON trips (route_id);
CREATE INDEX idx_service_dates_date ON service_dates (date);
"""

WEEKDAY_COLS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _read_csv(zf: zipfile.ZipFile, name: str) -> list[dict]:
    with zf.open(name) as f:
        return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))


def _time_to_seconds(value: str) -> int:
    """GTFS-tid till sekunder. Kan vara >24:00 for turer efter midnatt."""
    h, m, s = value.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def _gtfs_date(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def _service_dates(calendar: list[dict], calendar_dates: list[dict],
                   service_ids: set[str]) -> list[tuple[str, str]]:
    dates: dict[str, set[date]] = {sid: set() for sid in service_ids}
    for row in calendar:
        sid = row["service_id"]
        if sid not in dates:
            continue
        active_weekdays = {i for i, col in enumerate(WEEKDAY_COLS) if row[col] == "1"}
        if not active_weekdays:
            continue
        d, end = _gtfs_date(row["start_date"]), _gtfs_date(row["end_date"])
        while d <= end:
            if d.weekday() in active_weekdays:
                dates[sid].add(d)
            d += timedelta(days=1)
    for row in calendar_dates:
        sid = row["service_id"]
        if sid not in dates:
            continue
        d = _gtfs_date(row["date"])
        if row["exception_type"] == "1":
            dates[sid].add(d)
        else:
            dates[sid].discard(d)
    return [(sid, d.isoformat()) for sid, ds in dates.items() for d in sorted(ds)]


def build_database(zip_path: Path = config.GTFS_ZIP_PATH,
                   db_path: Path = config.DB_PATH) -> dict:
    """Bygg ny databas fran zippen och byt atomiskt. Returnerar statistik."""
    with zipfile.ZipFile(zip_path) as zf:
        routes = {r["route_id"]: r for r in _read_csv(zf, "routes.txt")}
        trips = {t["trip_id"]: t for t in _read_csv(zf, "trips.txt")}
        stops = {s["stop_id"]: s for s in _read_csv(zf, "stops.txt")}
        calendar = _read_csv(zf, "calendar.txt")
        calendar_dates = _read_csv(zf, "calendar_dates.txt")
        feed_info = _read_csv(zf, "feed_info.txt")

        stop_times: dict[str, list[tuple[int, str, int]]] = {}
        with zf.open("stop_times.txt") as f:
            for row in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")):
                stop_times.setdefault(row["trip_id"], []).append(
                    (int(row["stop_sequence"]), row["stop_id"],
                     _time_to_seconds(row["departure_time"])))

    local_route_ids = {rid for rid, r in routes.items()
                       if r["route_short_name"] in config.LOCAL_LINES}
    local_trip_ids = {tid for tid, t in trips.items()
                      if t["route_id"] in local_route_ids}

    # Hallplatser (stationsniva) dar nagon lokal linje stannar
    scope_stations = set()
    for tid in local_trip_ids:
        for _, stop_id, _ in stop_times.get(tid, []):
            stop = stops[stop_id]
            scope_stations.add(stop["parent_station"] or stop_id)

    # Alla plattformar/lagen som hor till dessa stationer
    scope_stop_ids = {sid for sid, s in stops.items()
                      if (s["parent_station"] or sid) in scope_stations}

    kept_trips: dict[str, list[tuple[int, str, int]]] = {}
    for tid, rows in stop_times.items():
        kept_rows = [r for r in rows if r[1] in scope_stop_ids]
        if kept_rows:
            kept_trips[tid] = kept_rows

    kept_service_ids = {trips[tid]["service_id"] for tid in kept_trips}
    kept_route_ids = {trips[tid]["route_id"] for tid in kept_trips}
    service_date_rows = _service_dates(calendar, calendar_dates, kept_service_ids)

    tmp_path = db_path.with_suffix(".sqlite.tmp")
    tmp_path.unlink(missing_ok=True)
    db = sqlite3.connect(tmp_path)
    db.executescript(SCHEMA)

    db.executemany(
        "INSERT INTO routes VALUES (?, ?, ?, ?)",
        [(rid, routes[rid]["route_short_name"], routes[rid]["route_long_name"],
          int(rid in local_route_ids)) for rid in kept_route_ids])

    stop_rows = []
    for sid in scope_stop_ids | scope_stations:
        s = stops[sid]
        stop_rows.append((sid, s["stop_name"], float(s["stop_lat"]), float(s["stop_lon"]),
                          int(s["location_type"] or 0), s["parent_station"],
                          s["platform_code"]))
    db.executemany("INSERT INTO stops VALUES (?, ?, ?, ?, ?, ?, ?)", stop_rows)

    trip_rows, st_rows = [], []
    for tid, kept_rows in kept_trips.items():
        t = trips[tid]
        full_rows = stop_times[tid]
        last_seq, last_stop_id, _ = max(full_rows)
        destination = stops[last_stop_id]["stop_name"]
        trip_rows.append((tid, t["route_id"], t["service_id"],
                          int(t["direction_id"] or 0), destination))
        for seq, stop_id, dep_s in kept_rows:
            st_rows.append((tid, seq, stop_id, dep_s, int(seq == last_seq)))
    db.executemany("INSERT INTO trips VALUES (?, ?, ?, ?, ?)", trip_rows)
    db.executemany("INSERT INTO stop_times VALUES (?, ?, ?, ?, ?)", st_rows)
    db.executemany("INSERT INTO service_dates VALUES (?, ?)", service_date_rows)

    stats = {
        "feed_version": feed_info[0]["feed_version"] if feed_info else "",
        "downloaded_at": datetime.fromtimestamp(
            zip_path.stat().st_mtime, tz=config.TZ).isoformat(timespec="seconds"),
        "imported_at": datetime.now(tz=config.TZ).isoformat(timespec="seconds"),
        "stations": len(scope_stations),
        "stops": len(stop_rows),
        "routes": len(kept_route_ids),
        "trips": len(trip_rows),
        "stop_times": len(st_rows),
        "service_dates": len(service_date_rows),
    }
    db.executemany("INSERT INTO meta VALUES (?, ?)",
                   [(k, str(v)) for k, v in stats.items()])
    db.commit()
    db.close()

    tmp_path.replace(db_path)
    log.info("Databas ombyggd: %s", json.dumps(stats, ensure_ascii=False))
    return stats


def refresh(force_download: bool = False) -> dict:
    """Hela nattliga flodet: hamta zip vid behov och bygg om databasen."""
    from app.services.trafiklab import fetch_static_zip
    fetch_static_zip(force=force_download)
    return build_database()


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Bygg om GTFS-databasen fran cachen")
    parser.add_argument("--force-download", action="store_true",
                        help="ladda ner ny zip aven om cachen ar farsk (kvotbelagt!)")
    args = parser.parse_args()
    print(json.dumps(refresh(args.force_download), indent=2, ensure_ascii=False))
