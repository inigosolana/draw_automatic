// Aviso EN VIVO (rojo, no bloqueante): si no hay switch y hay más equipos que
// bocas LAN del router, avisa de que hace falta un switch. No impide generar;
// es solo un recordatorio visual mientras se rellena el formulario.
(function () {
  document.addEventListener("DOMContentLoaded", function () {
    var form = document.querySelector(".creation-form");
    var banner = document.getElementById("switch-needed-warning");
    if (!form || !banner) return;

    function routerModel() {
      var el = document.getElementById("router-modelo");
      return el ? String(el.value || "") : "";
    }

    // Bocas LAN útiles: hAP ac2/ac3 = 3 (ETH3-5); CHATEAU = 4. (Igual que el backend.)
    function lanPorts() {
      return /chateau/i.test(routerModel()) ? 4 : 3;
    }

    function counts() {
      var terminals = document.querySelectorAll("#terminal-rows .terminal-row").length;
      var devices = 0;
      var hasSwitch = false;
      document.querySelectorAll("#device-rows .device-row").forEach(function (row) {
        var cat = row.querySelector('[data-field="category"]');
        if (!cat || !cat.value) return;
        if (cat.value === "switch") {
          hasSwitch = true;
          return;
        }
        var qtyEl = row.querySelector('[data-field="quantity"]');
        var qty = Math.max(1, parseInt((qtyEl && qtyEl.value) || "1", 10) || 1);
        devices += qty;
      });
      return { total: terminals + devices, hasSwitch: hasSwitch };
    }

    function update() {
      var c = counts();
      var ports = lanPorts();
      if (!c.hasSwitch && c.total > ports) {
        var rn = routerModel() || "el router";
        banner.innerHTML =
          '<span aria-hidden="true">⚠️</span> Hay <b>' + c.total +
          "</b> equipos para conectar y <b>" + rn + "</b> solo tiene <b>" + ports +
          "</b> bocas LAN (ETH3–ETH" + (ports + 2) +
          "). <b>Necesitas añadir un SWITCH</b> para conectarlos todos. " +
          "<span class=\"switch-warning-note\">(Puedes generar igualmente.)</span>";
        banner.style.display = "";
      } else {
        banner.style.display = "none";
      }
    }

    form.addEventListener("change", update);
    form.addEventListener("input", update);
    // Las filas se añaden por JS (Añadir terminal/dispositivo, importar OT,
    // plantillas) sin disparar 'change' en el contenedor: recomprobamos periódicamente.
    setInterval(update, 1200);
    update();
  });
})();
