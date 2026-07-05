"""Utskrivbara stolptidtabeller som PDF (WeasyPrint + QR-kod).

En lapp per hallplats: lokala linjers avgangar grupperade per linje
och riktning, med kolumner for vardag/lordag/sondag och QR-kod till
hallplatsens live-vy. Dagtypernas datum valjs inom samma
tidtabellsperiod som vardagsdatumet sa att lappen ar konsistent -
saknar en dagtyp trafik i perioden markeras det, med not om nar
nasta tabell borjar galla.
"""

import io
import sqlite3
from datetime import date, datetime, timedelta

import pypdf
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


def line_day_plans(db: sqlite3.Connection, lines: list[str],
                   today: date) -> dict[str, dict]:
    """Per linje: vardagsdatum, tabellbytesdatum och datum per dagtyp
    (None om dagtypen saknar trafik inom perioden). Berakningen ar
    stationsoberoende och dyrast i hela lappflodet - gors en gang och
    ateranvands for alla hallplatser i en batch."""
    plans = {}
    for line in lines:
        vardag = timetable.find_service_day(db, line, "vardag", today)
        if vardag is None:
            continue
        change = timetable.next_table_change(db, line, vardag)
        days = {}
        for day_key, _ in DAY_LABELS:
            d = timetable.find_service_day(db, line, day_key, today)
            days[day_key] = d if d and (change is None or d < change) else None
        plans[line] = {"vardag": vardag, "change": change, "days": days}
    return plans


def build_lapp_context(db: sqlite3.Connection, station: sqlite3.Row,
                       plans: dict[str, dict], today: date) -> dict:
    station_id = station["stop_id"]

    # (linje, riktning) -> block; dagkolumner fylls per dagtyp
    blocks: dict[tuple[str, int], dict] = {}
    changes: dict[date, list[str]] = {}
    future_starts: dict[date, list[str]] = {}
    booking_messages: set[str] = set()

    lines = [l["line"] for l in timetable.lines_at_station(db, station_id)
             if l["is_local"] and l["line"] in plans]
    natural_weekday = today
    while natural_weekday.weekday() > 4:
        natural_weekday += timedelta(days=1)
    for line in lines:
        plan = plans[line]
        if plan["change"]:
            changes.setdefault(plan["change"], []).append(line)
        if plan["vardag"] > natural_weekday:
            future_starts.setdefault(plan["vardag"], []).append(line)
        for day_key, day_label in DAY_LABELS:
            d = plan["days"][day_key]
            rows = timetable.stop_day_departures(db, station_id, d) if d else []
            for r in rows:
                if r["line"] != line:
                    continue
                block = blocks.setdefault((line, r["direction_id"]), {
                    "line": line, "destinations": {}, "days": {}})
                block["destinations"][r["destination"]] = \
                    block["destinations"].get(r["destination"], 0) + 1
                if r["pickup"] in (2, 3) and r["booking_msg"]:
                    booking_messages.add(r["booking_msg"])
                block["days"].setdefault(day_key, []).append(
                    (r["departure_s"], r["destination"], r["pickup"]))

    out_blocks = []
    for (line, _dir), block in sorted(blocks.items()):
        dests = sorted(block["destinations"], key=block["destinations"].get, reverse=True)
        # a/f reserverade for avstigande/forbestalls-markorer
        variant_alphabet = "bcdeghijklmnopqrstuvxyz"
        letters = {d: variant_alphabet[i] for i, d in enumerate(sorted(dests))} \
            if len(dests) > 1 else {}
        # Dagar utan trafik blir en textrad i stallet for tom kolumn,
        # sa att blocket kan krympa och nasta linje lagga sig bredvid.
        day_cols, missing = [], []
        for day_key, day_label in DAY_LABELS:
            deps = [(s, letters.get(dest, "") + ("f" if pickup in (2, 3) else ""))
                    for s, dest, pickup in block["days"].get(day_key, [])]
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

    has_booking = any(
        letter.endswith("f")
        for b in out_blocks for col in b["day_cols"]
        for row in col["hours"] for _, letter in row["minutes"])
    if has_booking:
        for msg in sorted(booking_messages) or ["Turen förbeställs hos Din Tur."]:
            notes.append(f"f = {msg}")

    meta = get_meta()
    live_url = f"{config.get_base_url()}/hallplats/{station_id}"
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


