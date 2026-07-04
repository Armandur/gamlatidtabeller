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


def _join_sv(items: list[str]) -> str:
    """"501", "501 och 502", "501, 502 och 503"."""
    items = sorted(set(items))
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " och " + items[-1]


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
    changes: dict[date, list[str]] = {}
    future_starts: dict[date, list[str]] = {}

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
            changes.setdefault(change, []).append(line)
        if vardag > natural_weekday:
            future_starts.setdefault(vardag, []).append(line)
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
        # Dagar utan trafik blir en textrad i stallet for tom kolumn,
        # sa att blocket kan krympa och nasta linje lagga sig bredvid.
        day_cols, missing = [], []
        for day_key, day_label in DAY_LABELS:
            deps = [(s, letters.get(dest, "")) for s, dest in block["days"].get(day_key, [])]
            if deps:
                day_cols.append({"label": day_label, "hours": _hour_groups(deps)})
            else:
                missing.append(day_label.lower())
        out_blocks.append({
            "line": line,
            "heading": " / ".join(dests[:2]),
            "letters": sorted(letters.items(), key=lambda kv: kv[1]),
            "day_cols": day_cols,
            "missing_text": "Ingen trafik " + " och ".join(missing) if missing else "",
            "width_class": f"block-{len(day_cols)}",
        })

    # Packa blocken i rader om max tre dagkolumner - varje rad ar en
    # egen div sa att WeasyPrint kan sidbryta mellan rader (en enda
    # inline-container vagrar den bryta).
    block_rows, row, used = [], [], 0
    for b in out_blocks:
        cols = len(b["day_cols"])
        if row and used + cols > 3:
            block_rows.append(row)
            row, used = [], 0
        row.append(b)
        used += cols
    if row:
        block_rows.append(row)

    # Samma budskap for flera linjer grupperas till en not
    notes = []
    for d, note_lines in sorted(changes.items()):
        notes.append(f"Linje {_join_sv(note_lines)}: ny tidtabell gäller från "
                     f"{timetable.format_date_sv(d)}.")
    for d, note_lines in sorted(future_starts.items()):
        notes.append(f"Linje {_join_sv(note_lines)}: tiderna gäller först från "
                     f"{timetable.format_date_sv(d)} - ingen trafik just nu.")

    meta = get_meta()
    live_url = f"{config.BASE_URL}/hallplats/{station_id}"
    qr = segno.make(live_url, error="m")
    return {
        "station": station,
        "blocks": out_blocks,
        "block_rows": block_rows,
        "notes": notes,
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
