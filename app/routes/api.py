from datetime import datetime

from fastapi import APIRouter, HTTPException

from app import config, timetable
from app.database import DatabaseMissing, get_meta, open_db
from app.services import realtime
from app.services.trafiklab import cache_age_hours

router = APIRouter(prefix="/api")


@router.get("/status")
def status():
    """Datastatus: feedversion, alder pa cache och databas."""
    try:
        meta = get_meta()
    except DatabaseMissing:
        return {"ok": False, "detail": "Databasen är inte byggd än"}
    age = cache_age_hours()
    return {"ok": True, "zip_cache_age_hours": round(age, 1) if age is not None else None,
            **meta}


@router.get("/hallplats/{station_id}/avgangar")
def departures(station_id: str, limit: int = 20, karta: bool = False):
    """Kommande avgangar - pollas av hallplatssidan for uppdatering."""
    realtime.mark_activity(map_interest=karta)
    now = datetime.now(tz=config.TZ)
    with open_db() as db:
        station = timetable.get_station(db, station_id)
        if station is None:
            raise HTTPException(404, "Hållplatsen finns inte")
        deps = timetable.upcoming_departures(db, station_id, now, min(limit, 50))
        route_ids, stop_ids = timetable.station_rt_keys(db, station_id)
    realtime_ok = realtime.enrich_departures(deps, now)
    alerts = realtime.alerts_for(route_ids, stop_ids)
    vehicles = realtime.vehicles_for_departures(deps)
    for d in deps:
        d["when"] = d["when"].isoformat(timespec="minutes")
    return {"station": station["name"], "generated_at": now.strftime("%H:%M"),
            "realtime_ok": realtime_ok, "alerts": alerts,
            "vehicles": vehicles, "departures": deps}
