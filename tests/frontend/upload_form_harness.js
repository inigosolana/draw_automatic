// Verificación del frontend de la subida a GLPI (upload-glpi-form.js).
// Ejecuta el JS real en jsdom contra el HTML real de /upload-draw, simula elegir
// un archivo + sede y enviar el formulario, y comprueba que se dispara la subida
// (fetch a /upload-draw/file) SIN lanzar excepción. Regresión del fallo en que
// runUpload referenciaba `config` (definido en otro IIFE) -> ReferenceError ->
// el botón se quedaba en "Subiendo…" y nunca salía la petición.
//
// Lo invoca tests/test_frontend_upload.py, que renderiza el HTML y lo pasa por
// UPLOAD_FORM_HTML.
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const HTML_PATH = process.env.UPLOAD_FORM_HTML;
const JS_DIR = process.env.UPLOAD_FORM_JS_DIR
  || path.resolve(__dirname, "..", "..", "static", "js");

if (!HTML_PATH || !fs.existsSync(HTML_PATH)) {
  console.error("Falta UPLOAD_FORM_HTML (HTML renderizado de /upload-draw).");
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
  return Promise.resolve({
    ok: true,
    status: 200,
    text: () => Promise.resolve(JSON.stringify({ ok: true, id: 1, url: "http://glpi/x", name: "D" })),
  });
};
window.scrollTo = () => {};

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
  inject("upload-glpi-form.js");

  const form = window.document.getElementById("upload-draw-form");
  check("existe el formulario de subida", !!form);
  if (form) {
    // Sede seleccionada (input oculto que rellena el buscador de sedes).
    const entity = window.document.getElementById("upload-entity-id");
    if (entity) entity.value = "5710";
    // Archivo elegido: jsdom no deja asignar .files directo, se define la prop.
    const fileInput = form.querySelector('input[name="drawio_files"]');
    const file = new window.File(["<mxfile></mxfile>"], "REGMA_SA_Sede_25.drawio", { type: "application/xml" });
    Object.defineProperty(fileInput, "files", { value: [file], configurable: true });

    let threw = null;
    try {
      form.dispatchEvent(new window.Event("submit", { cancelable: true, bubbles: true }));
    } catch (e) {
      threw = e && (e.message || String(e));
    }
    await sleep(60);

    check("el submit no lanza excepción", threw === null, threw || "");
    check("no hay errores JS en el envío", errors.length === 0, errors.join("; "));
    check(
      "se dispara la subida (fetch a /upload-draw/file)",
      fetchCalls.some((c) => c.url.includes("/upload-draw/file")),
      "urls=" + JSON.stringify(fetchCalls.map((c) => c.url)),
    );
  }

  console.log("Resultado subida: " + pass + " OK, " + fail + " fallo(s).");
  process.exit(fail === 0 ? 0 : 1);
})();
