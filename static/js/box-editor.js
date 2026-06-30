// Editor rápido de cajas y líneas para la vista previa de "Crear diagrama".
// Cajas arrastrables, conexión por líneas, borrado y zoom. Autónomo: si no
// existe #be-canvas no hace nada.
(function () {
  "use strict";
  document.addEventListener("DOMContentLoaded", function () {
    var canvas = document.getElementById("be-canvas");
    var stage = document.getElementById("be-stage");
    var wires = document.getElementById("be-wires");
    if (!canvas || !stage || !wires) return;

    var boxes = [];
    var links = [];
    var bid = 0;
    var mode = "move";
    var linkSrc = null;
    var selBox = null;
    var selLink = null;
    var zoom = 1;

    var HINTS = {
      move: "Modo <b>Mover</b>: arrastra cajas, clic para seleccionar (Supr borra), doble clic para renombrar.",
      link: "Modo <b>Conectar</b>: pulsa una caja y luego otra para unirlas con una línea.",
      del: "Modo <b>Borrar</b>: pulsa una caja o una línea para eliminarla."
    };

    function setHint() {
      var h = document.getElementById("be-hint");
      if (h) h.innerHTML = HINTS[mode];
    }
    function setBtn(id, on) {
      var b = document.getElementById(id);
      if (b) b.classList.toggle("on", on);
    }
    function setMode(m) {
      mode = m;
      if (linkSrc) { linkSrc.classList.remove("sel"); linkSrc = null; }
      setBtn("be-move", m === "move");
      setBtn("be-link", m === "link");
      setBtn("be-del", m === "del");
      canvas.classList.toggle("linkmode", m === "link");
      canvas.classList.toggle("delmode", m === "del");
      setHint();
      if (m !== "move") clearSel();
    }
    function clearSel() {
      boxes.forEach(function (b) { b.classList.remove("sel"); });
      selBox = null; selLink = null; draw();
    }
    function selectBox(el) { clearSel(); selBox = el; el.classList.add("sel"); draw(); }
    function selectLink(l) { clearSel(); selLink = l; draw(); }

    function setZoom(z) {
      zoom = Math.max(0.5, Math.min(2, Math.round(z * 100) / 100));
      stage.style.transform = "scale(" + zoom + ")";
      var lbl = document.getElementById("be-zoom");
      if (lbl) lbl.textContent = Math.round(zoom * 100) + "%";
    }

    function addBox(label, x, y) {
      var el = document.createElement("div");
      el.className = "ebox";
      el.dataset.id = ++bid;
      el.textContent = label == null ? "Nueva caja" : label;
      el.style.left = (x == null ? 40 + Math.round((bid * 37) % 300) : x) + "px";
      el.style.top = (y == null ? 40 + Math.round((bid * 53) % 230) : y) + "px";
      stage.appendChild(el);
      boxes.push(el);
      el.addEventListener("pointerdown", function (e) { onBoxDown(e, el); });
      el.addEventListener("dblclick", function (e) {
        e.stopPropagation();
        var t = prompt("Texto de la caja:", el.textContent);
        if (t != null) { el.textContent = t; draw(); }
      });
      if (label == null) setMode("move");
      draw();
      return el;
    }
    function deleteBox(el) {
      links = links.filter(function (l) { return l.a !== el && l.b !== el; });
      boxes = boxes.filter(function (b) { return b !== el; });
      el.remove();
      if (selBox === el) selBox = null;
      draw();
    }
    function deleteSelected() {
      if (selBox) deleteBox(selBox);
      else if (selLink) { links = links.filter(function (l) { return l !== selLink; }); selLink = null; draw(); }
    }

    var drag = null;
    function onBoxDown(e, el) {
      if (mode === "del") { e.stopPropagation(); deleteBox(el); return; }
      if (mode === "link") {
        e.stopPropagation();
        if (!linkSrc) { linkSrc = el; el.classList.add("sel"); }
        else if (linkSrc === el) { el.classList.remove("sel"); linkSrc = null; }
        else { links.push({ a: linkSrc, b: el }); linkSrc.classList.remove("sel"); linkSrc = null; draw(); }
        return;
      }
      selectBox(el);
      drag = { el: el, sx: e.clientX, sy: e.clientY, ol: el.offsetLeft, ot: el.offsetTop };
      el.setPointerCapture(e.pointerId);
    }
    document.addEventListener("pointermove", function (e) {
      if (!drag) return;
      var x = drag.ol + (e.clientX - drag.sx) / zoom;
      var y = drag.ot + (e.clientY - drag.sy) / zoom;
      x = Math.max(2, Math.min(x, stage.clientWidth - drag.el.offsetWidth - 2));
      y = Math.max(2, Math.min(y, stage.clientHeight - drag.el.offsetHeight - 2));
      drag.el.style.left = x + "px";
      drag.el.style.top = y + "px";
      draw();
    });
    document.addEventListener("pointerup", function () { drag = null; });

    wires.addEventListener("click", function (e) {
      var i = e.target.getAttribute && e.target.getAttribute("data-i");
      if (i == null) return;
      e.stopPropagation();
      var l = links[+i];
      if (!l) return;
      if (mode === "del") { links = links.filter(function (x) { return x !== l; }); draw(); }
      else selectLink(l);
    });
    canvas.addEventListener("pointerdown", function (e) {
      if (e.target === canvas || e.target === stage || e.target === wires) clearSel();
    });
    document.addEventListener("keydown", function (e) {
      if ((e.key === "Delete" || e.key === "Backspace") && (selBox || selLink)) {
        var tag = (document.activeElement && document.activeElement.tagName) || "";
        if (/INPUT|SELECT|TEXTAREA/.test(tag)) return;
        e.preventDefault();
        deleteSelected();
      }
    });

    function draw() {
      var w = stage.clientWidth, h = stage.clientHeight;
      wires.setAttribute("width", w);
      wires.setAttribute("height", h);
      wires.setAttribute("viewBox", "0 0 " + w + " " + h);
      wires.innerHTML = links.map(function (l, i) {
        var a = l.a, b = l.b;
        var ax = a.offsetLeft + a.offsetWidth / 2, ay = a.offsetTop + a.offsetHeight / 2;
        var bx = b.offsetLeft + b.offsetWidth / 2, by = b.offsetTop + b.offsetHeight / 2;
        var on = l === selLink;
        return '<line class="hit" data-i="' + i + '" x1="' + ax + '" y1="' + ay + '" x2="' + bx + '" y2="' + by + '"/>'
          + '<line data-i="' + i + '" x1="' + ax + '" y1="' + ay + '" x2="' + bx + '" y2="' + by + '" stroke="' + (on ? "#01696f" : "#7a8a97") + '" stroke-width="' + (on ? 3.5 : 2) + '" opacity="' + (on ? 0.95 : 0.6) + '" style="pointer-events:none"/>';
      }).join("");
    }
    function clearCanvas() {
      boxes.forEach(function (b) { b.remove(); });
      boxes = []; links = []; linkSrc = null; selBox = null; selLink = null; draw();
    }

    document.getElementById("be-move").addEventListener("click", function () { setMode("move"); });
    document.getElementById("be-box").addEventListener("click", function () { addBox(); });
    document.getElementById("be-link").addEventListener("click", function () { setMode("link"); });
    document.getElementById("be-del").addEventListener("click", function () { setMode("del"); });
    document.getElementById("be-clear").addEventListener("click", clearCanvas);
    document.getElementById("be-zoomin").addEventListener("click", function () { setZoom(zoom + 0.1); });
    document.getElementById("be-zoomout").addEventListener("click", function () { setZoom(zoom - 0.1); });
    window.addEventListener("resize", draw);

    // Diagrama de ejemplo
    var bInt = addBox("🌐 Internet", 40, 200);
    var bOnt = addBox("ONT", 230, 200);
    var bRt = addBox("Router", 430, 150);
    var bBk = addBox("Backup 4G", 620, 70);
    var bSw = addBox("Switch", 430, 320);
    var bPh = addBox("Teléfono", 650, 320);
    var bAp = addBox("AP WiFi", 860, 320);
    links.push({ a: bInt, b: bOnt }, { a: bOnt, b: bRt }, { a: bRt, b: bBk }, { a: bOnt, b: bSw }, { a: bSw, b: bPh }, { a: bSw, b: bAp });
    setMode("move");
    draw();
    setTimeout(draw, 60);
  });
})();
