"use strict";
/*
 * Helper de credenciales Passbolt para el alta en Zabbix de draw_automatic (opción B).
 *
 * Corre EN EL HOST (donde ya están las llaves de NOP) y REUTILIZA el
 * passbolt-provider.js de NOP — no reimplementa criptografía. draw_automatic
 * (contenedor) lo llama por HTTP con la IP del router y recibe la contraseña,
 * igual patrón que el helper de versión RouterOS.
 *
 * Flujo:
 *   1. Carga el .env de NOP (PASSBOLT_*) y su passbolt-provider.js.
 *   2. Mapea IP -> resourceId con el autodiscovery-cache de NOP (solo lectura de JSON).
 *   3. Pide a Passbolt el recurso con secreto y lo descifra  <-- (1 punto para el DEV)
 *   4. Devuelve { ok, username, password } por POST /credential.
 *
 * Arranque: scripts/install_credential_helper.sh (systemd + ufw), lo ejecuta un humano.
 */

const fs = require("fs");
const http = require("http");
const path = require("path");

// --- Config (del entorno; el instalador la deja en /etc/ausarta-credential-helper.env) ---
const NOP_DIR = process.env.NOP_DIR || "/home/ubuntu/Network Operations Platform Marcos";
// Bind al gateway del bridge Docker (solo la red del contenedor lo alcanza, no la LAN).
const BIND = process.env.CRED_HELPER_BIND || "172.28.0.1";
const PORT = Number(process.env.CRED_HELPER_PORT || 49600);
const TOKEN = String(process.env.CRED_HELPER_TOKEN || "");
if (!TOKEN) {
  console.warn("[SEGURIDAD] CRED_HELPER_TOKEN vacío: el sidecar NO exige token. " +
    "Define CRED_HELPER_TOKEN (y PASSBOLT_HELPER_TOKEN en la app con el mismo valor).");
}
const AUTODISCOVERY_CACHE = process.env.NOP_AUTODISCOVERY_CACHE
  || path.join(NOP_DIR, "data", "passbolt-autodiscovery-cache.json");

// Carga el .env de NOP sin depender de 'dotenv' (que no está en draw_automatic).
function loadEnvFile(p) {
  try {
    for (const line of fs.readFileSync(p, "utf8").split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
      if (!m) continue;
      let v = m[2];
      if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
        v = v.slice(1, -1);
      }
      if (process.env[m[1]] === undefined) process.env[m[1]] = v;
    }
  } catch (e) { /* si no existe, se usa el entorno ya presente */ }
}
loadEnvFile(path.join(NOP_DIR, ".env"));
const { PassboltProvider } = require(path.join(NOP_DIR, "passbolt-provider.js"));

const provider = new PassboltProvider({
  baseUrl: process.env.PASSBOLT_BASE_URL,
  userId: process.env.PASSBOLT_USER_ID,
  privateKeyPath: process.env.PASSBOLT_PRIVATE_KEY_PATH,
  privateKeyPassphrase: process.env.PASSBOLT_PRIVATE_KEY_PASSPHRASE,
  serverFingerprint: process.env.PASSBOLT_SERVER_FINGERPRINT,
});

// Lee+parsea un JSON con cache por mtime (evita re-parsear el fichero entero en
// cada request; solo relee si el fichero cambió).
const _jsonCache = new Map();
function readJsonCached(p) {
  try {
    const st = fs.statSync(p);
    const c = _jsonCache.get(p);
    if (c && c.mtimeMs === st.mtimeMs) return c.data;
    const data = JSON.parse(fs.readFileSync(p, "utf8"));
    _jsonCache.set(p, { mtimeMs: st.mtimeMs, data });
    return data;
  } catch (e) {
    return JSON.parse(fs.readFileSync(p, "utf8"));  // propaga el error original si falla
  }
}

// IP del router -> resourceId + username, leyendo el autodiscovery cache de NOP.
function resolveResourceByIp(ip) {
  const raw = readJsonCached(AUTODISCOVERY_CACHE);
  const clients = raw.clients || {};
  for (const key of Object.keys(clients)) {
    const routers = clients[key].mikrotikRouters || [];
    for (const r of routers) {
      const connect = String(r.connectTo || r.displayConnectTo || "").split(":")[0];
      const sources = (r.sourceConnectTos || []).map((c) => String(c).split(":")[0]);
      if (connect === ip || sources.includes(ip)) {
        return { resourceId: r.resourceId, username: r.username || "", label: r.label || r.name || "" };
      }
    }
  }
  return null;
}

