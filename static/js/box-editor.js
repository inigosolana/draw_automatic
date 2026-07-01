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
    // "dirty" = el técnico ha editado a mano (mover/conectar/borrar/renombrar).
    // Solo entonces el diagrama final se genera desde estas cajas. buildFromForm
    // (reconstrucción automática) lo deja en false.
    var dirty = false;
    // Historial para deshacer/rehacer (snapshots serializables del lienzo).
    var history = [];
    var histIndex = -1;

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

    // Reglas de conexión por tipo de caja (simétricas). Si un tipo no está en el
    // mapa o la caja no tiene tipo (cajas manuales), se permite cualquier conexión.
    var LINK_RULES = {
      internet: ["ont", "router"],
      ont: ["router"],
      router: ["internet", "ont", "switch", "backup", "terminal", "device", "ap"],
      backup: ["router"],
      switch: ["router", "switch", "terminal", "device", "ap", "pc"],
      ap: ["router", "switch"],
      terminal: ["router", "switch"],
      device: ["router", "switch"]
    };
    function canConnect(a, b) {
      var ta = a.dataset.type || "", tb = b.dataset.type || "";
      if (!ta || !tb) return true;
      var allowed = LINK_RULES[ta];
      if (!allowed) return true;
      return allowed.indexOf(tb) >= 0;
    }

    function addBox(label, x, y, type, model) {
      var el = document.createElement("div");
      el.className = "ebox";
      el.dataset.id = ++bid;
      if (type) el.dataset.type = type;
      if (model) el.dataset.model = model;
      el.textContent = label == null ? "Nueva caja" : label;
      el.style.left = (x == null ? 40 + Math.round((bid * 37) % 300) : x) + "px";
      el.style.top = (y == null ? 40 + Math.round((bid * 53) % 230) : y) + "px";
      stage.appendChild(el);
      boxes.push(el);
      el.addEventListener("pointerdown", function (e) { onBoxDown(e, el); });
      el.addEventListener("dblclick", function (e) {
        e.stopPropagation();
        var t = prompt("Texto de la caja:", el.textContent);
        if (t != null) { el.textContent = t; dirty = true; draw(); pushHistory(); }
      });
      if (label == null) { setMode("move"); dirty = true; }
      draw();
      return el;
    }
    function deleteBox(el) {
      links = links.filter(function (l) { return l.a !== el && l.b !== el; });
      boxes = boxes.filter(function (b) { return b !== el; });
      el.remove();
      if (selBox === el) selBox = null;
      dirty = true;
      draw();
      pushHistory();
    }
    function deleteSelected() {
      if (selBox) deleteBox(selBox);
      else if (selLink) { links = links.filter(function (l) { return l !== selLink; }); selLink = null; dirty = true; draw(); pushHistory(); }
    }

    var drag = null;
    function onBoxDown(e, el) {
      if (mode === "del") { e.stopPropagation(); deleteBox(el); setMode("move"); return; }
      if (mode === "link") {
        e.stopPropagation();
        if (!linkSrc) { linkSrc = el; el.classList.add("sel"); }
        else if (linkSrc === el) { el.classList.remove("sel"); linkSrc = null; }
        else if (!canConnect(linkSrc, el)) {
          var h = document.getElementById("be-hint");
          if (h) h.innerHTML = "❌ Esa conexión no está permitida (p. ej. la ONT solo se conecta al router). Elige otra caja.";
        }
        else { links.push({ a: linkSrc, b: el }); linkSrc.classList.remove("sel"); linkSrc = null; dirty = true; draw(); setMode("move"); pushHistory(); }
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
      drag.moved = true;
      dirty = true;
      draw();
    });
    document.addEventListener("pointerup", function () {
      if (drag && drag.moved) pushHistory();
      drag = null;
    });

    wires.addEventListener("click", function (e) {
      var i = e.target.getAttribute && e.target.getAttribute("data-i");
      if (i == null) return;
      e.stopPropagation();
      var l = links[+i];
      if (!l) return;
      if (mode === "del") { links = links.filter(function (x) { return x !== l; }); dirty = true; draw(); setMode("move"); pushHistory(); }
      else selectLink(l);
    });
    canvas.addEventListener("pointerdown", function (e) {
      if (e.target === canvas || e.target === stage || e.target === wires) clearSel();
    });
    document.addEventListener("keydown", function (e) {
      var tag = (document.activeElement && document.activeElement.tagName) || "";
      var typing = /INPUT|SELECT|TEXTAREA/.test(tag);
      if ((e.ctrlKey || e.metaKey) && (e.key === "z" || e.key === "Z")) {
        if (typing) return;
        e.preventDefault();
        if (e.shiftKey) redo(); else undo();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && (e.key === "y" || e.key === "Y")) {
        if (typing) return;
        e.preventDefault();
        redo();
        return;
      }
      if ((e.key === "Delete" || e.key === "Backspace") && (selBox || selLink)) {
        if (typing) return;
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

    // ---- Deshacer / Rehacer (historial de snapshots) ----
    function snapshot() {
      return {
        boxes: boxes.map(function (b) {
          return {
            id: b.dataset.id, type: b.dataset.type || "", model: b.dataset.model || "",
            label: b.textContent || "", x: b.offsetLeft, y: b.offsetTop
          };
        }),
        links: links.map(function (l) { return { a: l.a.dataset.id, b: l.b.dataset.id }; })
      };
    }
    function restoreSnapshot(snap) {
      clearCanvas();
      var map = {};
      snap.boxes.forEach(function (bx) {
        var el = addBox(bx.label, bx.x, bx.y, bx.type, bx.model);
        el.dataset.id = bx.id;
        var n = parseInt(bx.id, 10);
        if (!isNaN(n) && n > bid) bid = n;
        map[bx.id] = el;
      });
      links = snap.links
        .map(function (lk) { return { a: map[lk.a], b: map[lk.b] }; })
        .filter(function (l) { return l.a && l.b; });
      draw();
    }
    function updateHistoryButtons() {
      var u = document.getElementById("be-undo"), r = document.getElementById("be-redo");
      if (u) u.disabled = histIndex <= 0;
      if (r) r.disabled = histIndex >= history.length - 1;
    }
    function resetHistory() {
      history = [snapshot()];
      histIndex = 0;
      updateHistoryButtons();
    }
    function pushHistory() {
      history = history.slice(0, histIndex + 1);
      history.push(snapshot());
      if (history.length > 60) history.shift();
      histIndex = history.length - 1;
      updateHistoryButtons();
    }
    function undo() {
      if (histIndex <= 0) return;
      histIndex--;
      restoreSnapshot(history[histIndex]);
      dirty = histIndex > 0; // índice 0 = estado generado del formulario
      updateHistoryButtons();
    }
    function redo() {
      if (histIndex >= history.length - 1) return;
      histIndex++;
      restoreSnapshot(history[histIndex]);
      dirty = histIndex > 0;
      updateHistoryButtons();
    }

    document.getElementById("be-move").addEventListener("click", function () { setMode("move"); });
    document.getElementById("be-box").addEventListener("click", function () { addBox(); pushHistory(); });
    document.getElementById("be-link").addEventListener("click", function () { setMode("link"); });
    document.getElementById("be-del").addEventListener("click", function () { setMode("del"); });
    document.getElementById("be-clear").addEventListener("click", function () { clearCanvas(); dirty = true; pushHistory(); });
    var undoBtn = document.getElementById("be-undo");
    if (undoBtn) undoBtn.addEventListener("click", undo);
    var redoBtn = document.getElementById("be-redo");
    if (redoBtn) redoBtn.addEventListener("click", redo);
    document.getElementById("be-zoomin").addEventListener("click", function () { setZoom(zoom + 0.1); });
    document.getElementById("be-zoomout").addEventListener("click", function () { setZoom(zoom - 0.1); });
    window.addEventListener("resize", draw);

    // ---- autorrelleno desde el formulario ----
    function val(id) { var e = document.getElementById(id); return e ? String(e.value || "").trim() : ""; }
    function readForm() {
      var terminals = Array.prototype.map.call(document.querySelectorAll("#terminal-rows .terminal-row"), function (r) {
        var m = r.querySelector('[data-field="model"]');
        var ext = r.querySelector('[data-field="extension"]');
        return { model: m ? m.value.trim() : "", ext: ext ? ext.value.trim() : "" };
      }).filter(function (t) { return t.model; });
      var devices = Array.prototype.map.call(document.querySelectorAll("#device-rows .device-row"), function (r) {
        var cat = r.querySelector('[data-field="category"]');
        var m = r.querySelector('[data-field="model"]');
        var cm = r.querySelector('[data-field="custom-model"]');
        var c = cat ? cat.value : "";
        var model = c === "otros" ? (cm ? cm.value.trim() : "") : (m ? m.value.trim() : "");
        return { category: c, model: model };
      }).filter(function (d) { return d.model; });
      return {
        internet: val("internet-tipo"), ont: val("ont-modelo"),
        router: val("router-modelo"), backup: val("backup-modelo"),
        terminals: terminals, devices: devices
      };
    }
    var COL = [40, 240, 450, 670, 890, 1110];
    function buildFromForm() {
      if (drag) return; // no reconstruir mientras se arrastra
      clearCanvas();
      var f = readForm();
      var col = 0, prev = null, router = null;
      if (f.internet) { prev = addBox("🌐 " + f.internet, COL[col++], 210, "internet"); }
      if (f.ont) { var o = addBox(f.ont, COL[col++], 210, "ont", f.ont); if (prev) links.push({ a: prev, b: o }); prev = o; }
      if (f.router) { router = addBox(f.router, COL[col++], 210, "router", f.router); if (prev) links.push({ a: prev, b: router }); }
      if (f.backup && router) { var bk = addBox("Backup: " + f.backup, COL[Math.max(0, col - 1)], 80, "backup", f.backup); links.push({ a: router, b: bk }); }
      var switches = f.devices.filter(function (d) { return d.category === "switch"; });
      var anchor = router;
      var anchorX = router ? COL[Math.max(0, col - 1)] : 0, anchorY = 210;
      if (switches.length) {
        var sw = addBox(switches[0].model, COL[col], 360, "switch", switches[0].model);
        if (router) links.push({ a: router, b: sw });
        anchor = sw; anchorX = COL[col]; anchorY = 360;
      }
      var endpoints = [];
      f.terminals.forEach(function (t) { endpoints.push({ label: "📞 " + t.model + (t.ext ? " " + t.ext : ""), type: "terminal", model: t.model }); });
      f.devices.forEach(function (d) { if (d.category !== "switch") endpoints.push({ label: d.model, type: d.category === "ap" ? "ap" : "device", model: d.model }); });
      // Colocar los teléfonos/dispositivos debajo del router o switch (como en el
      // diagrama final), en FILAS centradas bajo el ancla (no en columna, para que
      // las líneas no se solapen todas en la misma vertical); el técnico puede
      // moverlos luego. Se reparte en varias filas si hay muchos.
      var stepX = 160, stepY = 90, perRow = 5;
      var anchorCx = anchor ? anchorX : COL[Math.min(col + 1, COL.length - 1)];
      var ey0 = anchor ? anchorY + 100 : 70;
      endpoints.forEach(function (ep, i) {
        var row = Math.floor(i / perRow);
        var colInRow = i % perRow;
        var rowCount = Math.min(perRow, endpoints.length - row * perRow);
        var rowStartX = anchorCx - Math.floor((rowCount - 1) / 2) * stepX;
        var x = Math.max(10, rowStartX + colInRow * stepX);
        var y = ey0 + row * stepY;
        var e = addBox(ep.label, x, y, ep.type, ep.model);
        if (anchor) links.push({ a: anchor, b: e });
      });
      setMode("move");
      dirty = false;
      draw();
      setTimeout(draw, 40);
      resetHistory();
    }
    var rebuildTimer = null;
    function scheduleRebuild() { clearTimeout(rebuildTimer); rebuildTimer = setTimeout(buildFromForm, 220); }
    var form = document.querySelector(".creation-form");
    if (form) {
      form.addEventListener("change", scheduleRebuild);
      form.addEventListener("input", scheduleRebuild);
    }
    buildFromForm();
  });
})();
