"""Admin-granssnitt som egen ASGI-app pa egen port.

Kors i SAMMA process som publika appen (se app/run.py) - dashboarden
laser realtidsstatus och utskriftsjobb direkt ur modulernas minne.
Porten ar tankt att inte exponeras publikt; satt ADMIN_PASSWORD i
drift for inloggningsskydd ovanpa det.
"""

import logging
import secrets
import threading
import time
from datetime import datetime

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import config, gtfs_import, settings_store
from app.database import DatabaseMissing, get_meta, open_db
from app.deps import templates
from app.routes import studio
from app.services import realtime
from app.services.trafiklab import cache_age_hours

log = logging.getLogger(__name__)

app = FastAPI(title="Gamla tidtabeller - admin", docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=config.SESSION_SECRET,
                   session_cookie="gt_admin", same_site="lax")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Senaste/pagaende underhallsatgard (en i taget)
_action = {"running": False, "message": ""}


def _logged_in(request: Request) -> bool:
    return not config.ADMIN_PASSWORD or bool(request.session.get("inloggad"))


def _csrf_token(request: Request) -> str:
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(16)
    return request.session["csrf"]


def _check_csrf(request: Request, token: str) -> None:
    if not secrets.compare_digest(token.encode(), request.session.get("csrf", "").encode()):
        raise HTTPException(403, "Ogiltig CSRF-token - ladda om sidan och försök igen.")


def _run_action(label: str, fn) -> None:
    def worker():
        try:
            fn()
            _action["message"] = f"{label}: klart {datetime.now(tz=config.TZ):%H:%M:%S}"
        except Exception as exc:
            log.exception("%s misslyckades", label)
            _action["message"] = f"{label}: MISSLYCKADES - {exc}"
        finally:
            _action["running"] = False

    _action["running"] = True
    _action["message"] = f"{label}: pågår ..."
    threading.Thread(target=worker, daemon=True).start()


@app.get("/logga-in")
def login_form(request: Request):
    return templates.TemplateResponse(request, "admin/login.html", {
        "request": request, "csrf": _csrf_token(request)})


@app.post("/logga-in")
def login(request: Request, losenord: str = Form(...), csrf: str = Form(...)):
    _check_csrf(request, csrf)
    # bytes: compare_digest stodjer inte icke-ASCII-strangar (t.ex. aao)
    if not secrets.compare_digest(losenord.encode(), config.ADMIN_PASSWORD.encode()):
        time.sleep(0.6)
        return templates.TemplateResponse(request, "admin/login.html", {
            "request": request, "csrf": _csrf_token(request),
            "fel": "Fel lösenord."}, status_code=403)
    request.session["inloggad"] = True
    return RedirectResponse("/", 302)


@app.post("/logga-ut")
def logout(request: Request, csrf: str = Form(...)):
    _check_csrf(request, csrf)
    request.session.clear()
    return RedirectResponse("/logga-in", 302)


@app.get("/")
def dashboard(request: Request):
    if not _logged_in(request):
        return RedirectResponse("/logga-in", 302)
    try:
        meta = get_meta()
    except DatabaseMissing:
        meta = {}
    age = cache_age_hours()
    rt_age = (time.time() - realtime.state.updated_at
              if realtime.state.updated_at else None)
    jobs = [{"status": j["status"], "progress": j["progress"], "total": j["total"]}
            for j in studio._jobs.values()]
    stored = settings_store.load()
    return templates.TemplateResponse(request, "admin/dashboard.html", {
        "request": request,
        "csrf": _csrf_token(request),
        "meta": meta,
        "zip_age": f"{age:.1f}" if age is not None else None,
        "rt_fresh": realtime.state.fresh,
        "rt_age": f"{rt_age:.0f}" if rt_age is not None else None,
        "rt_trips": len(realtime.state.trip_updates),
        "rt_alerts": len(realtime.state.alerts),
        "rt_requests_today": realtime.state.requests_today,
        "rt_backoff": realtime.state.backoff_until > time.time(),
        "jobs": jobs,
        "local_lines": ", ".join(sorted(config.get_local_lines())),
        "base_url": config.get_base_url(),
        "has_overrides": bool(stored),
        "default_lines": ", ".join(sorted(config.LOCAL_LINES)),
        "default_base_url": config.BASE_URL,
        "action": _action,
        "password_set": bool(config.ADMIN_PASSWORD),
    })


