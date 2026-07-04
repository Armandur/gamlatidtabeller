# Roadmap

## Klart

- [x] Iteration 1: projektskelett, GTFS-nedladdning med kvotsäker cache,
      import till SQLite (scope: LOCAL_LINES + alla avgångar vid deras
      hållplatser), nattlig refresh, /api/status

- [x] Iteration 2: mobil hållplatsvy - fritextsök (klientfiltrerad
      server-renderad lista), hållplatssida med linjer + kommande
      avgångar över dygnsgräns, 30s-polling som grund för realtid

- [x] Iteration 3: linjevy per riktning och dagtyp (vardag/lördag/söndag),
      tabellmatris med grenvariantmarkering, upptäcker tabellbyten
      (t.ex. sommar->höst) och linjer utan trafik i perioden

- [x] Iteration 4: realtid - GTFS-RT-poller var 20:e sekund (TripUpdates
      + ServiceAlerts i minnet), förseningar/inställda turer i
      avgångslistan, störningsbanner på hållplats- och linjesidor,
      automatisk fallback till tidtabellstid när feeden är nere/gammal

- [x] Iteration 5: utskrift mobil - stolptidtabell som PDF per hållplats
      (WeasyPrint, A4/A5, QR-kod till live-vyn, minuttabell per
      linje/riktning och dagtyp, periodnoter, rate limit)

## Kvar

- [ ] Iteration 6: utskriftsstudio skrivbord - karta + lista, multival,
      batch-PDF A4/A5, skärmärken
- [ ] Iteration 7: Docker + GitHub Actions + Unraid-deployinstruktioner
- [ ] Senare/kanske: VehiclePositions på karta, "nära mig" via geolocation
