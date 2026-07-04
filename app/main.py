import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config, gtfs_import
from app.database import DatabaseMissing
from app.deps import templates
from app.routes import api, pages, studio
from app.services import realtime

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
    tasks = [asyncio.create_task(_nightly_refresh_loop())]
    if config.TRAFIKLAB_RT_KEY:
        tasks.append(asyncio.create_task(realtime.poll_loop()))
    else:
        log.warning("TRAFIKLAB_RT_KEY saknas - realtid avstangd")
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(title="Gamla tidtabeller", lifespan=lifespan)
app.include_router(pages.router)
app.include_router(api.router)
app.include_router(studio.router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.exception_handler(DatabaseMissing)
def database_missing(request: Request, exc: DatabaseMissing):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"ok": False, "detail": "Tidtabellsdatan är inte laddad än"},
                            status_code=503)
    return templates.TemplateResponse(request, "error.html", {
        "request": request,
        "message": "Tidtabellsdatan är inte laddad än. Försök igen om en stund.",
    }, status_code=503)