async function resolvePassword(ip) {
  const match = resolveResourceByIp(ip);
  if (!match || !match.resourceId) {
    throw new Error(`No hay recurso Passbolt para la IP ${ip} en el autodiscovery de NOP.`);
  }

  // Recupera el recurso por id con su secreto y lo descifra con el provider de NOP
  // (apiRequest gestiona el login JWT; normalizeResourceRecord descifra con la clave).
  const resp = await provider.apiRequest({
    method: "GET",
    url: `/resources/${match.resourceId}.json`,
    params: { "contain[secret]": 1 },
  });
  const raw = (resp && resp.data && resp.data.body) || (resp && resp.data) || {};
  const record = await provider.normalizeResourceRecord(raw, { includeSecret: true });
  const secret = record.secret || {};
  return {
    username: match.username || record.username || secret.username || "",
    password: secret.password || "",
  };
}

// Inventario de routers de NOP (IP + versión) por cliente/CIF. No es secreto:
// solo lee el cache de autoescaneo de NOP para autorrellenar IP y versión.
const ROUTER_EXAMPLES = process.env.NOP_ROUTER_EXAMPLES
  || path.join(NOP_DIR, "data", "mikrotik-router-examples-cache.json");

function normName(s) {
  return String(s || "").toUpperCase().normalize("NFKD")
    .replace(/[̀-ͯ]/g, "").replace(/[^A-Z0-9]+/g, "");
}

function resolveClientRouters(cif, cliente) {
  const raw = readJsonCached(ROUTER_EXAMPLES);
  const items = raw.items || [];
  const cifU = String(cif || "").toUpperCase().trim();
  const cliN = normName(cliente);
  const out = [];
  for (const r of items) {
    if (!r.ok) continue;
    const name = String(r.clientName || "");
    const match = (cifU && name.toUpperCase().includes(cifU))
      || (cliN.length >= 5 && normName(name).includes(cliN));
    if (!match) continue;
    const ip = String(r.displayConnectTo || "").split(":")[0];
    const major = parseInt(String(r.version || "").trim(), 10);
    out.push({
      ip,
      version: r.version || "",
      is_v7: Number.isFinite(major) && major >= 7,
      type: r.routerType || "",       // "fiber" | "backup" | ...
      board: r.boardName || "",        // p. ej. "Chateau 5G R17 ax" | "hAP ac^2"
      label: r.routerLabel || r.clientName || "",
      routerId: r.routerId || "",
    });
  }
  return out;
}

// Servicios activos del cliente en Yeastar (proveedor de fibra + si tiene backup).
// No es secreto: son datos de servicio. Consulta por psql al contenedor de Yeastar.
const { execFileSync } = require("child_process");

function yeastarServices(cif, cliente) {
  // Parametrizado con variables de psql (:'var') → sin interpolar en el SQL.
  const conds = [];
  const vars = [];
  if (cif) { conds.push("cif = :'cif'"); vars.push("-v", "cif=" + String(cif)); }
  if (cliente) { conds.push("nombre ILIKE :'cli'"); vars.push("-v", "cli=%" + String(cliente) + "%"); }
  if (!conds.length) return { proveedor: "", tiene_backup: false, backup_proveedor: "" };
  const sql = "select tipo, service, coalesce(proveedor,'') from servicios_crm "
    + `where activo=true and (${conds.join(" OR ")})`;
  let out = "";
  try {
    out = execFileSync("docker", [
      "exec", "yeastar_postgres", "psql", "-U", "postgres", "-d", "yeastar_unificado",
      ...vars, "-tAF", "|", "-c", sql,
    ], { timeout: 8000, encoding: "utf8" });
  } catch (e) {
    return { proveedor: "", tiene_backup: false, backup_proveedor: "", error: String(e.message || e) };
  }
  let proveedor = "";
  let tieneBackup = false;
  let backupProv = "";
  for (const line of out.split(/\r?\n/)) {
    if (!line.trim()) continue;
    const [tipo, service, prov] = line.split("|");
    const s = String(service || "").toUpperCase();
    if (String(tipo).toLowerCase() === "fibra" && !proveedor) proveedor = prov || "";
    if (s.includes("BACKUP")) { tieneBackup = true; if (!backupProv) backupProv = prov || ""; }
  }
  return { proveedor, tiene_backup: tieneBackup, backup_proveedor: backupProv };
}

// --- IP privada del backup: router de túneles de NOP (/ppp/secret) ---
const TUNNELS_IP = process.env.TUNNELS_ROUTER_IP || "45.13.211.10";
const TUNNELS_USER = process.env.TUNNELS_ROUTER_USER || "api";
const TUNNELS_PASS = process.env.TUNNELS_ROUTER_PASS || "";
let _secretsCache = { at: 0, data: [] };

