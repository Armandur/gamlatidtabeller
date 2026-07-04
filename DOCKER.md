# Deployment - Docker på Unraid

Appen körs som en monolitisk single-container. Imagen byggs automatiskt
av GitHub Actions och publiceras till
`ghcr.io/armandur/gamlatidtabeller` med taggarna `latest`, SHA,
branchnamn och semver (vid `v*`-taggar).

Containern kör både publika appen (port 8000) och admingränssnittet
(port 8001) i samma process. **Exponera bara den publika porten utåt** -
adminporten ska bara nås från LAN.

## Unraid: Add Container

| Fält | Värde |
|---|---|
| Repository | `ghcr.io/armandur/gamlatidtabeller:latest` |

### Portar (Add another Path/Port/Variable -> Port)

| Container-port | Host-port (förslag) | Anmärkning |
|---|---|---|
| 8000 | 8780 | Publika appen - kan proxas ut via nginx/HTTPS |
| 8001 | 8781 | Admin - exponera INTE via reverse proxy |

### Sökvägar (Path)

| Container-sökväg | Host-sökväg (förslag) | Läge |
|---|---|---|
| `/data` | `/mnt/user/appdata/gamlatidtabeller` | rw |

`/data` innehåller GTFS-zipcachen, SQLite-databasen och
`settings.json` (admininställningar). Allt återskapas automatiskt
utom settings.json, men en förseedad `dintur-gtfs.zip` sparar ett
kvotanrop vid första starten.

### Variabler (Variable)

| Variabel | Värde | Anmärkning |
|---|---|---|
| `TRAFIKLAB_STATIC_KEY` | (nyckel) | GTFS Regional Static - Bronze, 60 anrop/30 d |
| `TRAFIKLAB_RT_KEY` | (nyckel) | GTFS Regional Realtime - hög kvot |
| `BASE_URL` | `https://...` | Publika adressen; hamnar i QR-koderna på lapparna |
| `ADMIN_PASSWORD` | (starkt lösenord) | Skyddar admingränssnittet |
| `SESSION_SECRET` | (slumpad hex) | `openssl rand -hex 32`; annars nollställs adminsessioner vid omstart |

## Efter första start

1. Vid start utan databas hämtas GTFS-zippen (1 kvotanrop) och
   databasen byggs - kontrollera `http://HOST:8781` (admin) att
   feedversion och hållplatsantal ser rätt ut.
2. Nattlig uppdatering körs 04:30 svensk tid och hämtar alltid färsk
   zip (~31 anrop/månad av kvotens 60).

## HTTPS

"Hitta närmaste hållplats" (geolocation) kräver att sidan serveras
över HTTPS. Kör den publika porten bakom en reverse proxy med TLS
(t.ex. befintlig nginx-container på TERVO2) och sätt `BASE_URL` till
https-adressen. Adminporten ska inte läggas bakom proxyn.

## Lokal dev-körning av imagen

```bash
docker build -t gamlatidtabeller:dev .
docker run -d --name gt-dev --env-file .env -e DATA_DIR=/data \
  -p 8000:8000 -p 8001:8001 \
  -v "$PWD/data:/data" gamlatidtabeller:dev
```
