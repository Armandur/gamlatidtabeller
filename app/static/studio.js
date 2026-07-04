"use strict";

// Utskriftsstudio: valj hallplatser via lista och Leaflet-karta,
// skicka valen som formular-POST till /studio/pdf.
(function () {
  const selected = new Set();
  const listEl = document.getElementById("studio-stationer");
  const statusEl = document.getElementById("val-status");
  const idsInput = document.getElementById("ids-input");
  const submitBtn = document.getElementById("skapa-pdf");
  const searchEl = document.getElementById("studio-sok");

  const map = L.map("karta");
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);

  const markers = {};
  const bounds = L.latLngBounds();
  for (const s of window.STATIONS) {
    const m = L.circleMarker([s.lat, s.lon], markerStyle(false))
      .addTo(map)
      .bindTooltip(s.name)
      .on("click", () => toggle(s.id));
    markers[s.id] = m;
    bounds.extend([s.lat, s.lon]);
  }
  map.fitBounds(bounds, { padding: [20, 20] });

  function markerStyle(isSelected) {
    return {
      radius: isSelected ? 9 : 6,
      color: isSelected ? "#b3005e" : "#00427a",
      fillColor: isSelected ? "#b3005e" : "#4a90d9",
      fillOpacity: 0.85,
      weight: 2,
    };
  }

  function toggle(id) {
    if (selected.has(id)) selected.delete(id); else selected.add(id);
    sync();
  }

  function setAll(ids, on) {
    for (const id of ids) { if (on) selected.add(id); else selected.delete(id); }
    sync();
  }

  function sync() {
    for (const s of window.STATIONS) {
      markers[s.id].setStyle(markerStyle(selected.has(s.id)));
      const box = document.getElementById("kryss-" + s.id);
      if (box) box.checked = selected.has(s.id);
    }
    statusEl.innerHTML = "<strong>" + selected.size + "</strong> " +
      (selected.size === 1 ? "hållplats vald" : "hållplatser valda");
    idsInput.value = Array.from(selected).join(",");
    submitBtn.disabled = selected.size === 0;
  }

  function renderList() {
    const q = searchEl.value.trim().toLowerCase();
    listEl.innerHTML = "";
    for (const s of window.STATIONS) {
      if (q && !s.name.toLowerCase().includes(q)) continue;
      const li = document.createElement("li");
      const label = document.createElement("label");
      const box = document.createElement("input");
      box.type = "checkbox";
      box.id = "kryss-" + s.id;
      box.checked = selected.has(s.id);
      box.addEventListener("change", () => toggle(s.id));
      label.append(box, " " + s.name);
      li.appendChild(label);
      li.addEventListener("mouseenter", () => markers[s.id].openTooltip());
      li.addEventListener("mouseleave", () => markers[s.id].closeTooltip());
      listEl.appendChild(li);
    }
  }

  searchEl.addEventListener("input", renderList);

  document.getElementById("valj-alla").addEventListener("click", () =>
    setAll(window.STATIONS.map((s) => s.id), true));
  document.getElementById("valj-inga").addEventListener("click", () =>
    setAll(window.STATIONS.map((s) => s.id), false));
  document.getElementById("valj-synliga").addEventListener("click", () => {
    const b = map.getBounds();
    setAll(window.STATIONS.filter((s) => b.contains([s.lat, s.lon])).map((s) => s.id), true);
  });

  // Shift+dra: rita rektangel och valj alla hallplatser i den
  let boxStart = null, boxRect = null;
  map.on("mousedown", (e) => {
    if (!e.originalEvent.shiftKey) return;
    map.dragging.disable();
    boxStart = e.latlng;
  });
  map.on("mousemove", (e) => {
    if (!boxStart) return;
    const b = L.latLngBounds(boxStart, e.latlng);
    if (boxRect) boxRect.setBounds(b);
    else boxRect = L.rectangle(b, { color: "#b3005e", weight: 1, fillOpacity: 0.1 }).addTo(map);
  });
  map.on("mouseup", (e) => {
    if (!boxStart) return;
    const b = L.latLngBounds(boxStart, e.latlng);
    setAll(window.STATIONS.filter((s) => b.contains([s.lat, s.lon])).map((s) => s.id), true);
    if (boxRect) map.removeLayer(boxRect);
    boxStart = null; boxRect = null;
    map.dragging.enable();
  });

  // PDF-generering tar ca 1 s per hallplats och kors som bakgrundsjobb:
  // starta, polla progress, oppna fardig PDF i ny flik.
  const form = document.getElementById("pdf-form");
  const jobStatus = document.getElementById("jobb-status");
  const jobLink = document.getElementById("jobb-lank");

  async function pollJob(jobId) {
    const pdfUrl = "/studio/jobb/" + jobId + "/pdf";
    for (;;) {
      await new Promise((r) => setTimeout(r, 1500));
      const s = await apiFetch("/studio/jobb/" + jobId);
      if (s.status === "arbetar") {
        jobStatus.textContent = "Skapar PDF: " + s.progress + " av " + s.total + " hållplatser ...";
      } else if (s.status === "klar") {
        jobStatus.textContent = "Klar!";
        jobLink.href = pdfUrl;
        jobLink.hidden = false;
        window.open(pdfUrl, "_blank");  // blockeras popupen finns lanken kvar
        return;
      } else {
        jobStatus.textContent = "Något gick fel vid PDF-genereringen - försök igen.";
        return;
      }
    }
  }

  form.addEventListener("submit", async function (e) {
    e.preventDefault();
    submitBtn.disabled = true;
    jobLink.hidden = true;
    jobStatus.textContent = "Startar utskriftsjobb ...";
    try {
      const resp = await fetch("/studio/pdf", {
        method: "POST",
        body: new URLSearchParams(new FormData(form)),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "HTTP " + resp.status);
      await pollJob(data.job_id);
    } catch (err) {
      jobStatus.textContent = err.message || "Något gick fel - försök igen.";
    } finally {
      submitBtn.disabled = selected.size === 0;
    }
  });

  renderList();
  sync();
})();
