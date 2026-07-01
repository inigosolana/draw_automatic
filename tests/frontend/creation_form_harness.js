// Verificación del frontend del formulario de creación (creation-form*.js).
// Ejecuta los módulos JS reales en jsdom contra el HTML real de /draw, simula
// interacciones de usuario y comprueba el DOM. Lo invoca tests/test_frontend_
// creation_form.py (que renderiza el HTML y lo pasa por CREATION_FORM_HTML).
//
// Variables de entorno:
//   CREATION_FORM_HTML  ruta al HTML renderizado de /draw  (obligatoria)
//   CREATION_FORM_JS_DIR  carpeta static/js  (por defecto: ../../static/js)
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const HTML_PATH = process.env.CREATION_FORM_HTML;
const JS_DIR = process.env.CREATION_FORM_JS_DIR
  || path.resolve(__dirname, "..", "..", "static", "js");

if (!HTML_PATH || !fs.existsSync(HTML_PATH)) {
  console.error("Falta CREATION_FORM_HTML (HTML renderizado de /draw).");
  process.exit(2);
}

let pass = 0, fail = 0;
function check(name, cond, extra) {
  if (cond) { pass++; }
  else { fail++; console.log("  ✗ FALLA: " + name + (extra ? "  [" + extra + "]" : "")); }
}

let html = fs.readFileSync(HTML_PATH, "utf8");
html = html.replace(/<script\s+src=[^>]*><\/script>/g, "");

const dom = new JSDOM(html, { runScripts: "dangerously", pretendToBeVisual: true });
const { window } = dom;

const fetchCalls = [];
window.fetch = function (url) {
  fetchCalls.push({ url: String(url) });
  const u = String(url);
  let body = {};
  if (u.includes("/api/templates/")) body = { name: "Plantilla X", payload: { internet_tipo: "SOLO FIBRA", internet_proveedor: "ADAMO", internet_velocidad: "600 MB", ont_modelo: "ONT ADAMO", router_modelo: "MikroTik hAP ac3", backup_modelo: "", router_ip: "10.0.0.1/24" } };
  else if (u.includes("/api/templates")) body = { templates: [{ id: 1, name: "Fibra ADAMO" }] };
  else if (u.includes("/api/connectivity/suggestions")) body = { suggestions: { router_modelo: ["MikroTik hAP ac2"], ont_modelo: ["ONT ZTE"] } };
  else if (u.includes("create-site")) body = { glpi_entity_id: 9999, sede: "Sede 3 - COMEDOR" };
  else if (u.includes("import-work-order")) body = { work_order_id: "7885", cliente: "ACME SL", cif: "B12345678", sede: "Sede 3 - COMEDOR", direccion: "Calle Mayor 1", glpi_matched: true, glpi_confidence: "high", glpi_entity_id: "", glpi_client_id: "10", sede_nueva: true, glpi_message: "cliente encontrado, sede nueva", internet_tipo: "FIBRA + BACK UP", internet_proveedor: "AIRE", internet_velocidad: "300 MB", ont_modelo: "ONT ZTE", router_modelo: "MikroTik hAP ac2", backup_modelo: "WAP LTE", router_ip: "192.168.0.1/24", terminals: [{ model: "W71H", extension: "2001" }], devices_json: [], warnings: ["aviso de prueba"] };
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
};
window.prompt = () => "Mi Plantilla";
window.confirm = () => true;
window.scrollTo = () => {};
if (window.HTMLElement && window.HTMLElement.prototype) {
  window.HTMLElement.prototype.scrollIntoView = function () {};
}

const errors = [];
window.addEventListener("error", (e) => errors.push(e.message || String(e.error)));

