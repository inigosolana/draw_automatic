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
      // Suelo bajo (0.3) para que el autoajuste pueda encoger diagramas grandes
      // hasta que quepan enteros; el técnico luego sube el zoom si quiere.
      zoom = Math.max(0.3, Math.min(2, Math.round(z * 100) / 100));
      // Escalar desde la esquina superior izquierda para que el autoajuste deje
      // todo el contenido visible dentro del lienzo.
      stage.style.transformOrigin = "0 0";
      stage.style.transform = "scale(" + zoom + ")";
      var lbl = document.getElementById("be-zoom");
      if (lbl) lbl.textContent = Math.round(zoom * 100) + "%";
    }

    // Ajusta el zoom para que TODO el contenido quepa en el lienzo visible.
    function fitToView() {
      if (!boxes.length) return;
      var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      boxes.forEach(function (b) {
        var x = parseFloat(b.style.left) || 0;
        var y = parseFloat(b.style.top) || 0;
        var w = b.offsetWidth || 130;
        var h = b.offsetHeight || 44;
        if (x < minX) minX = x;
        if (y < minY) minY = y;
        if (x + w > maxX) maxX = x + w;
        if (y + h > maxY) maxY = y + h;
      });
      var contentW = Math.max(1, maxX);
      var contentH = Math.max(1, maxY);
      var pad = 24;
      var cw = canvas.clientWidth || 900;
      var ch = canvas.clientHeight || 460;
      var z = Math.min((cw - pad) / contentW, (ch - pad) / contentH, 1);
      setZoom(z);
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
      // El lienzo de líneas debe cubrir TODO el contenido (aunque los endpoints
      // caigan por debajo del alto visible del canvas), si no las líneas a las
      // cajas de abajo se recortarían. El zoom (fitToView) ya encoge para que
      // quepa todo dentro del área visible.
      var w = stage.clientWidth, h = stage.clientHeight;
      boxes.forEach(function (b) {
        w = Math.max(w, b.offsetLeft + b.offsetWidth + 40);
        h = Math.max(h, b.offsetTop + b.offsetHeight + 40);
      });
      wires.setAttribute("width", w);
      wires.setAttribute("height", h);
      wires.style.width = w + "px";
      wires.style.height = h + "px";
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
      if (typeof clearFloors === "function") clearFloors();
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
        var p = r.querySelector('[data-field="puerto"]');
        var pi = r.querySelector('[data-field="piso"]');
        return { model: m ? m.value.trim() : "", ext: ext ? ext.value.trim() : "", puerto: p ? p.value.trim() : "", piso: pi ? pi.value.trim() : "" };
      }).filter(function (t) { return t.model; });
      var devices = [];
      Array.prototype.forEach.call(document.querySelectorAll("#device-rows .device-row"), function (r) {
        var cat = r.querySelector('[data-field="category"]');
        var m = r.querySelector('[data-field="model"]');
        var cm = r.querySelector('[data-field="custom-model"]');
        var c = cat ? cat.value : "";
        var model = c === "otros" ? (cm ? cm.value.trim() : "") : (m ? m.value.trim() : "");
        if (!model) return;
        var pEl = r.querySelector('[data-field="puerto"]');
        var puerto = pEl ? pEl.value.trim() : "";
        var cEl = r.querySelector('[data-field="conectar"]');
        var conectar = cEl ? cEl.value.trim() : "router";
        // Expandir por cantidad: 2 switches (o 1 fila con cantidad 2) => 2 cajas,
        // igual que en el diagrama final.
        var piEl = r.querySelector('[data-field="piso"]');
        var piso = piEl ? piEl.value.trim() : "";
        var qEl = r.querySelector('[data-field="quantity"]');
        var qty = Math.max(1, parseInt((qEl && qEl.value) || "1", 10) || 1);
        for (var i = 0; i < qty; i++) devices.push({ category: c, model: model, puerto: puerto, conectar: conectar, piso: piso });
      });
      var rp = document.getElementById("router-piso");
      var tp = document.getElementById("tiene-pisos");
      return {
        internet: val("internet-tipo"), ont: val("ont-modelo"),
        router: val("router-modelo"), backup: val("backup-modelo"),
        terminals: terminals, devices: devices,
        tienePisos: tp ? tp.checked : false,
        routerPiso: rp ? rp.value.trim() : ""
      };
    }
    var COL = [40, 240, 450, 670, 890, 1110];
    var floorEls = [];
    var FLOOR_COLORS = [
      ["#dae8fc", "#6c8ebf", "#1a3c6b"], ["#d5e8d4", "#82b366", "#2d5a2d"],
      ["#fff2cc", "#d6b656", "#7a5c00"], ["#ffe6cc", "#d79b00", "#8a4b00"],
      ["#e1d5e7", "#9673a6", "#5b3a6b"], ["#f8cecc", "#b85450", "#7a2320"],
      ["#d0f0f0", "#3a9b9b", "#164f4f"], ["#f5f0d0", "#a39b56", "#5c5320"]
    ];
    function clearFloors() {
      floorEls.forEach(function (el) { el.remove(); });
      floorEls = [];
    }
    // Reorganiza las cajas para que cada piso ocupe su propia BANDA horizontal
    // (así los cuadros de piso no se solapan). Los equipos sin piso (internet,
    // ONT, backup) se quedan arriba. Dentro de cada banda: router/switch en la
    // fila superior y los dispositivos debajo.
    function arrangeByFloor(boxFloor) {
      var groups = {};
      boxFloor.forEach(function (piso, el) {
        if (!piso) return;
        (groups[piso] = groups[piso] || []).push(el);
      });
      var pisos = Object.keys(groups).sort(function (a, b) {
        return (parseInt(a, 10) || 99) - (parseInt(b, 10) || 99);
      });
      var BAND_TOP = 330, BAND_H = 320, ROW_H = 100, PER_ROW = 6, STEP_X = 160, X0 = 90;
      pisos.forEach(function (piso, bi) {
        var els = groups[piso].slice();
        // Primero router/switch (fila superior), luego dispositivos.
        els.sort(function (a, b) {
          var ra = (a.dataset.type === "router" || a.dataset.type === "switch") ? 0 : 1;
          var rb = (b.dataset.type === "router" || b.dataset.type === "switch") ? 0 : 1;
          return ra - rb;
        });
        var heads = els.filter(function (e) { return e.dataset.type === "router" || e.dataset.type === "switch"; });
        var leaves = els.filter(function (e) { return e.dataset.type !== "router" && e.dataset.type !== "switch"; });
        var yBase = BAND_TOP + bi * BAND_H;
        heads.forEach(function (el, i) {
          el.style.left = (X0 + i * STEP_X) + "px";
          el.style.top = yBase + "px";
        });
        leaves.forEach(function (el, i) {
          var row = Math.floor(i / PER_ROW), col = i % PER_ROW;
          el.style.left = (X0 + col * STEP_X) + "px";
          el.style.top = (yBase + ROW_H + row * ROW_H) + "px";
        });
      });
    }
    // Dibuja un rectángulo de fondo por piso, con color propio y semitransparente,
    // englobando sus cajas y con la etiqueta "Piso N" grande. Parecido al diagrama final.
    function drawFloors(boxFloor) {
      clearFloors();
      var groups = {};
      boxFloor.forEach(function (piso, el) {
        if (!piso) return;
        (groups[piso] = groups[piso] || []).push(el);
      });
      var PAD = 26;
      Object.keys(groups).forEach(function (piso) {
        var els = groups[piso];
        var minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
        els.forEach(function (el) {
          minx = Math.min(minx, el.offsetLeft);
          miny = Math.min(miny, el.offsetTop);
          maxx = Math.max(maxx, el.offsetLeft + el.offsetWidth);
          maxy = Math.max(maxy, el.offsetTop + el.offsetHeight);
        });
        if (!isFinite(minx)) return;
        var digits = String(piso).replace(/\D/g, "");
        var idx = (digits ? parseInt(digits, 10) - 1 : 0) % FLOOR_COLORS.length;
        var c = FLOOR_COLORS[idx < 0 ? 0 : idx];
        var box = document.createElement("div");
        box.className = "efloor";
        box.style.position = "absolute";
        box.style.left = (minx - PAD) + "px";
        box.style.top = (miny - PAD - 24) + "px";
        box.style.width = (maxx - minx + PAD * 2) + "px";
        box.style.height = (maxy - miny + PAD * 2 + 24) + "px";
        // Fondo semitransparente por color-alpha (#RRGGBBAA): así el RELLENO es
        // translúcido pero el BORDE queda nítido (no usamos opacity global).
        box.style.background = c[0] + "40";
        box.style.border = "2px dashed " + c[1];
        box.style.borderRadius = "10px";
        box.style.zIndex = "0";
        box.style.pointerEvents = "none";
        var label = document.createElement("div");
        label.textContent = String(piso).toLowerCase().indexOf("piso") === 0 ? piso : ("Piso " + piso);
        label.style.position = "absolute";
        label.style.left = (minx - PAD + 8) + "px";
        label.style.top = (miny - PAD - 24) + "px";
        label.style.fontWeight = "bold";
        label.style.fontSize = "20px";
        label.style.color = c[2];
        label.style.background = "rgba(255,255,255,0.85)";
        label.style.padding = "1px 8px";
        label.style.borderRadius = "6px";
        label.style.zIndex = "2";
        label.style.pointerEvents = "none";
        // El cuadro va al PRINCIPIO del stage (detrás de las cajas); la etiqueta
        // encima para que se lea siempre.
        stage.insertBefore(box, stage.firstChild);
        stage.appendChild(label);
        floorEls.push(box, label);
      });
    }
    function buildFromForm() {
      if (drag) return; // no reconstruir mientras se arrastra
      clearCanvas();
      var f = readForm();
      var boxFloor = new Map(); // el -> piso (para los contenedores de piso)
      var col = 0, prev = null, router = null;
      if (f.internet) { prev = addBox("🌐 " + f.internet, COL[col++], 210, "internet"); }
      if (f.ont) { var o = addBox(f.ont, COL[col++], 210, "ont", f.ont); if (prev) links.push({ a: prev, b: o }); prev = o; }
      if (f.router) { router = addBox(f.router, COL[col++], 210, "router", f.router); if (prev) links.push({ a: prev, b: router }); if (f.routerPiso) boxFloor.set(router, f.routerPiso); }
      if (f.backup && router) { var bk = addBox("Backup: " + f.backup, COL[Math.max(0, col - 1)], 80, "backup", f.backup); links.push({ a: router, b: bk }); }
      var switchDevs = f.devices.filter(function (d) { return d.category === "switch"; });
      var otherDevs = f.devices.filter(function (d) { return d.category !== "switch"; });
      var routerX = router ? COL[Math.max(0, col - 1)] : COL[Math.min(col, COL.length - 1)];

      // Colocar TODOS los switches en fila bajo el router (antes solo se pintaba
      // el primero). Con 2+ switches quedan separados para no solaparse.
      var SW_Y = 360, SW_SPACING = 320;
      var switchNodes = [];
      if (switchDevs.length) {
        var startX = routerX - (switchDevs.length - 1) * SW_SPACING / 2;
        switchDevs.forEach(function (sd, i) {
          // Cascada: el 2º switch con conectar="switch1" cuelga del 1er switch
          // (debajo) en vez del router.
          // Cascada: el 2º switch cuelga del 1º si su puerto es del switch de
          // telefonía (TEL-ETHn) o si el campo conectar lo indica.
          var puertoSw = (sd.puerto || "").toUpperCase();
          var cascada = i >= 1 && switchNodes.length >= 1 &&
            (puertoSw.indexOf("TEL-") === 0 || sd.conectar === "switch1");
          var sx = cascada ? switchNodes[0].x : Math.max(20, startX + i * SW_SPACING);
          var sy = cascada ? SW_Y + 150 : SW_Y;
          var sw = addBox(sd.model, sx, sy, "switch", sd.model);
          if (cascada) links.push({ a: switchNodes[0].node, b: sw });
          else if (router) links.push({ a: router, b: sw });
          if (sd.piso) boxFloor.set(sw, sd.piso);
          switchNodes.push({ node: sw, x: sx, y: sy });
        });
      }

      var terminals = f.terminals.map(function (t) {
        return { label: "📞 " + t.model + (t.ext ? " " + t.ext : ""), type: "terminal", model: t.model, puerto: t.puerto || "", piso: t.piso || "" };
      });
      var devs = otherDevs.map(function (d) {
        return { label: d.model, type: d.category === "ap" ? "ap" : "device", model: d.model, puerto: d.puerto || "", piso: d.piso || "" };
      });

      // Reparte una lista de endpoints en FILAS centradas bajo un ancla (no en
      // columna, para que las líneas no se solapen); el técnico los recoloca luego.
      function placeEndpoints(list, anchor) {
        if (!list.length) return;
        var stepX = 160, stepY = 90, perRow = 5;
        var ax = anchor ? anchor.x : COL[Math.min(col + 1, COL.length - 1)];
        var ey0 = anchor ? anchor.y + 120 : 70;
        list.forEach(function (ep, i) {
          var row = Math.floor(i / perRow);
          var colInRow = i % perRow;
          var rowCount = Math.min(perRow, list.length - row * perRow);
          var rowStartX = ax - Math.floor((rowCount - 1) / 2) * stepX;
          var x = Math.max(10, rowStartX + colInRow * stepX);
          var y = ey0 + row * stepY;
          var e = addBox(ep.label, x, y, ep.type, ep.model);
          if (anchor && anchor.node) links.push({ a: anchor.node, b: e });
          // Piso: propio o heredado del anclaje (switch/router).
          var piso = ep.piso || (anchor && anchor.node ? boxFloor.get(anchor.node) : "");
          if (piso) boxFloor.set(e, piso);
        });
      }

      var routerAnchor = router ? { node: router, x: routerX, y: 210 } : null;
      if (switchNodes.length >= 2) {
        // Respetar el switch elegido por puerto (como el diagrama final):
        // "TEL-*" -> switch de telefonía (1º); "DAT-*" -> switch de datos (2º).
        // Sin prefijo/Auto -> por defecto: teléfonos al 1º, resto al 2º.
        function switchFor(ep, isTerminal) {
          var p = (ep.puerto || "").toUpperCase();
          if (p.indexOf("DAT-") === 0) return switchNodes[1];
          if (p.indexOf("TEL-") === 0) return switchNodes[0];
          return isTerminal ? switchNodes[0] : switchNodes[1];
        }
        var g0 = [], g1 = [];
        terminals.forEach(function (t) { (switchFor(t, true) === switchNodes[1] ? g1 : g0).push(t); });
        devs.forEach(function (d) { (switchFor(d, false) === switchNodes[0] ? g0 : g1).push(d); });
        placeEndpoints(g0, switchNodes[0]);
        placeEndpoints(g1, switchNodes[1]);
      } else if (switchNodes.length === 1) {
        placeEndpoints(terminals.concat(devs), switchNodes[0]);
      } else {
        placeEndpoints(terminals.concat(devs), routerAnchor);
      }

      setMode("move");
      dirty = false;
      draw();
      setTimeout(function () {
        if (f.tienePisos) {
          arrangeByFloor(boxFloor);
          draw();
          drawFloors(boxFloor);
        } else {
          draw();
        }
        fitToView();
      }, 40);
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
