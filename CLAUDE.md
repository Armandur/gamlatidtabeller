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

Stolptidtabeller renderas server-side med WeasyPrint. Templates:
`print/_lapp_css.html` + `print/_lapp_body.html` (delas, body laser
lappdata ur variabeln `L`) och `print/lapp.html` (`crop` ger A5
centrerad pa A4 med streckad skarlinje). VARJE hallplats renderas som
eget PDF-dokument - da blir counter(page)/counter(pages) lappens egen
numrering ("Hallplats - sida N av M" laggs bara pa flersidiga lappar,
via omrendering; margin-boxar paverkar inte pagineringen sa sidantalet
ar stabilt). Batch sammanfogas med pypdf. Minuttabell per (linje,
riktning) med dagkolumner; dagar utan trafik blir textrad och blocken
radpackas (max tre dagkolumner per rad - WeasyPrint kan inte sidbryta
inuti en inline-container, darfor packas raderna server-side).
Dagtypsdatum valjs inom samma tidtabellsperiod som vardagsdatumet;
`line_day_plans()` beraknar detta EN gang per batch (dyrt annars -
next_table_change scannar veckovis). QR-kod (segno) pekar pa
`BASE_URL/hallplats/{id}`. Skarlinje-laget ar 2-upp-imposition i
pypdf: tva A5-sidor per liggande A4-ark med streckad mittlinje
(grundarket renderas en gang och cachas i `_twoup_base_cache`).
Enlapps-endpointen har in-memory rate limit per IP (~1 s/PDF).

## Utskriftsstudio (/studio)

Skrivbordsvy: vendorerad Leaflet (app/static/vendor/leaflet/) +
OSM-tiles, cirkelmarkorer (inga ikonbilder behovs), lista med
kryssrutor, Shift+dra ritar rektangel for omradesval, "valj synliga
pa kartan"/alla/rensa. Batchar kors som bakgrundsjobb (~1 s per
hallplats): POST /studio/pdf startar och returnerar jobb-id (max ett
pagaende jobb per IP, max 2 globalt, TTL 15 min i minnet), klienten
pollar /studio/jobb/{id} for progress och oppnar
/studio/jobb/{id}/pdf i ny flik nar jobbet ar klart. Obscura
kraschar pa Leaflet - browser-verifiera studion med shot/Playwright.

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

## Admin (egen app, egen port)

`app/admin.py` ar en SEPARAT FastAPI-app som kors i samma process som
publika appen via `python -m app.run` (PORT + ADMIN_PORT) - samma
process kravs for att dashboarden ska se realtidsstatus och
utskriftsjobb i minnet. Admin-porten exponeras inte publikt;
ADMIN_PASSWORD ger inloggning ovanpa (Starlette SessionMiddleware,
CSRF-token i session pa alla POST). OBS: `secrets.compare_digest`
kraver bytes for icke-ASCII - jamfor alltid `.encode()`.

Installningar som kan andras i admin (lokala linjer, bas-URL for QR)
lagras i `data/settings.json` via `app/settings_store.py` - de kan
inte bo i databasen som byggs om varje natt. Env ar default,
settings.json innehaller bara avvikelser; `config.get_local_lines()`
/`get_base_url()` ar uppslagen. Linjeandring bygger om databasen
fran cachad zip automatiskt.

## Filstruktur

```
app/
  main.py          # publik app, lifespan (startbygge, nattlig refresh, RT-poller)
  run.py           # kor publik + admin i samma process pa tva portar
  admin.py         # admin-app (egen port): status, atgarder, installningar
  config.py        # env, LOCAL_LINES-default, get_local_lines()/get_base_url()
  settings_store.py# data/settings.json - admininstallningar som overlever ombygge
  database.py      # open_db(), get_meta(), DatabaseMissing
  gtfs_import.py   # zip -> sqlite, korbar som modul
  timetable.py     # uppslag: sok, avgangar, linjetabeller, servicedagar
  printing.py      # stolptidtabells-PDF (WeasyPrint, QR, 2-upp)
  deps.py          # templates-instans
  services/
    trafiklab.py   # nedladdning med cache-sparr
    realtime.py    # GTFS-RT-poller + matchning
  routes/
    pages.py       # startsida, hallplatsvy, linjevy, lapp-PDF
    api.py         # status + avgangs-JSON (pollas av stop.js)
    studio.py      # utskriftsstudio + batchjobb
  templates/       # Jinja2 (print/ for PDF, admin/ for adminappen)
  static/          # vanilla JS/CSS + vendorerad Leaflet
data/              # gitignored: zip-cache + sqlite + settings.json
```

## Kommande (se ROADMAP.md)

Hållplatsvy -> linjevy -> realtid (egen GTFS-RT-poller, protobuf,
in-memory) -> utskriftsstudio (WeasyPrint, segno-QR, batch-PDF A4/A5).

## Deployment

Dockerfile: python 3.12-slim + uv (`uv sync --frozen`), apt-paket för
WeasyPrint (libpango/libharfbuzz) och fonts-dejavu-core, non-root
`appuser` MED hemkatalog (annars klagar fontconfig pa cache), volym
`/data`, CMD `python -m app.run` (bada portarna). CI:
`.github/workflows/docker.yml` bygger till ghcr med latest/sha/branch/
semver. Driftinstruktioner för Unraid Add Container: se DOCKER.md.

## Test/verifiering

```bash
uv run python -m app.gtfs_import        # bygger om db från cache
uv run python -c "from app.main import app; print('OK')"
```

Testdatum som är bra att känna till: 2026-07-06 (sommarvardag, 247
avgångar Härnösand C), 2026-07-11 (sommarlördag, 4 avgångar - inga
stadsbussar), station-id Härnösand Central = 9021022000898000.
