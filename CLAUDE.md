# Gamla tidtabeller - kodbasbeskrivning för Claude

Webbapp som visar busstider för Härnösand (Din Tur) och genererar
utskrivbara stolptidtabeller. Mobil-först, WCAG 2.1 AA som ambition,
målgruppen inkluderar äldre och synskadade.

## Stack

Python 3.12 + FastAPI + uvicorn, Jinja2, vanilla JS utan bundler,
rå `sqlite3` (medvetet vald avvikelse: databasen är en engångsgenererad
artefakt som byggs om från GTFS-zippen varje natt - inga migrationer,
ingen SQLAlchemy). Beroenden hanteras med `uv` (`uv sync`, `uv run`).

## Dataflöde

1. `app/services/trafiklab.py` laddar ner GTFS-zippen till
   `data/dintur-gtfs.zip`. **Static-nyckeln har bara 60 anrop/30 dagar** -
   nedladdning sker ALDRIG om cachen är färskare än
   `STATIC_MAX_AGE_HOURS` (20 h). Rör inte den spärren.
2. `app/gtfs_import.py` bygger `data/gtfs.sqlite` från zippen
   (temp-fil + atomiskt byte). Körbar som `python -m app.gtfs_import`.
3. `app/main.py` har lifespan som bygger db vid start om den saknas och
   kör nattlig refresh 04:30 (Europe/Stockholm).
4. `app/services/realtime.py` pollar GTFS-RT (TripUpdates +
   ServiceAlerts) var 20:e sekund med RT-nyckeln (hög kvot, ofarligt).
   Allt hålls i minnet i modulsingletonen `state`; referenserna byts
   atomiskt så läsare behöver inga lås. Data äldre än 90 s räknas som
   otillgänglig -> UI faller tillbaka på tidtabellstid.
   `enrich_departures()` lägger realtidsfält på avgångar (matchar
   stop_time_update exakt på stop_id/seq, annars senaste före stoppet -
   förseningar propagerar framåt enligt GTFS-RT-semantiken).
   ServiceAlerts dedupliceras per rubrik (Din Tur publicerar lång+kort
   variant av samma störning).

## Scope-filtret

`config.LOCAL_LINES` = 501, 502, 503, 511, 590 (Härnösands stads- och
lokallinjer). Importen tar med alla hållplatser dessa linjer trafikerar,
och ALLA avgångar vid de hållplatserna - även regionala linjer (201, 90
osv). Hållplatsvyn visar allt; linjevy och utskrifter håller sig till
LOCAL_LINES.

## Kvirkar i Din Tur-feeden (bekräftade 2026-07-03)

- API:erna kräver `Accept-Encoding: gzip`, annars HTTP 406.
- `calendar.txt` har nollade veckodagsmasker - trafikdagarna kommer
  enbart från `calendar_dates.txt`. Importen materialiserar allt till
  tabellen `service_dates` (service_id, datum).
- `trip_headsign` är tomt i hela feeden - `trips.destination` härleds
  från turens sista hållplats vid import.
- GTFS-tider kan vara >24:00 (turer efter midnatt); lagras som sekunder
  i `stop_times.departure_s`.
- Sommartrafik ligger som egna service_id (2026: 2 juli-14 aug, inga
  stadsbussar lör/sön, ingen 590 före 17 aug).

## Utskrift (app/printing.py)

Stolptidtabeller renderas server-side med WeasyPrint fran
`templates/print/lapp.html` (fristaende, inline-CSS, @page-storlek
A4/A5). Minuttabell per (linje, riktning) med kolumner man-fre/lor/son;
dagtypsdatum valjs inom samma tidtabellsperiod som vardagsdatumet
(via `next_table_change`), annars visas "Ingen trafik" + gul not.
QR-kod (segno, SVG-data-URI) pekar pa `BASE_URL/hallplats/{id}`.
Endpoint `/hallplats/{id}/lapp.pdf?format=a5|a4` har enkel in-memory
rate limit per IP (WeasyPrint ar dyr).

## Databas (data/gtfs.sqlite, byggs om nattligen)

- `meta` - feed_version, downloaded_at, imported_at, radantal
- `routes` - is_local markerar LOCAL_LINES
- `stops` - både stationer (location_type=1) och lägen/plattformar;
  användarvänd hållplats = station, avgångar hämtas via parent_station
- `trips` - destination = härledd slutstation, direction_id
- `stop_times` - departure_s (sekunder), is_last (visa ej som avgång)
- `service_dates` - materialiserade trafikdagar per service_id

Läsning via `app/database.py:open_db()` - ny anslutning per användning
(read-only URI) eftersom filen byts atomiskt av nattjobbet.

## Filstruktur

```
app/
  main.py          # app, lifespan (startbygge + nattlig refresh), /api/status
  config.py        # env, LOCAL_LINES, kvot-/schemakonstanter
  database.py      # open_db(), get_meta(), DatabaseMissing
  gtfs_import.py   # zip -> sqlite, körbar som modul
  services/
    trafiklab.py   # nedladdning med cache-spärr
  routes/          # (kommande) hållplatsvy, linjevy, utskrift
  templates/       # (kommande)
  static/          # (kommande)
data/              # gitignored: zip-cache + sqlite
```

## Kommande (se ROADMAP.md)

Hållplatsvy -> linjevy -> realtid (egen GTFS-RT-poller, protobuf,
in-memory) -> utskriftsstudio (WeasyPrint, segno-QR, batch-PDF A4/A5).

## Test/verifiering

```bash
uv run python -m app.gtfs_import        # bygger om db från cache
uv run python -c "from app.main import app; print('OK')"
```

Testdatum som är bra att känna till: 2026-07-06 (sommarvardag, 247
avgångar Härnösand C), 2026-07-11 (sommarlördag, 4 avgångar - inga
stadsbussar), station-id Härnösand Central = 9021022000898000.
