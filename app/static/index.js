"use strict";

// Klientfiltrering av den server-renderade hallplatslistan -
// hela listan finns i DOM sa sidan fungerar aven utan JS.
(function () {
  const input = document.getElementById("sok");
  const status = document.getElementById("sokstatus");
  const items = Array.from(document.querySelectorAll("#stationslista li"));

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