def _render_one(context: dict, page_format: str) -> bytes:
    """Rendera EN hallplats som eget PDF-dokument.

    Varje lapp ar ett eget dokument sa att counter(page)/counter(pages)
    blir lappens egen numrering. Blir lappen flersidig renderas den om
    med sidfot "Hallplats - sida N av M" (margin-boxar paverkar inte
    pagineringen, sa sidantalet ar stabilt mellan passen). Ensidiga
    lappar far ingen sidfot.
    """
    kwargs = {"lapp": context, "page_size": PAGE_SIZES.get(page_format, "A5")}
    template = templates.env.get_template("print/lapp.html")
    doc = weasyprint.HTML(string=template.render(**kwargs, pagenr=False)).render()
    if len(doc.pages) == 1:
        return doc.write_pdf()
    return weasyprint.HTML(string=template.render(**kwargs, pagenr=True)).write_pdf()


# A5 stående resp. A4 liggande i PDF-punkter
_A5_W, _A5_H = 419.528, 595.276
_A4L_W, _A4L_H = 841.89, 595.276

_twoup_base_cache: bytes | None = None


def _twoup_base_page() -> bytes:
    """A4-liggande grundark med streckad skarlinje i mitten (renderas en gang)."""
    global _twoup_base_cache
    if _twoup_base_cache is None:
        html = ("<style>@page{size:A4 landscape;margin:0}"
                "div{position:absolute;left:50%;top:5mm;height:287mm;width:0;"
                "border-left:0.4mm dashed #888}</style><div></div>")
        _twoup_base_cache = weasyprint.HTML(string=html).write_pdf()
    return _twoup_base_cache


def _impose_two_up(lapp_pdfs: list[bytes]) -> bytes:
    """Tva A5-sidor per liggande A4-ark, med mittlinje att skara efter.

    Sidorna paras ihop lopande over hela batchen (en flersidig lapps
    sida 2 kan hamna bredvid nasta hallplats forsta) - sidfoten
    "sida N av M" haller ihop lapparna vid uppsattning.
    """
    pages = [p for raw in lapp_pdfs for p in pypdf.PdfReader(io.BytesIO(raw)).pages]
    base_reader = pypdf.PdfReader(io.BytesIO(_twoup_base_page()))
    writer = pypdf.PdfWriter()
    margin_x = (_A4L_W - 2 * _A5_W) / 2
    for i in range(0, len(pages), 2):
        sheet = writer.add_blank_page(width=_A4L_W, height=_A4L_H)
        sheet.merge_page(base_reader.pages[0])
        sheet.merge_transformed_page(
            pages[i], pypdf.Transformation().translate(tx=margin_x, ty=0))
        if i + 1 < len(pages):
            sheet.merge_transformed_page(
                pages[i + 1],
                pypdf.Transformation().translate(tx=margin_x + _A5_W, ty=0))
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def render_lapp_pdf(db: sqlite3.Connection, station: sqlite3.Row,
                    page_format: str = "a5") -> bytes:
    today = datetime.now(tz=config.TZ).date()
    plans = line_day_plans(db, timetable.local_lines(db), today)
    return _render_one(build_lapp_context(db, station, plans, today), page_format)


def render_batch_pdf(db: sqlite3.Connection, stations: list[sqlite3.Row],
                     page_format: str = "a5", two_up: bool = False,
                     progress=None) -> bytes:
    """En PDF med en hallplats per sida (flersidiga lappar sidnumreras).

    two_up (bara A5): tva lappar per liggande A4-ark med skarlinje.
    `progress(antal_klara)` anropas efter varje hallplats.
    """
    today = datetime.now(tz=config.TZ).date()
    plans = line_day_plans(db, timetable.local_lines(db), today)
    lapp_pdfs = []
    for i, station in enumerate(stations):
        context = build_lapp_context(db, station, plans, today)
        lapp_pdfs.append(_render_one(context, page_format))
        if progress:
            progress(i + 1)
    if two_up and page_format == "a5":
        return _impose_two_up(lapp_pdfs)
    writer = pypdf.PdfWriter()
    for raw in lapp_pdfs:
        writer.append(io.BytesIO(raw))
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()
