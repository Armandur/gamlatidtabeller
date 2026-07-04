"""Utskrivbara stolptidtabeller som PDF (WeasyPrint + QR-kod).

En lapp per hallplats: lokala linjers avgangar grupperade per linje
och riktning, med kolumner for vardag/lordag/sondag och QR-kod till
hallplatsens live-vy. Dagtypernas datum valjs inom samma
tidtabellsperiod som vardagsdatumet sa att lappen ar konsistent -
saknar en dagtyp trafik i perioden markeras det, med not om nar
nasta tabell borjar galla.
"""

import sqlite3
from datetime import date, datetime, timedelta

import segno
import weasyprint

from app import config, timetable
from app.database import get_meta
from app.deps import templates

DAY_LABELS = [("vardag", "Måndag–fredag"), ("lordag", "Lördag"), ("sondag", "Söndag")]

PAGE_SIZES = {"a5": "A5", "a4": "A4"}


def _hour_groups(departures: list[tuple[int, str]]) -> list[dict]:
    """[(departure_s, variantbokstav)] -> radlista {hour, minutes: [(mm, bokstav)]}."""
    hours: dict[int, list] = {}
    for dep_s, letter in sorted(departures):
        hours.setdefault(dep_s // 3600 % 24, []).append((dep_s % 3600 // 60, letter))
    return [{"hour": h, "minutes": mm} for h, mm in sorted(hours.items())]


def build_lapp_context(db: sqlite3.Connection, station: sqlite3.Row) -> dict:
    today = datetime.now(tz=config.TZ).date()
    station_id = station["stop_id"]

    # (linje, riktning) -> block; dagkolumner fylls per dagtyp
    blocks: dict[tuple[str, int], dict] = {}
    notes: set[str] = set()

    lines = [l["line"] for l in timetable.lines_at_station(db, station_id) if l["is_local"]]
    natural_weekday = today
    while natural_weekday.weekday() > 4:
        natural_weekday += timedelta(days=1)
    for line in lines:
        vardag = timetable.find_service_day(db, line, "vardag", today)
        if vardag is None:
            continue
        change = timetable.next_table_change(db, line, vardag)
        if change:
            notes.add(f"Linje {line}: ny tidtabell gäller från {timetable.format_date_sv(change)}.")
        if vardag > natural_weekday:
            notes.add(f"Linje {line}: tiderna gäller först från {timetable.format_date_sv(vardag)} - "
                      "linjen har ingen trafik just nu.")
        for day_key, day_label in DAY_LABELS:
            d = timetable.find_service_day(db, line, day_key, today)
            in_period = d is not None and (change is None or d < change)
            rows = timetable.stop_day_departures(db, station_id, d) if in_period else []
            for r in rows:
                if r["line"] != line:
                    continue
                block = blocks.setdefault((line, r["direction_id"]), {
                    "line": line, "destinations": {}, "days": {}})
                block["destinations"][r["destination"]] = \
                    block["destinations"].get(r["destination"], 0) + 1
                block["days"].setdefault(day_key, []).append(
                    (r["departure_s"], r["destination"]))

    out_blocks = []
    for (line, _dir), block in sorted(blocks.items()):
        dests = sorted(block["destinations"], key=block["destinations"].get, reverse=True)
        letters = {d: chr(ord("a") + i) for i, d in enumerate(sorted(dests))} \
            if len(dests) > 1 else {}
        day_cols = []
        for day_key, day_label in DAY_LABELS:
            deps = [(s, letters.get(dest, "")) for s, dest in block["days"].get(day_key, [])]
            day_cols.append({"label": day_label,
                             "hours": _hour_groups(deps) if deps else None})
        out_blocks.append({
            "line": line,
            "heading": " / ".join(dests[:2]),
            "letters": sorted(letters.items(), key=lambda kv: kv[1]),
            "day_cols": day_cols,
        })

    meta = get_meta()
    live_url = f"{config.BASE_URL}/hallplats/{station_id}"
    qr = segno.make(live_url, error="m")
    return {
        "station": station,
        "blocks": out_blocks,
        "notes": sorted(notes),
        "updated": meta.get("feed_version", ""),
        "printed": today.isoformat(),
        "live_url": live_url,
        "qr_data_uri": qr.svg_data_uri(scale=4),
    }


def render_lapp_pdf(db: sqlite3.Connection, station: sqlite3.Row,
                    page_format: str = "a5") -> bytes:
    context = build_lapp_context(db, station)
    context["page_size"] = PAGE_SIZES.get(page_format, "A5")
    html = templates.env.get_template("print/lapp.html").render(context)
    return weasyprint.HTML(string=html).write_pdf()
