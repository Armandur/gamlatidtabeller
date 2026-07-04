"""Utskriftsstudio: val av hallplatser och batch-PDF som bakgrundsjobb.

Batchar tar ~1 s per hallplats, darfor kors de som jobb: POST startar
och returnerar jobb-id direkt, klienten pollar status (med progress)
och hamtar fardig PDF pa egen URL. Jobben bor i minnet: max ett
pagaende per IP, stadas efter TTL. IP anvands bara transient for
samtidighetssparren - loggas eller lagras inte.
"""

import json
import logging
import secrets
import time

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import Response

from app import printing, timetable
from app.database import open_db
from app.deps import templates
from app.routes.pages import _base_context

log = logging.getLogger(__name__)

router = APIRouter()

MAX_BATCH = 150
JOB_TTL = 15 * 60
MAX_RUNNING = 2

_jobs: dict[str, dict] = {}


def _purge_jobs():
    cutoff = time.time() - JOB_TTL
    for jid in [j for j, job in _jobs.items() if job["created"] < cutoff]:
        del _jobs[jid]


def _run_job(job_id: str, id_list: list[str], page_format: str, two_up: bool):
    job = _jobs[job_id]
    try:
        with open_db() as db:
            stations = [s for i in id_list
                        if (s := timetable.get_station(db, i)) is not None]
            job["total"] = len(stations)

            def progress(done):
                job["progress"] = done

            pdf = printing.render_batch_pdf(db, stations, page_format,
                                            two_up, progress)
        job["pdf"] = pdf
        job["filename"] = f"hallplatslappar-{len(stations)}st-{page_format}.pdf"
        job["status"] = "klar"
    except Exception:
        log.exception("Utskriftsjobb %s misslyckades", job_id)
        job["status"] = "fel"


@router.get("/studio")
def studio(request: Request):
    """Utskriftsstudio: valj hallplatser via karta/lista, batch-PDF."""
    with open_db() as db:
        stations = timetable.list_stations(db)
    station_data = [{"id": s["stop_id"], "name": s["name"],
                     "lat": s["lat"], "lon": s["lon"]} for s in stations]
    return templates.TemplateResponse(request, "studio.html", {
        **_base_context(request),
        "stations_json": json.dumps(station_data, ensure_ascii=False),
        "station_count": len(station_data),
    })


@router.post("/studio/pdf")
def create_job(request: Request, background_tasks: BackgroundTasks,
               ids: str = Form(...), format: str = Form("a5"),
               skarlinje: bool = Form(False)):
    if format not in printing.PAGE_SIZES:
        raise HTTPException(404, "Okänt pappersformat")
    id_list = [i for i in ids.split(",") if i]
    if not id_list:
        raise HTTPException(400, "Inga hållplatser valda.")
    if len(id_list) > MAX_BATCH:
        raise HTTPException(400, f"Max {MAX_BATCH} hållplatser per utskrift.")

    _purge_jobs()
    client_ip = request.client.host if request.client else "?"
    active = [j for j in _jobs.values() if j["status"] == "arbetar"]
    if any(j["ip"] == client_ip for j in active):
        raise HTTPException(429, "Du har redan ett pågående utskriftsjobb - "
                                 "vänta tills det är klart.")
    if len(active) >= MAX_RUNNING:
        raise HTTPException(503, "Hög belastning - försök igen om en stund.")

    job_id = secrets.token_urlsafe(8)
    _jobs[job_id] = {"status": "arbetar", "progress": 0, "total": len(id_list),
                     "ip": client_ip, "created": time.time()}
    background_tasks.add_task(_run_job, job_id, id_list, format, skarlinje)
    return {"job_id": job_id}


@router.get("/studio/jobb/{job_id}")
def job_status(job_id: str):
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Jobbet finns inte (eller har städats bort).")
    return {"status": job["status"], "progress": job["progress"],
            "total": job["total"]}


@router.get("/studio/jobb/{job_id}/pdf")
def job_pdf(job_id: str):
    job = _jobs.get(job_id)
    if job is None or job["status"] != "klar":
        raise HTTPException(404, "Ingen färdig PDF för det jobbet.")
    return Response(job["pdf"], media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="{job["filename"]}"'})
