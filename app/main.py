import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI

from app import config, gtfs_import
from app.database import DatabaseMissing, get_meta
from app.services.trafiklab import cache_age_hours

log = logging.getLogger(__name__)


def _seconds_until_next_refresh() -> float:
    now = datetime.now(tz=config.TZ)
    target = now.replace(hour=config.NIGHTLY_REFRESH_HOUR,
                         minute=config.NIGHTLY_REFRESH_MINUTE,
                         second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def _nightly_refresh_loop():
    while True:
        await asyncio.sleep(_seconds_until_next_refresh())
        try:
            await asyncio.to_thread(gtfs_import.refresh)
        except Exception:
            log.exception("Nattlig GTFS-uppdatering misslyckades, kor vidare pa befintlig data")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Bygg databasen vid start om den saknas men zip-cachen finns
    if not config.DB_PATH.exists() and config.GTFS_ZIP_PATH.exists():
        await asyncio.to_thread(gtfs_import.build_database)
    task = asyncio.create_task(_nightly_refresh_loop())
    yield
    task.cancel()


app = FastAPI(title="Gamla tidtabeller", lifespan=lifespan)


@app.get("/api/status")
def status():
    """Datastatus: feedversion, alder pa cache och databas."""
    try:
        meta = get_meta()
    except DatabaseMissing:
        return {"ok": False, "detail": "Databasen ar inte byggd an"}
    age = cache_age_hours()
    return {"ok": True, "zip_cache_age_hours": round(age, 1) if age is not None else None,
            **meta}