function tunnelGet(pathRest) {
  return new Promise((resolve) => {
    const auth = Buffer.from(`${TUNNELS_USER}:${TUNNELS_PASS}`).toString("base64");
    const req = http.request(
      { host: TUNNELS_IP, port: 8080, path: "/rest" + pathRest, method: "GET",
        headers: { Authorization: "Basic " + auth }, timeout: 15000 },
      (res) => { let d = ""; res.on("data", (c) => { d += c; }); res.on("end", () => { try { resolve(JSON.parse(d || "[]")); } catch { resolve([]); } }); },
    );
    req.on("error", () => resolve([]));
    req.on("timeout", () => { req.destroy(); resolve([]); });
    req.end();
  });
}

async function tunnelBackupIps(cliente) {
  if (!TUNNELS_PASS) return [];
  const now = Date.now();
  if (now - _secretsCache.at > 120000) {
    _secretsCache = { at: now, data: await tunnelGet("/ppp/secret") };
  }
  const cliN = normName(cliente);
  if (cliN.length < 5) return [];
  const out = [];
  for (const s of _secretsCache.data || []) {
    const name = String(s.name || "");
    const ip = String(s["remote-address"] || "").trim();
    if (!ip) continue;
    const nn = normName(name);
    // backup = secret del cliente con sufijo BU
    if (nn.includes(cliN) && /BU$/.test(nn)) out.push({ name, ip });
  }
  return out;
}

function send(res, code, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(code, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) });
  res.end(body);
}

const server = http.createServer((req, res) => {
  if (req.method === "GET" && req.url.replace(/\/$/, "") === "/health") {
    return send(res, 200, { ok: true, service: "credential-helper" });
  }
  if (req.method === "GET" && req.url.split("?")[0].replace(/\/$/, "") === "/routers") {
    if (TOKEN && req.headers["x-helper-token"] !== TOKEN) {
      return send(res, 401, { ok: false, error: "token inválido" });
    }
    try {
      const u = new URL(req.url, "http://local.invalid");
      const routers = resolveClientRouters(u.searchParams.get("cif") || "", u.searchParams.get("cliente") || "");
      return send(res, 200, { ok: true, routers });
    } catch (e) {
      return send(res, 502, { ok: false, error: String(e && e.message || e) });
    }
  }
  if (req.method === "GET" && req.url.split("?")[0].replace(/\/$/, "") === "/tunnel-ip") {
    if (TOKEN && req.headers["x-helper-token"] !== TOKEN) {
      return send(res, 401, { ok: false, error: "token inválido" });
    }
    const u = new URL(req.url, "http://local.invalid");
    tunnelBackupIps(u.searchParams.get("cliente") || "")
      .then((matches) => send(res, 200, { ok: true, matches }))
      .catch((e) => send(res, 502, { ok: false, error: String(e && e.message || e) }));
    return;
  }
  if (req.method === "GET" && req.url.split("?")[0].replace(/\/$/, "") === "/services") {
    if (TOKEN && req.headers["x-helper-token"] !== TOKEN) {
      return send(res, 401, { ok: false, error: "token inválido" });
    }
    try {
      const u = new URL(req.url, "http://local.invalid");
      const svc = yeastarServices(u.searchParams.get("cif") || "", u.searchParams.get("cliente") || "");
      return send(res, 200, { ok: true, ...svc });
    } catch (e) {
      return send(res, 502, { ok: false, error: String(e && e.message || e) });
    }
  }
  if (req.method !== "POST" || req.url.replace(/\/$/, "") !== "/credential") {
    return send(res, 404, { ok: false, error: "not found" });
  }
  if (TOKEN && req.headers["x-helper-token"] !== TOKEN) {
    return send(res, 401, { ok: false, error: "token inválido" });
  }
  let data = "";
  req.on("data", (c) => { data += c; if (data.length > 1e6) req.destroy(); });
  req.on("end", async () => {
    let ip = "";
    try { ip = String((JSON.parse(data || "{}").ip) || "").trim(); } catch { /* ignore */ }
    if (!ip) return send(res, 400, { ok: false, error: "falta ip" });
    try {
      const cred = await resolvePassword(ip);
      return send(res, 200, { ok: true, username: cred.username || "", password: cred.password || "" });
    } catch (e) {
      return send(res, 502, { ok: false, error: String(e && e.message || e) });
    }
  });
});

server.listen(PORT, BIND, () => {
  console.log(`credential-helper escuchando en ${BIND}:${PORT} (reusa passbolt-provider de ${NOP_DIR})`);
});
