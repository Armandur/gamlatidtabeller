"use strict";

// Uppdaterar avgangslistan och storningar varje halvminut med
// realtidsdata fran API:t. Sidan ar redan server-renderad; detta
// haller den farsk om den lamnas oppen vid hallplatsen.
(function () {
  const list = document.getElementById("avgangslista");
  const alertBox = document.getElementById("storningar");
  const rtStatus = document.getElementById("rt-status");
  const updatedAt = document.getElementById("uppdaterad-kl");
  let latestVehicles = [];

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
    const msgs = Array.from(new Set(
      data.departures.map((d) => d.booking_msg).filter(Boolean))).sort();
    document.getElementById("bokningsinfo").innerHTML = msgs.map(function (m) {
      return '<p class="bokningsrad"><span class="lage">förbeställs</span> ' +
        escapeHtml(m) + "</p>";
    }).join("");
    alertBox.innerHTML = data.alerts.map(function (a) {
      return '<div class="storning"><strong>' + escapeHtml(a.header) + "</strong>" +
        (a.description ? "<br>" + escapeHtml(a.description) : "") + "</div>";
    }).join("");
    rtStatus.innerHTML = data.realtime_ok
      ? 'Tider med grön punkt (<span class="rt-prick" aria-hidden="true"></span>) uppdateras i realtid.'
      : "Visar tidtabellstid - realtid saknas just nu.";
    updatedAt.textContent = data.generated_at;
    latestVehicles = data.vehicles || [];
    renderVehicles();
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

  // "Var ar bussen?" - Leaflet och kartan laddas forst nar anvandaren
  // ber om den (150 kB extra ar inte gratis pa dalig uppkoppling).
  const mapBtn = document.getElementById("visa-karta");
  const mapDiv = document.getElementById("fordonskarta");
  const mapStatus = document.getElementById("karta-status");
  let map = null;
  let vehicleLayer = null;

  function loadLeaflet(done) {
    if (window.L) { done(); return; }
    const css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = "/static/vendor/leaflet/leaflet.css";
    document.head.appendChild(css);
    const js = document.createElement("script");
    js.src = "/static/vendor/leaflet/leaflet.js";
    js.onload = done;
    js.onerror = function () { mapStatus.textContent = "Kartan kunde inte laddas."; };
    document.head.appendChild(js);
  }

  function renderVehicles() {
    if (!map) return;
    vehicleLayer.clearLayers();
    const points = [window.STATION_POS];
    for (const v of latestVehicles) {
      points.push([v.lat, v.lon]);
      L.marker([v.lat, v.lon], {
        icon: L.divIcon({
          className: "fordonsikon",
          html: '<span class="linjebricka">' + escapeHtml(v.line) + "</span>",
          iconSize: null,
        }),
      }).bindTooltip(escapeHtml(v.line) + " mot " + escapeHtml(v.destination) +
                     (v.age_s !== null ? " · " + v.age_s + " s sedan" : ""))
        .addTo(vehicleLayer);
    }
    mapStatus.textContent = latestVehicles.length
      ? latestVehicles.length + (latestVehicles.length === 1 ? " buss" : " bussar") +
        " med känd position visas på kartan."
      : "Ingen buss på väg hit har känd position just nu.";
    if (points.length > 1) {
      map.fitBounds(L.latLngBounds(points).pad(0.2), { maxZoom: 15 });
    }
  }

  mapBtn.addEventListener("click", function () {
    mapBtn.disabled = true;
    mapStatus.textContent = "Laddar kartan ...";
    loadLeaflet(function () {
      mapDiv.hidden = false;
      map = L.map("fordonskarta").setView(window.STATION_POS, 14);
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      }).addTo(map);
      L.circleMarker(window.STATION_POS, {
        radius: 9, color: "#00427a", fillColor: "#00427a", fillOpacity: 0.9,
      }).bindTooltip("Hållplatsen").addTo(map);
      vehicleLayer = L.layerGroup().addTo(map);
      mapBtn.hidden = true;
      renderVehicles();
      refresh();
    });
  });

  setInterval(refresh, 30000);
})();
