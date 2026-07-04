# Gamla tidtabeller

Hållplatsvän för Härnösand. Din Tur har tagit bort de fysiska tidtabellerna
från busskurerna - den här webappen gör det enkelt att se vilka linjer som
trafikerar en hållplats och när nästa buss går, och att skriva ut
stolptidtabeller att sätta upp i kurerna igen.

Medborgarframställd tjänst byggd på öppna data från Trafiklab (CC0).
Ej officiell information från Din Tur.

## Datakällor

- **GTFS Regional Static** (Samtrafiken via Trafiklab): komplett tidtabell
  för Din Tur. OBS Bronze-nyckelns kvot är 60 anrop/30 dagar - appen cachar
  zippen i `data/` och laddar bara ner om cachen är äldre än 20 timmar.
  Nattligt jobb kl 04:30 hämtar ny data och bygger om databasen.
- **GTFS Regional Realtime** (separat nyckel, hög kvot): TripUpdates och
  ServiceAlerts för realtid och störningar. (Kommer i senare iteration.)

API:erna kräver headern `Accept-Encoding: gzip`, annars svarar de HTTP 406.

## Köra lokalt

```bash
cp .env.example .env   # fyll i Trafiklab-nycklar
uv sync
uv run python -m app.gtfs_import   # bygg databasen (laddar ner zip vid behov)
uv run python -m app.run   # publik app pa PORT, admin pa ADMIN_PORT
```

`python -m app.gtfs_import --force-download` tvingar ny nedladdning
(kvotbelagt - använd sparsamt).

## Miljövariabler

| Variabel | Beskrivning |
|---|---|
| `TRAFIKLAB_STATIC_KEY` | Nyckel för GTFS Regional Static |
| `TRAFIKLAB_RT_KEY` | Nyckel för GTFS Regional Realtime |
| `BASE_URL` | Publik bas-URL, används i QR-koder på utskrifter |
| `DATA_DIR` | Katalog för zip-cache och SQLite (default `data`) |

## Deployment

Kommer när appen är körbar på riktigt: single-container Docker på Unraid
(Add Container), image via GitHub Actions till ghcr. Se `DOCKER.md` (senare).

## Admin

Ett separat admingränssnitt körs på `ADMIN_PORT` (exponera den inte
publikt): datastatus, manuell GTFS-uppdatering ("bygg om från cache"
utan kvotanrop respektive "hämta ny" med), samt inställningar för
lokala linjer och bas-URL som sparas i `data/settings.json` och
överlever databasombyggen. Skyddas med `ADMIN_PASSWORD`.
