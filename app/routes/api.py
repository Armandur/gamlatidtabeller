from datetime import datetime

from fastapi import APIRouter, HTTPException

from app import config, timetable
from app.database import DatabaseMissing, get_meta, open_db
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
def departures(station_id: str, limit: int = 20):
    """Kommande avgangar - pollas av hallplatssidan for uppdatering."""
    now = datetime.now(tz=config.TZ)
    with open_db() as db:
        station = timetable.get_station(db, station_id)
        if station is None:
            raise HTTPException(404, "Hållplatsen finns inte")
        deps = timetable.upcoming_departures(db, station_id, now, min(limit, 50))
    for d in deps:
        d["when"] = d["when"].isoformat(timespec="minutes")
    return {"station": station["name"], "generated_at": now.strftime("%H:%M"),
            "departures": deps}
