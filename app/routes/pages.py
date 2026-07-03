from datetime import datetime

from fastapi import APIRouter, HTTPException, Request

from app import config, timetable
from app.database import get_meta, open_db
from app.deps import templates

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
    return templates.TemplateResponse(request, "index.html", {
        **_base_context(request), "stations": stations})


@router.get("/hallplats/{station_id}")
def stop_page(request: Request, station_id: str):
    now = datetime.now(tz=config.TZ)
    with open_db() as db:
        station = timetable.get_station(db, station_id)
        if station is None:
            raise HTTPException(404, "Hållplatsen finns inte")
        lines = timetable.lines_at_station(db, station_id)
        departures = timetable.upcoming_departures(db, station_id, now)
    return templates.TemplateResponse(request, "stop.html", {
        **_base_context(request),
        "station": station,
        "lines": lines,
        "departures": departures,
        "now_time": now.strftime("%H:%M"),
    })
