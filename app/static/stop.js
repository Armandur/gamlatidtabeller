"use strict";

// Uppdaterar avgangslistan varje halvminut. Sidan ar redan
// server-renderad - detta haller den farsk om den lamnas oppen,
// och blir grunden for realtidsdata i senare iteration.
(function () {
  const list = document.getElementById("avgangslista");
  const updatedAt = document.getElementById("uppdaterad-kl");

  function badgeClass(dep) {
    return dep.is_local ? "linjebricka" : "linjebricka regional";
  }

  function render(data) {
    if (!data.departures.length) {
      list.innerHTML = '<li class="tomt">Inga kommande avgångar hittades.</li>';
      return;
    }
    list.innerHTML = data.departures.map(function (d) {
      const extras =
        (d.platform ? ' <span class="lage">läge ' + escapeHtml(d.platform) + "</span>" : "") +
        (d.other_day ? ' <span class="annandag">i morgon</span>' : "");
      const om = d.in_minutes < 60 && !d.other_day ? "om " + d.in_minutes + " min" : "";
      return "<li>" +
        '<span class="tid">' + escapeHtml(d.time) + "</span>" +
        '<span class="' + badgeClass(d) + '">' + escapeHtml(d.line) + "</span>" +
        '<span class="mot">mot ' + escapeHtml(d.destination) + extras + "</span>" +
        '<span class="om">' + om + "</span>" +
        "</li>";
    }).join("");
  }

  async function refresh() {
    try {
      const data = await apiFetch("/api/hallplats/" + encodeURIComponent(window.STATION_ID) + "/avgangar");
      render(data);
      updatedAt.textContent = data.generated_at;
    } catch (err) {
      // Behall senast visade lista; ny chans vid nasta tick
      console.warn("Kunde inte uppdatera avgångar:", err);
    }
  }

  setInterval(refresh, 30000);
})();
