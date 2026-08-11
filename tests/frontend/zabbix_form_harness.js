// Verificación puntual de static/js/zabbix-form.js en jsdom: confirma que una
// carga de OT (applyPrefill -> onProvince + applyTipo) dispara UNA sola petición
// al lookup de grupo de Zabbix (dedup por rol+provincia), no dos.
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const JS = fs.readFileSync(path.resolve(__dirname, "..", "..", "static", "js", "zabbix-form.js"), "utf8");
const html = `<!doctype html><html><body
  data-group-lookup-url="/zabbix/api/group"
  data-ot-lookup-url="/zabbix/api/ot">
  <form id="zabbix-form">
    <input id="zabbix-ot" value="7885">
    <button id="zabbix-ot-load" type="button">cargar</button>
    <div id="zabbix-ot-status"></div>
    <select id="zabbix-tipo"><option value="fibra">fibra</option><option value="fibra_backup">fibra_backup</option></select>
    <select id="zabbix-provincia"><option value="">--</option><option value="Cantabria">Cantabria</option></select>
    <input id="zabbix-groupid">
    <div id="zabbix-group-status"></div>
    <input id="zabbix-cliente"><input id="zabbix-sede">
    <input id="zabbix-localidad"><input id="zabbix-calle">
    <select id="zabbix-proveedor"><option value="">--</option><option value="AIRE">AIRE</option></select>
  </form></body></html>`;

const dom = new JSDOM(html, { runScripts: "dangerously", pretendToBeVisual: true });
const { window } = dom;
const groupCalls = [];
window.fetch = function (url) {
  const u = String(url);
  if (u.includes("/api/group")) groupCalls.push(u);
  let body = {};
  if (u.includes("/api/ot")) body = { work_order_id: "7885", tipo: "fibra_backup", provincia: "Cantabria", cliente: "ACME SL", proveedor: "AIRE" };
  else if (u.includes("/api/group")) body = { groupid: "42", name: "Routers Fibra Cantabria" };
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
};
const errors = [];
window.addEventListener("error", (e) => errors.push(e.message || String(e.error)));

const s = window.document.createElement("script");
s.textContent = JS;
window.document.body.appendChild(s);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async function () {
  let pass = 0, fail = 0;
  const check = (n, c, x) => { if (c) pass++; else { fail++; console.log("  x FALLA: " + n + (x ? " [" + x + "]" : "")); } };

  window.document.getElementById("zabbix-ot-load").dispatchEvent(new window.Event("click", { bubbles: true }));
  await sleep(80);

  check("sin errores JS", errors.length === 0, errors.join(" | "));
  check("prefill fijó provincia", window.document.getElementById("zabbix-provincia").value === "Cantabria");
  check("prefill fijó tipo", window.document.getElementById("zabbix-tipo").value === "fibra_backup");
  check("UNA sola peticion de grupo (dedup)", groupCalls.length === 1, groupCalls.length + " llamadas");
  check("groupid asignado", window.document.getElementById("zabbix-groupid").value === "42");

  console.log(`RESULTADO: ${pass} OK, ${fail} FALLOS`);
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(3); });
