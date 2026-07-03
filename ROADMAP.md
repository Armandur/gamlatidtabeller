# Roadmap

## Klart

- [x] Iteration 1: projektskelett, GTFS-nedladdning med kvotsäker cache,
      import till SQLite (scope: LOCAL_LINES + alla avgångar vid deras
      hållplatser), nattlig refresh, /api/status

- [x] Iteration 2: mobil hållplatsvy - fritextsök (klientfiltrerad
      server-renderad lista), hållplatssida med linjer + kommande
      avgångar över dygnsgräns, 30s-polling som grund för realtid

## Kvar

- [ ] Iteration 3: linjevy per riktning och servicedag, sommarmarkering
- [ ] Iteration 4: realtid - GTFS-RT-poller (TripUpdates, ServiceAlerts),
      realtidsbadges, störningsbanner, snygg fallback till statisk tid
- [ ] Iteration 5: utskrift mobil - PDF för en hållplats (WeasyPrint, QR)
- [ ] Iteration 6: utskriftsstudio skrivbord - karta + lista, multival,
      batch-PDF A4/A5, skärmärken
- [ ] Iteration 7: Docker + GitHub Actions + Unraid-deployinstruktioner
- [ ] Senare/kanske: VehiclePositions på karta, "nära mig" via geolocation