function inject(file) {
  const full = path.join(JS_DIR, file);
  if (!fs.existsSync(full)) return;
  const s = window.document.createElement("script");
  s.textContent = fs.readFileSync(full, "utf8");
  window.document.body.appendChild(s);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async function () {
  ["page-bootstrap.js", "device-picker.js", "creation-form.js",
   "creation-form-terminals.js", "creation-form-templates.js",
   "creation-form-workorder.js"].forEach(inject);

  await sleep(50);

  const d = window.document;
  const $ = (id) => d.getElementById(id);
  const fire = (el, type) => el.dispatchEvent(new window.Event(type, { bubbles: true }));

  // 0. carga / globales
  check("sin errores JS en carga", errors.length === 0, errors.join(" | "));
  check("__drawioConnectivity.apply", typeof window.__drawioConnectivity?.apply === "function");
  check("__drawioConnectivity.reset", typeof window.__drawioConnectivity?.reset === "function");
  check("__drawioTerminals", !!window.__drawioTerminals);
  check("__drawioResetForm", typeof window.__drawioResetForm === "function");
  check("__drawioApplyGlpiSuggestion", typeof window.__drawioApplyGlpiSuggestion === "function");
  check("PAGE_CONFIG", !!(window.__DRAWIO_PAGE_CONFIG && window.__DRAWIO_PAGE_CONFIG.templatesUrl));

  // 1. conectividad 4G
  const tipo = $("internet-tipo"), router = $("router-modelo"), ont = $("ont-modelo"), backup = $("backup-modelo");
  tipo.value = "SOLO 4G MONITORIZADO"; fire(tipo, "change");
  check("4G fuerza CHATEAU", router.value === "CHATEAU", router.value);
  check("4G deshabilita ONT", ont.disabled === true);
  check("4G deshabilita backup", backup.disabled === true);

  // 2. fibra
  tipo.value = "FIBRA + BACK UP"; fire(tipo, "change");
  const prov = $("internet-proveedor");
  check("fibra: proveedor AIRE", Array.from(prov.options).some(o => o.value === "AIRE"));
  check("fibra: router hAP ac2", Array.from(router.options).some(o => o.value === "MikroTik hAP ac2"));
  check("fibra: ONT habilitada", ont.disabled === false);

  // 3. apply + baseline + evento
  let eventFired = false;
  d.addEventListener("drawio:connectivity-applied", () => { eventFired = true; });
  window.__drawioConnectivity.apply({ internet_tipo: "SOLO FIBRA", internet_proveedor: "ADAMO", internet_velocidad: "600 MB", ont_modelo: "ONT ADAMO", router_modelo: "MikroTik hAP ac3", backup_modelo: "", router_ip: "10.0.0.1/24" });
  await sleep(10);
  check("evento connectivity-applied", eventFired);
  check("apply: tipo", tipo.value === "SOLO FIBRA", tipo.value);
  check("apply: proveedor", prov.value === "ADAMO", prov.value);
  check("apply: router", router.value === "MikroTik hAP ac3", router.value);
  let baseObj = {}; try { baseObj = JSON.parse($("autofill-baseline").value || "{}"); } catch (e) {}
  check("baseline rellenado por evento", baseObj.internet_proveedor === "ADAMO");

  // 4. plantilla desde desplegable
  const picker = $("template-picker");
  check("desplegable con plantilla", Array.from(picker.options).some(o => o.textContent.includes("Fibra ADAMO")));
  picker.value = "1"; fire(picker, "change");
  await sleep(20);
  check("elegir plantilla aplica router", router.value === "MikroTik hAP ac3", router.value);

  // 5. terminales
  const before = d.querySelectorAll(".terminal-row").length;
  fire($("add-terminal"), "click");
  const after = d.querySelectorAll(".terminal-row").length;
  check("añadir terminal", after === before + 1, `${before}->${after}`);
  const lastRow = d.querySelector("#terminal-rows").lastElementChild;
  const modelSel = lastRow.querySelector('[data-field="model"]');
  modelSel.value = "W71H"; fire(modelSel, "change");
  check("base DECT auto W71H->W60B", lastRow.querySelector('[data-field="dect-base"]').value === "W60B");
  fire(lastRow.querySelector(".remove-terminal"), "click");
  check("eliminar terminal", d.querySelectorAll(".terminal-row").length === after - 1);

  // 6. importar OT
  if ($("work-order-paste")) $("work-order-paste").value = "7885";
  fire($("import-work-order"), "click");
  await sleep(60);
  check("llamada a import-work-order", fetchCalls.some(c => c.url.includes("import-work-order")));
  check("OT rellena cliente", $("cliente").value === "ACME SL", $("cliente").value);
  check("OT rellena sede", $("sede").value === "Sede 3 - COMEDOR", $("sede").value);
  check("OT aplica router", router.value === "MikroTik hAP ac2", router.value);
  check("OT añade terminal W71H", Array.from(d.querySelectorAll(".terminal-row")).some(r => r.querySelector('[data-field="model"]').value === "W71H"));
  check("OT muestra warnings", $("import-work-order-warnings").textContent.includes("aviso de prueba"));

  // 6b. sede nueva -> aparece el botón "Crear sede en GLPI" y crea la sede
  const newSiteBox = $("import-new-site");
  check("sede nueva muestra caja crear-sede", !!newSiteBox && newSiteBox.style.display !== "none");
  const createBtn = newSiteBox && newSiteBox.querySelector("button");
  check("caja crear-sede tiene botón", !!createBtn);
  if (createBtn) {
    fire(createBtn, "click");
    await sleep(40);
    check("click crear-sede llama a create-site", fetchCalls.some(c => c.url.includes("create-site")));
    check("crear-sede fija entity_id nuevo", $("glpi-entity-id").value === "9999", $("glpi-entity-id").value);
    check("crear-sede oculta la caja", newSiteBox.style.display === "none");
  }

  // 7. reset
  window.__drawioResetForm();
  await sleep(10);
  check("reset limpia tipo", tipo.value === "");
  check("reset limpia cliente", $("cliente").value === "");
  check("reset deja 1 terminal", d.querySelectorAll(".terminal-row").length === 1);

  check("sin errores JS en runtime", errors.length === 0, errors.join(" | "));

  console.log(`RESULTADO: ${pass} OK, ${fail} FALLOS`);
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(3); });
