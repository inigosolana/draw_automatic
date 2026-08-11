(function () {
  const form = document.getElementById("zabbix-form");
  if (!form) return;

  const $ = (id) => document.getElementById(id);
  const tipoEl = $("zabbix-tipo");
  const provinceSelect = $("zabbix-provincia");
  const groupStatus = $("zabbix-group-status");
  const groupIdInput = $("zabbix-groupid");
  const clienteEl = $("zabbix-cliente");
  const sedeEl = $("zabbix-sede");
  const localidadEl = $("zabbix-localidad");
  const calleEl = $("zabbix-calle");
  const proveedorEl = $("zabbix-proveedor");
  const proveedorLabel = $("zabbix-proveedor-label");
  const provBackupWrap = $("zabbix-proveedor-backup-wrap");
  const provBackupEl = $("zabbix-proveedor-backup");
  const lteWrap = $("zabbix-lte-tpl-wrap");
  const lteTpl = $("zabbix-lte-tpl");
  const ipLabel = $("zabbix-router-ip-label");
  const passwordWrap = $("zabbix-router-password-wrap");
  const routerIp = $("zabbix-router-ip");
  const routerPassword = $("zabbix-router-password");
  const versionBlock = $("zabbix-version-block");
  const versionManual = $("zabbix-version-manual");
  const versionStatus = $("zabbix-version-status");
  const checkVersionBtn = $("zabbix-check-version");
  const backupWrap = $("zabbix-backup-wrap");
  const backupTipo = $("zabbix-backup-tipo");
  const backupIp = $("zabbix-backup-ip");
  const namePreview = $("zabbix-name-preview");

  const otEl = $("zabbix-ot");
  const otBtn = $("zabbix-ot-load");
  const otStatus = $("zabbix-ot-status");

  const groupLookupUrl = document.body.dataset.groupLookupUrl;
  const versionLookupUrl = document.body.dataset.versionLookupUrl;
  const otLookupUrl = document.body.dataset.otLookupUrl;
  const clientLookupUrl = document.body.dataset.clientLookupUrl;
  const csrfToken = (form.querySelector('[name="csrf_token"]') || {}).value || "";

  function setVal(sel, value) {
    if (!sel) return;
    if (sel.tagName === "SELECT" && value) {
      if (!Array.from(sel.options).some((o) => o.value === value)) {
        const o = document.createElement("option");
        o.value = value; o.textContent = value; sel.appendChild(o);
      }
    }
    sel.value = value || "";
  }

  function applyPrefill(p, sourceMsg) {
    if (tipoEl && p.tipo) tipoEl.value = p.tipo;
    if (provinceSelect && p.provincia) { setVal(provinceSelect, p.provincia); onProvince(); }
    if (clienteEl && p.cliente) { setVal(clienteEl, p.cliente); onCliente(); }
    if (sedeEl && p.sede) setVal(sedeEl, p.sede);
    if (localidadEl) localidadEl.value = p.localidad || localidadEl.value || "";
    if (calleEl) calleEl.value = p.calle || calleEl.value || "";
    if (proveedorEl && p.proveedor) setVal(proveedorEl, p.proveedor);
    if (provBackupEl && p.proveedor_backup) setVal(provBackupEl, p.proveedor_backup);
    if (backupTipo && p.backup_tipo) setVal(backupTipo, p.backup_tipo);
    if (routerIp && p.router_ip) routerIp.value = p.router_ip;
    if (backupIp && p.backup_ip) backupIp.value = p.backup_ip;
    if (p.routeros_version) {
      const radio = form.querySelector('input[name="routeros_version"][value="' + p.routeros_version + '"]');
      if (radio) radio.checked = true;
    }
    applyTipo();
    let msg = sourceMsg + (p.cliente || "");
    if (p.router_ip) {
      msg += " · IP " + p.router_ip + (p.nop_version ? " (RouterOS " + p.nop_version + ")" : "") + " autodetectada";
    } else {
      msg += " · pon la IP del router a mano";
    }
    if (p.tiene_backup_detectado) {
      msg += " · tiene BACKUP" + (p.backup_ip ? " (IP " + p.backup_ip + ")" : " (pon su IP y tipo)");
    }
    if (p.existentes) {
      const f = p.existentes.fibra, b = p.existentes.backup;
      const t = p.tipo || "fibra";
      if (t === "chateau") {
        msg += " · Instalación CHATEAU · EN ZABBIX → chateau: " + (f ? "✅ ya creado" : "❌ NO");
      } else if (t === "fibra_backup") {
        msg += " · Instalación FIBRA+BACKUP · EN ZABBIX → fibra: " + (f ? "✅" : "❌ NO") +
               ", backup: " + (b ? "✅" : "❌ NO");
      } else {
        msg += " · Instalación FIBRA · EN ZABBIX → fibra: " + (f ? "✅ ya creada" : "❌ NO");
      }
    }
    if (p.router_options && p.router_options.length > 1) {
      msg += " · OJO: " + p.router_options.length + " routers (" +
        p.router_options.map(function (o) { return o.ip; }).join(", ") + "), revisa cuál";
    }
    if (p.warnings && p.warnings.length) msg += "  ⚠ " + p.warnings.join("; ");
    setStatus(otStatus, msg, "ok");
  }

  async function fetchT(url, opts, ms) {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), ms || 12000);
    try {
      return await fetch(url, Object.assign({ signal: ctrl.signal }, opts || {}));
    } finally {
      clearTimeout(t);
    }
  }

  async function loadOT(ot) {
    if (!otLookupUrl) return;
    setStatus(otStatus, "Cargando OT " + ot + "...", "loading");
    try {
      const r = await fetchT(otLookupUrl + "?ot=" + encodeURIComponent(ot), { credentials: "same-origin" }, 15000);
      const p = await r.json();
      if (!r.ok) throw new Error(p.error || "No se pudo cargar la OT.");
      applyPrefill(p, "OT " + (p.work_order_id || ot) + " cargada: ");
    } catch (e) {
      setStatus(otStatus, e.message || "Error cargando la OT.", "error");
    }
  }

  async function loadClient() {
    if (!clientLookupUrl) { setStatus(otStatus, "Elige provincia, cliente y sede.", "error"); return; }
    const cliente = clienteEl ? clienteEl.value.trim() : "";
    const sede = sedeEl ? sedeEl.value.trim() : "";
    if (!cliente) { setStatus(otStatus, "Elige el cliente (provincia → cliente → sede).", "error"); return; }
    // CIF del cliente elegido (del catálogo GLPI embebido), mejora la búsqueda.
    let cif = "";
    const c = cliObj();
    if (c && c.cif) cif = c.cif;
    setStatus(otStatus, "Buscando datos de " + cliente + "...", "loading");
    try {
      const qs = "cliente=" + encodeURIComponent(cliente) + "&sede=" + encodeURIComponent(sede) + "&cif=" + encodeURIComponent(cif);
      const r = await fetchT(clientLookupUrl + "?" + qs, { credentials: "same-origin" }, 15000);
      const p = await r.json();
      if (!r.ok) throw new Error(p.error || "No se pudieron buscar los datos.");
      applyPrefill(p, "Cliente cargado: ");
    } catch (e) {
      setStatus(otStatus, e.message || "Error buscando datos del cliente.", "error");
    }
  }

  function loadData() {
    const ot = (otEl && otEl.value || "").trim();
    if (ot) loadOT(ot); else loadClient();
  }

  const PROVIDER_ABBR = {
    SARENET: "SAR", AIRE: "AIR", ADAMO: "ADA", MASMOVIL: "MM", "MAS MOVIL": "MM",
    ORANGE: "ORA", "SARENET ORANGE": "ORA", EUSKALTEL: "EUS", MOVISTAR: "MOV",
    VODAFONE: "VOD", PTV: "PTV", DUAL: "DUAL",
  };
  const BACKUP_ABBR = { TELTONIKA: "TEL", KITE: "KIT", "WAP LTE": "WAP", WAP: "WAP" };

  let catalog = [];
  try { catalog = JSON.parse(($("zabbix-catalog") || {}).textContent || "[]"); } catch (e) { catalog = []; }
  const hasCatalog = Array.isArray(catalog) && catalog.length > 0;

  const BGP_TYPES = ["fibra", "fibra_backup", "chateau", "dual"];
  const tipo = () => (tipoEl ? tipoEl.value : "fibra");
  const isBGP = () => BGP_TYPES.includes(tipo());
  const groupRole = () => (tipo() === "lte" ? "LTE" : "Fibra");

  function show(el, on) { if (el) el.hidden = !on; }
  function namePart(t) {
    return String(t || "").trim().toUpperCase().normalize("NFKD")
      .replace(/[̀-ͯ]/g, "").replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  }
  function abbr(map, v) {
    const key = String(v || "").trim().toUpperCase().replace(/\s+/g, " ");
    if (map[key]) return map[key];
    const letters = key.replace(/[^A-Z0-9]/g, "");
    return letters.slice(0, 3) || "GEN";
  }
  function setStatus(el, msg, state) {
    if (!el) return; el.textContent = msg; el.className = "zabbix-group-status";
    if (state) el.classList.add("is-" + state);
  }

  function applyTipo() {
    const t = tipo();
    show(provBackupWrap, t === "chateau" || t === "dual");
    show(lteWrap, t === "lte");
    show(passwordWrap, isBGP());
    show(versionBlock, isBGP());
    show(backupWrap, t === "fibra_backup");
    if (lteTpl) lteTpl.required = t === "lte";
    // El backup no bloquea el alta: si falta la IP de túnel se crea solo la fibra
    // y se avisa. Solo se exige el tipo de backup si se ha puesto una IP.
    if (backupIp) backupIp.required = false;
    if (backupTipo) backupTipo.required = t === "fibra_backup" && !!(backupIp && backupIp.value.trim());
    if (routerPassword) routerPassword.disabled = !isBGP();
    if (proveedorLabel) proveedorLabel.textContent = (t === "lte") ? "Operador" : "Proveedor";
    if (ipLabel) ipLabel.textContent = (t === "lte") ? "IP del equipo LTE / 4G" : "IP pública del router";
    lookupGroup(provinceSelect ? provinceSelect.value.trim() : "");
    updateNamePreview();
  }

  function updateNamePreview() {
    if (!namePreview) return;
    const t = tipo(), cli = clienteEl ? clienteEl.value : "", sede = sedeEl ? sedeEl.value : "";
    const prov = proveedorEl ? proveedorEl.value : "";
    const loc = localidadEl ? localidadEl.value : "", cal = calleEl ? calleEl.value : "";
    if (!prov || !cli || !sede) { namePreview.textContent = ""; return; }
    const tail = (head, ab) => [head, ab, namePart(cli), namePart(sede), namePart(loc), namePart(cal)]
      .filter(Boolean).join("_").slice(0, 128);
    let msg;
    if (t === "lte") msg = "Host: " + tail("LTE", abbr(PROVIDER_ABBR, prov));
    else if (t === "dual") msg = "Host: " + tail("FTTH", "DUAL");
    else msg = "Router: " + tail("FTTH", abbr(PROVIDER_ABBR, prov));
    if (t === "fibra_backup" && backupTipo && backupTipo.value) {
      msg += "  ·  Backup: " + tail("BACKUP", abbr(BACKUP_ABBR, backupTipo.value));
    }
    setStatus(namePreview, msg, "ok");
  }

  // ---- cascada provincia -> cliente -> sede (catálogo GLPI) ----
  function fillSel(sel, items, ph, val, lab) {
    if (!sel) return;
    sel.innerHTML = "";
    const o0 = document.createElement("option"); o0.value = ""; o0.textContent = ph; sel.appendChild(o0);
    items.forEach((it) => { const o = document.createElement("option"); o.value = val(it); o.textContent = lab(it); sel.appendChild(o); });
  }
  const provObj = () => catalog.find((p) => p.nombre === (provinceSelect && provinceSelect.value));
  const cliObj = () => { const p = provObj(); return p && (p.clientes || []).find((c) => c.nombre === (clienteEl && clienteEl.value)); };
  const sedeObjSel = () => { const c = cliObj(); return c && (c.sedes || []).find((s) => s.nombre === (sedeEl && sedeEl.value)); };

  function onProvince() {
    lookupGroup(provinceSelect ? provinceSelect.value.trim() : "");
    if (hasCatalog) {
      const p = provObj();
      fillSel(clienteEl, p ? (p.clientes || []) : [], "Selecciona cliente", (c) => c.nombre, (c) => c.nombre);
      fillSel(sedeEl, [], "Selecciona cliente primero", (s) => s.nombre, (s) => s.nombre);
      if (localidadEl) localidadEl.value = ""; if (calleEl) calleEl.value = "";
    }
    updateNamePreview();
  }
  function onCliente() {
    if (hasCatalog) {
      const c = cliObj();
      fillSel(sedeEl, c ? (c.sedes || []) : [], "Selecciona sede", (s) => s.nombre, (s) => s.nombre);
      if (localidadEl) localidadEl.value = ""; if (calleEl) calleEl.value = "";
    }
    updateNamePreview();
  }
  function onSede() {
    if (hasCatalog) { const s = sedeObjSel(); if (localidadEl) localidadEl.value = s ? (s.localidad || "") : ""; if (calleEl) calleEl.value = s ? (s.calle || "") : ""; }
    updateNamePreview();
  }

  let _lastGroupKey = null;
  async function lookupGroup(province) {
    if (!groupLookupUrl) return;
    if (!province) { _lastGroupKey = null; if (groupIdInput) groupIdInput.value = ""; setStatus(groupStatus, "Selecciona una provincia para asignar el grupo en Zabbix.", ""); return; }
    // Evita la doble petición idéntica: el prefill llama onProvince() y applyTipo()
    // seguidos, ambos con el mismo (rol, provincia). Si el par no cambió, no repetimos.
    const key = groupRole() + "|" + province;
    if (key === _lastGroupKey) return;
    _lastGroupKey = key;
    setStatus(groupStatus, "Buscando grupo en Zabbix...", "loading");
    try {
      const url = groupLookupUrl + "?role=" + encodeURIComponent(groupRole()) + "&provincia=" + encodeURIComponent(province);
      const r = await fetchT(url, { credentials: "same-origin" }, 10000);
      const p = await r.json();
      if (!r.ok) throw new Error(p.error || "No se pudo consultar el grupo.");
      if (groupIdInput) groupIdInput.value = p.groupid || "";
      setStatus(groupStatus, "Grupo: " + (p.name || province), "ok");
    } catch (e) {
      if (groupIdInput) groupIdInput.value = "";
      setStatus(groupStatus, e.message || "Provincia no encontrada en Zabbix.", "error");
    }
  }

  async function checkVersion() {
    if (!versionLookupUrl) return;
    const ip = (routerIp && routerIp.value || "").trim();
    const password = (routerPassword && routerPassword.value) || "";
    if (!ip || !password) { setStatus(versionStatus, "Introduce IP y contraseña para comprobar la versión.", "error"); return; }
    setStatus(versionStatus, "Consultando el router...", "loading");
    try {
      const r = await fetchT(versionLookupUrl, {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
        body: JSON.stringify({ router_ip: ip, router_password: password }),
      }, 15000);
      const p = await r.json();
      if (!r.ok || !p.ok) throw new Error(p.error || "No se pudo detectar la versión.");
      setStatus(versionStatus, "Versión " + p.version + " → " + p.template, "ok");
      if (versionManual) versionManual.hidden = true;
    } catch (e) {
      setStatus(versionStatus, (e.message || "Error") + " Indica v6/v7 a mano.", "error");
      if (versionManual) versionManual.hidden = false;
    }
  }

  if (tipoEl) tipoEl.addEventListener("change", applyTipo);
  if (provinceSelect) { provinceSelect.addEventListener("change", onProvince); }
  if (clienteEl) clienteEl.addEventListener("change", onCliente);
  if (sedeEl) sedeEl.addEventListener("change", onSede);
  [proveedorEl, provBackupEl, localidadEl, calleEl, backupTipo, lteTpl].forEach((el) => {
    if (!el) return;
    el.addEventListener("change", updateNamePreview);
    el.addEventListener("input", updateNamePreview);
  });
  // Buscador de cliente (independiente de la provincia): datalist con todos los
  // clientes; al elegir uno, rellena provincia → cliente → sede y carga sus datos.
  const cliBuscar = $("zabbix-cliente-buscar");
  const cliDatalist = $("zabbix-cliente-datalist");
  if (cliBuscar && cliDatalist && hasCatalog) {
    catalog.forEach((prov) => (prov.clientes || []).forEach((c) => {
      const o = document.createElement("option");
      o.value = c.nombre;
      o.label = c.nombre + " — " + prov.nombre;
      cliDatalist.appendChild(o);
    }));
    cliBuscar.addEventListener("change", () => {
      const name = cliBuscar.value.trim();
      if (!name) return;
      let found = null;
      for (const prov of catalog) {
        const c = (prov.clientes || []).find((x) => x.nombre === name);
        if (c) { found = { prov: prov.nombre, cli: c }; break; }
      }
      if (!found) return;
      if (provinceSelect) { provinceSelect.value = found.prov; onProvince(); }
      if (clienteEl) { clienteEl.value = found.cli.nombre; onCliente(); }
      const sedes = found.cli.sedes || [];
      if (sedeEl && sedes.length) { sedeEl.value = sedes[0].nombre; onSede(); }
      loadClient();
    });
  }

  if (backupIp) backupIp.addEventListener("input", applyTipo);
  if (checkVersionBtn) checkVersionBtn.addEventListener("click", checkVersion);
  if (otBtn) otBtn.addEventListener("click", loadData);
  if (otEl) otEl.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); loadData(); } });

  applyTipo();
  if (provinceSelect && provinceSelect.value.trim()) onProvince();
})();
