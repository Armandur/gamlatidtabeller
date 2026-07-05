"use strict";

// Uppdaterar avgangslistan och storningar varje halvminut med
// realtidsdata fran API:t. Sidan ar redan server-renderad; detta
// haller den farsk om den lamnas oppen vid hallplatsen.
(function () {
  const list = document.getElementById("avgangslista");
  const alertBox = document.getElementById("storningar");
  const rtStatus = document.getElementById("rt-status");
  const updatedAt = document.getElementById("uppdaterad-kl");

  function renderDeparture(d) {
    const badge = d.is_local ? "linjebricka" : "linjebricka regional";
    const prick = d.realtime ? '<span class="rt-prick" role="img" aria-label="realtid"></span>' : "";
    const gammal = d.delay_min ? ' <s class="gammal-tid">' + escapeHtml(d.scheduled_time) + "</s>" : "";
    const extras =
      (d.platform ? ' <span class="lage">läge ' + escapeHtml(d.platform) + "</span>" : "") +
      (d.day_label ? ' <span class="annandag">' + escapeHtml(d.day_label) + "</span>" : "") +
      (d.booking ? ' <span class="lage">förbeställs</span>' : "") +
      (d.canceled ? ' <span class="installd-badge">Inställd</span>' : "");
    const om = !d.canceled && d.in_minutes < 60 && !d.day_label ? "om " + d.in_minutes + " min" : "";
    return "<li" + (d.canceled ? ' class="installd"' : "") + ">" +
      '<span class="tid">' + prick + escapeHtml(d.display_time) + gammal + "</span>" +
      '<span class="' + badge + '">' + escapeHtml(d.line) + "</span>" +
      '<span class="mot">mot ' + escapeHtml(d.destination) + extras + "</span>" +
      '<span class="om">' + om + "</span>" +
      "</li>";
  }

  function render(data) {
    list.innerHTML = data.departures.length
      ? data.departures.map(renderDeparture).join("")
      : '<li class="tomt">Inga kommande avgångar hittades.</li>';
    alertBox.innerHTML = data.alerts.map(function (a) {
      return '<div class="storning"><strong>' + escapeHtml(a.header) + "</strong>" +
        (a.description ? "<br>" + escapeHtml(a.description) : "") + "</div>";
    }).join("");
    rtStatus.innerHTML = data.realtime_ok
      ? 'Tider med grön punkt (<span class="rt-prick" aria-hidden="true"></span>) uppdateras i realtid.'
      : "Visar tidtabellstid - realtid saknas just nu.";
    updatedAt.textContent = data.generated_at;
  }

  async function refresh() {
    try {
      const data = await apiFetch("/api/hallplats/" + encodeURIComponent(window.STATION_ID) + "/avgangar");
      render(data);
    } catch (err) {
      // Behall senast visade lista; ny chans vid nasta tick
      console.warn("Kunde inte uppdatera avgångar:", err);
    }
  }

  setInterval(refresh, 30000);
})();
