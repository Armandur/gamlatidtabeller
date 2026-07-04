"use strict";

// Klientfiltrering av den server-renderade hallplatslistan -
// hela listan finns i DOM sa sidan fungerar aven utan JS.
(function () {
  const input = document.getElementById("sok");
  const status = document.getElementById("sokstatus");
  const items = Array.from(document.querySelectorAll("#stationslista li"));

  // "Hitta narmaste hallplats" - visas bara om geolocation finns.
  // Platsen begars forst nar anvandaren trycker pa knappen och
  // anvands enbart i webblasaren for avstandsberakning.
  const naraBox = document.getElementById("narmaste");
  const naraBtn = document.getElementById("nara-mig");
  const naraResult = document.getElementById("nara-resultat");
  // Geolocation kraver saker kontext (HTTPS) - visa inte en dod knapp annars
  if (navigator.geolocation && window.isSecureContext) naraBox.hidden = false;

  function distanceM(lat1, lon1, lat2, lon2) {
    const rad = Math.PI / 180;
    const dLat = (lat2 - lat1) * rad;
    const dLon = (lon2 - lon1) * rad;
    const a = Math.sin(dLat / 2) ** 2 +
      Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) ** 2;
    return 6371000 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  }

  function fmtDistance(m) {
    return m < 1000 ? "ca " + Math.max(50, Math.round(m / 50) * 50) + " m"
                    : "ca " + (m / 1000).toFixed(1).replace(".", ",") + " km";
  }

  naraBtn.addEventListener("click", function () {
    naraBtn.disabled = true;
    naraResult.textContent = "Hämtar din plats ...";
    navigator.geolocation.getCurrentPosition(function (pos) {
      const nearest = items
        .map(function (li) {
          return { li: li, dist: distanceM(pos.coords.latitude, pos.coords.longitude,
                                           parseFloat(li.dataset.lat), parseFloat(li.dataset.lon)) };
        })
        .sort(function (a, b) { return a.dist - b.dist; })
        .slice(0, 3);
      naraResult.innerHTML = "<p>Närmast dig:</p><ul>" + nearest.map(function (n) {
        const a = n.li.querySelector("a");
        return '<li><a href="' + a.getAttribute("href") + '">' + a.innerHTML + "</a> " +
          '<span class="avstand">' + fmtDistance(n.dist) + "</span></li>";
      }).join("") + "</ul>";
      naraBtn.disabled = false;
    }, function (err) {
      naraResult.textContent = err.code === err.PERMISSION_DENIED
        ? "Du delade inte din plats - välj hållplats i listan i stället."
        : "Kunde inte hämta din plats - välj hållplats i listan i stället.";
      naraBtn.disabled = false;
    }, { timeout: 10000, maximumAge: 60000 });
  });

  input.addEventListener("input", function () {
    const q = input.value.trim().toLowerCase();
    let visible = 0;
    for (const li of items) {
      const match = !q || li.textContent.toLowerCase().includes(q);
      li.hidden = !match;
      if (match) visible++;
    }
    status.textContent = !q ? ""
      : visible === 0 ? "Ingen hållplats matchar din sökning."
      : visible + (visible === 1 ? " hållplats matchar." : " hållplatser matchar.");
  });
})();