@app.post("/uppdatera")
def update_gtfs(request: Request, csrf: str = Form(...), force: bool = Form(False)):
    if not _logged_in(request):
        return RedirectResponse("/logga-in", 302)
    _check_csrf(request, csrf)
    if _action["running"]:
        raise HTTPException(409, "En åtgärd pågår redan - vänta tills den är klar.")
    label = ("Hämta ny GTFS och bygg om (kvotbelagt anrop)" if force
             else "Bygg om databasen från cachad zip")
    _run_action(label, lambda: gtfs_import.refresh(force_download=force))
    return RedirectResponse("/", 302)


@app.post("/installningar")
def save_settings(request: Request, csrf: str = Form(...),
                  local_lines: str = Form(""), base_url: str = Form(""),
                  aterstall: bool = Form(False)):
    if not _logged_in(request):
        return RedirectResponse("/logga-in", 302)
    _check_csrf(request, csrf)
    if _action["running"]:
        raise HTTPException(409, "En åtgärd pågår redan - vänta tills den är klar.")

    old_lines = config.get_local_lines()
    if aterstall:
        settings_store.save({})
    else:
        values = {}
        lines = {token.strip() for token in local_lines.split(",") if token.strip()}
        if not lines:
            raise HTTPException(400, "Minst en linje måste anges.")
        if lines != set(config.LOCAL_LINES):
            values["local_lines"] = sorted(lines)
        cleaned_url = base_url.strip().rstrip("/")
        if cleaned_url and cleaned_url != config.BASE_URL:
            values["base_url"] = cleaned_url
        settings_store.save(values)

    if config.get_local_lines() != old_lines:
        _run_action("Linjeändring: bygg om databasen från cachad zip",
                    gtfs_import.build_database)
    return RedirectResponse("/", 302)


@app.get("/karta")
def vehicle_map(request: Request):
    """Diagnostikkarta: alla fordon i lanet ur VehiclePositions-feeden."""
    if not _logged_in(request):
        return RedirectResponse("/logga-in", 302)
    return templates.TemplateResponse(request, "admin/karta.html", {"request": request})


@app.get("/api/fordon")
def all_vehicles(request: Request):
    """Alla fordonspositioner just nu, berikade med linje/destination
    dar turen finns i var databas. Linjenummer for ovriga harleds ur
    trip_id-formatet 220LLL... (bekraftat monster i Din Tur-feeden)."""
    if not _logged_in(request):
        raise HTTPException(401, "Inte inloggad")
    realtime.mark_activity(map_interest=True)

    positions = dict(realtime.state.vehicle_positions)
    known = {}
    if positions:
        try:
            with open_db() as db:
                marks = ",".join("?" * len(positions))
                for r in db.execute(
                        f"SELECT t.trip_id, r.short_name, r.is_local, t.destination "
                        f"FROM trips t JOIN routes r ON r.route_id = t.route_id "
                        f"WHERE t.trip_id IN ({marks})", list(positions)):
                    known[r["trip_id"]] = r
        except DatabaseMissing:
            pass

    now = time.time()
    vehicles = []
    for tid, p in positions.items():
        row = known.get(tid)
        line = row["short_name"] if row else (tid[3:6].lstrip("0") or "?")
        vehicles.append({
            "trip_id": tid,
            "line": line,
            "destination": row["destination"] if row else "",
            "local": bool(row and row["is_local"]),
            "known": row is not None,
            "lat": p["lat"], "lon": p["lon"],
            "age_s": int(now - p["ts"]) if p["ts"] else None,
        })
    return {"fresh": realtime.state.fresh,
            "requests_today": realtime.state.requests_today,
            "generated_at": datetime.now(tz=config.TZ).strftime("%H:%M:%S"),
            "vehicles": vehicles}
