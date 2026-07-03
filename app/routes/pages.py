from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request

from app import config, timetable
from app.database import get_meta, open_db
from app.deps import templates
from app.services import realtime

router = APIRouter()


def _base_context(request: Request) -> dict:
    meta = get_meta()
    return {
        "request": request,
        "data_updated": meta.get("downloaded_at", "")[:10],
        "feed_version": meta.get("feed_version", ""),
    }


@router.get("/")
def index(request: Request):
    with open_db() as db:
        stations = timetable.list_stations(db)
        lines = timetable.local_lines(db)
    return templates.TemplateResponse(request, "index.html", {
        **_base_context(request), "stations": stations, "lines": lines})


@router.get("/linje/{line}")
def line_page(request: Request, line: str, typ: str = "vardag"):
    if typ not in timetable.DAY_TYPES:
        raise HTTPException(404, "Okänd dagtyp")
    today = datetime.now(tz=config.TZ).date()
    with open_db() as db:
        if line not in timetable.local_lines(db):
            raise HTTPException(404, "Linjen finns inte")
        rep_date = timetable.find_service_day(db, line, typ, today)
        directions = timetable.line_table(db, line, rep_date) if rep_date else []
        change_date = timetable.next_table_change(db, line, rep_date) if rep_date else None
        route_ids = timetable.line_route_ids(db, line)
    alerts = realtime.alerts_for(route_ids, set())

    # Varna bara nar linjen hoppar over nasta naturliga dag av dagtypen
    # (t.ex. 590 som saknar sommartrafik) - inte nar rep_date bara ar
    # nasta kommande vardag/lordag/sondag.
    natural_next = today
    while natural_next.weekday() not in timetable.DAY_TYPES[typ]:
        natural_next += timedelta(days=1)
    skips_ahead = rep_date is not None and rep_date > natural_next

    # Bokstavsmarkering for grenvarianter (turer med annan slutdestination)
    for d in directions:
        if len(d["destinations"]) > 1:
            letters = {dest: chr(ord("a") + i) for i, dest in enumerate(d["destinations"])}
            d["variant_letters"] = letters
            for trip in d["trips"]:
                trip["variant"] = letters[trip["destination"]]
        else:
            d["variant_letters"] = {}

    return templates.TemplateResponse(request, "line.html", {
        **_base_context(request),
        "line": line,
        "typ": typ,
        "day_types": [("vardag", "Vardagar"), ("lordag", "Lördagar"), ("sondag", "Söndagar")],
        "rep_date": rep_date,
        "rep_date_sv": timetable.format_date_sv(rep_date) if rep_date else None,
        "rep_in_future": skips_ahead,
        "change_date_sv": timetable.format_date_sv(change_date) if change_date else None,
        "directions": directions,
        "alerts": alerts,
    })


@router.get("/hallplats/{station_id}")
def stop_page(request: Request, station_id: str):
    now = datetime.now(tz=config.TZ)
    with open_db() as db:
        station = timetable.get_station(db, station_id)
        if station is None:
            raise HTTPException(404, "Hållplatsen finns inte")
        lines = timetable.lines_at_station(db, station_id)
        departures = timetable.upcoming_departures(db, station_id, now)
        route_ids, stop_ids = timetable.station_rt_keys(db, station_id)
    realtime_ok = realtime.enrich_departures(departures, now)
    alerts = realtime.alerts_for(route_ids, stop_ids)
    return templates.TemplateResponse(request, "stop.html", {
        **_base_context(request),
        "station": station,
        "lines": lines,
        "departures": departures,
        "realtime_ok": realtime_ok,
        "alerts": alerts,
        "now_time": now.strftime("%H:%M"),
    })
