import re
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app import config, printing, timetable
from app.database import get_meta, open_db
from app.deps import templates
from app.services import realtime

router = APIRouter()

# Enkel rate limit for PDF-generering (WeasyPrint ar dyr). Bara
# tidsstamplar i minnet, per klient-IP, aldrig loggat eller lagrat.
_pdf_hits: dict[str, list[float]] = {}


def _pdf_rate_ok(ip: str, per_minute: int = 10) -> bool:
    now = time.time()
    hits = [t for t in _pdf_hits.get(ip, []) if now - t < 60]
    ok = len(hits) < per_minute
    hits.append(now)
    _pdf_hits[ip] = hits
    return ok


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

    # Bokstavsmarkering for grenvarianter (turer med annan slutdestination).
    # a och f ar reserverade for "endast avstigande" resp. "forbestalls".
    variant_alphabet = "bcdeghijklmnopqrstuvxyz"
    for d in directions:
        if len(d["destinations"]) > 1:
            letters = {dest: variant_alphabet[i] for i, dest in enumerate(d["destinations"])}
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


@router.get("/hallplats/{station_id}/lapp.pdf")
def lapp_pdf(request: Request, station_id: str, format: str = "a5"):
    """Utskrivbar stolptidtabell for hallplatsen."""
    if format not in printing.PAGE_SIZES:
        raise HTTPException(404, "Okänt pappersformat")
    client_ip = request.client.host if request.client else "?"
    if not _pdf_rate_ok(client_ip):
        raise HTTPException(429, "För många utskrifter på kort tid - vänta en minut.")
    with open_db() as db:
        station = timetable.get_station(db, station_id)
        if station is None:
            raise HTTPException(404, "Hållplatsen finns inte")
        pdf = printing.render_lapp_pdf(db, station, format)
    slug = re.sub(r"[^a-z0-9]+", "-", station["name"].lower()).strip("-")
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="busstider-{slug}-{format}.pdf"'})


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
