"use strict";

// Admin-diagnostik: alla fordon i lanet pa karta, uppdateras lopande.
(function () {
  const statusEl = document.getElementById("karta-status");
  const map = L.map("lanskarta").setView([62.8, 17.6], 8);
  const osm = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);
  const satellit = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: 19,
      attribution: "Bilder &copy; Esri, Maxar, Earthstar Geographics",
    });
  L.control.layers({ "Karta": osm, "Satellit": satellit }).addTo(map);
  const layer = L.layerGroup().addTo(map);
  let fitted = false;

  function esc(t) {
    const d = document.createElement("div");
    d.textContent = t;
    return d.innerHTML;
  }

  async function refresh() {
    let data;
    try {
      const resp = await fetch("/api/fordon");
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      data = await resp.json();
    } catch (err) {
      statusEl.textContent = "Kunde inte hämta fordon: " + err.message;
      return;
    }
    layer.clearLayers();
    const points = [];
    for (const v of data.vehicles) {
      points.push([v.lat, v.lon]);
      const badge = v.local ? "linjebricka" : "linjebricka regional";
      L.marker([v.lat, v.lon], {
        icon: L.divIcon({
          className: "fordonsikon",
          html: '<span class="' + badge + '">' + esc(v.line) + "</span>",
          iconSize: null,
        }),
      }).bindTooltip(esc(v.line) + (v.destination ? " mot " + esc(v.destination) : "") +
                     " · tur " + esc(v.trip_id) +
                     (v.age_s !== null ? " · " + v.age_s + " s sedan" : ""))
        .addTo(layer);
    }
    statusEl.textContent = data.vehicles.length + " fordon i feeden" +
      (data.fresh ? "" : " (EJ FÄRSK DATA)") +
      " · uppdaterad " + data.generated_at +
      " · " + data.requests_today + " API-anrop i dag";
    if (!fitted && points.length) {
      map.fitBounds(L.latLngBounds(points).pad(0.1));
      fitted = true;
    }
  }

  refresh();
  setInterval(refresh, 20000);
})();
