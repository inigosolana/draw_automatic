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

// --- Crear un recurso en Passbolt v5 (la contraseña la teclea el técnico) ---
const openpgp = require(path.join(NOP_DIR, "node_modules", "openpgp"));
const V5_DEFAULT_RT = process.env.PASSBOLT_V5_RESOURCE_TYPE || "dd1f723d-0d1e-513f-8218-4055dc0530d0";
// Índice de carpetas normalizado nombre->id, CACHEADO (TTL 5 min). Antes se
// recorrían/normalizaban las ~3.790 carpetas (con await por carpeta) en CADA alta;
// ahora el descifrado/normalización se hace UNA vez por refresco y el match es síncrono.
let _folderIdx = { at: 0, list: [] };
async function _folderIndex() {
  const now = Date.now();
  if (_folderIdx.list.length && (now - _folderIdx.at) <= 300000) return _folderIdx.list;
  const resp = await provider.apiRequest({ method: "GET", url: "/folders.json" });
  const data = (resp && resp.data && resp.data.body) || (resp && resp.data) || [];
  const list = [];
  for (const fol of data) {
    let name = fol.name || "";
    if (fol.metadata) { try { const nr = await provider.normalizeFolderRecord(fol); name = nr.name || name; } catch (e) { /* metadata v5 */ } }
    list.push({ id: fol.id, nn: normName(name) });
  }
  _folderIdx = { at: now, list };
  return list;
}

async function findClientFolder(cliente, cif) {
  const idx = await _folderIndex();
  const cifN = normName(cif);
  const cliN = normName(cliente);
  for (const f of idx) {
    if ((cifN && f.nn.includes(cifN)) || (cliN.length >= 5 && f.nn.includes(cliN))) return f.id;
  }
  return "";
}

// Mapa id->clave pública de usuarios, cacheado (TTL 5 min): cambia poco y se usa
// en cada createResource para cifrar los secretos a los usuarios de la carpeta.
let _usersCache = { at: 0, map: null };
async function usersKeyById() {
  const now = Date.now();
  if (_usersCache.map && (now - _usersCache.at) <= 300000) return _usersCache.map;
  const resp = await provider.apiRequest({ method: "GET", url: "/users.json", params: { "contain[gpgkey]": 1 } });
  const users = (resp && resp.data && resp.data.body) || (resp && resp.data) || [];
  const map = new Map((users || []).map((u) => [u.id, u.gpgkey && u.gpgkey.armored_key]));
  _usersCache = { at: now, map };
  return map;
}

const B = (r) => (r && r.data && r.data.body) || (r && r.data) || r;

async function _encryptSecret(secJson, armoredKey, signKey) {
  const key = await openpgp.readKey({ armoredKey });
  return openpgp.encrypt({ message: await openpgp.createMessage({ text: secJson }), encryptionKeys: key, signingKeys: signKey });
}

// Patrón correcto Passbolt v5: (1) crear el recurso (propietario = usuario API),
// (2) simular el compartir con los usuarios de la carpeta para saber a quién cifrar,
// (3) compartir, (4) mover a la carpeta. Degradación segura: si (2-4) fallan, el
// recurso YA está creado (propiedad del usuario API) y se devuelve un aviso.
async function createResource({ cliente, cif, ip, username, password, folderId }) {
  if (!password) throw new Error("falta la contraseña (la teclea el técnico)");
  const uid = process.env.PASSBOLT_USER_ID;
  const ks = await provider.ensurePrivateKey();
  const userPriv = ks.privateKey;
  const mkMap = await provider.fetchMetadataKeys();
  const shared = [...mkMap.values()].find((k) => k.metadataKeyType === "shared_key") || [...mkMap.values()][0];
  if (!shared) throw new Error("sin metadata key compartida");
  const mkPub = shared.privateKey.toPublic();
  const parent = folderId || await findClientFolder(cliente, cif);

  const me = B(await provider.apiRequest({ method: "GET", url: `/users/${uid}.json`, params: { "contain[gpgkey]": 1 } }));
  const ownerArmored = me.gpgkey.armored_key;

  const name = `${cliente}${cif ? " - " + cif : ""} — ${ip}`.slice(0, 250);
  const metaJson = JSON.stringify({ object_type: "PASSBOLT_RESOURCE_METADATA", resource_type_id: V5_DEFAULT_RT, name, username: username || "Ausarta", uris: ip ? [ip] : [], description: "Router (alta draw_automatic)" });
  const secJson = JSON.stringify({ object_type: "PASSBOLT_SECRET_DATA", password, description: "" });
  const metadata = await openpgp.encrypt({ message: await openpgp.createMessage({ text: metaJson }), encryptionKeys: mkPub, signingKeys: userPriv });

  // (1) crear (propietario = usuario API, secreto solo para él) — esto funciona.
  const ownerSecret = await _encryptSecret(secJson, ownerArmored, userPriv);
  const created = B(await provider.apiRequest({ method: "POST", url: "/resources.json",
    data: { resource_type_id: V5_DEFAULT_RT, metadata, metadata_key_id: shared.id, metadata_key_type: "shared_key", secrets: [{ data: ownerSecret }] } }));
  const resId = created && created.id;
  if (!resId) throw new Error("no se creó el recurso");
  if (!parent) return { id: resId, folder: "", shared_with: 1, moved: false };

  try {
    // permisos deseados = propietario (usuario API) + los usuarios de la carpeta.
    const fol = B(await provider.apiRequest({ method: "GET", url: `/folders/${parent}.json`, params: { "contain[permissions]": 1 } }));
    const keyById = await usersKeyById();
    // permisos = los ACTUALES del recurso (owner, sin is_new) + usuarios de la carpeta (is_new, con aco).
    const cur = B(await provider.apiRequest({ method: "GET", url: `/resources/${resId}.json`, params: { "contain[permissions]": 1 } }));
    const perms = (cur.permissions || []).map((p) => ({ id: p.id, aro: p.aro, aro_foreign_key: p.aro_foreign_key, aco: p.aco, aco_foreign_key: p.aco_foreign_key, type: p.type }));
    const already = new Set(perms.map((p) => p.aro_foreign_key));
    for (const p of (fol.permissions || [])) {
      if (String(p.aro) === "User" && !already.has(p.aro_foreign_key) && keyById.get(p.aro_foreign_key)) {
        perms.push({ is_new: true, aro: "User", aro_foreign_key: p.aro_foreign_key, aco: "Resource", aco_foreign_key: resId, type: p.type || 1 });
      }
    }
    // (2) simular → qué usuarios hay que cifrar.
    const sim = B(await provider.apiRequest({ method: "POST", url: `/share/simulate/resource/${resId}.json`, data: { permissions: perms } }));
    const added = (sim && sim.changes && sim.changes.added) || [];
    const secrets = [];
    for (const a of added) {
      const userId = (a.User && a.User.id) || a.id || a.aro_foreign_key;
      const armored = keyById.get(userId);
      if (userId && armored) secrets.push({ user_id: userId, data: await _encryptSecret(secJson, armored, userPriv) });
    }
    // (3) compartir y (4) mover a la carpeta.
    await provider.apiRequest({ method: "PUT", url: `/share/resource/${resId}.json`, data: { permissions: perms, secrets } });
    await provider.apiRequest({ method: "POST", url: `/move/resource/${resId}.json`, data: { folder_parent_id: parent } });
    return { id: resId, folder: parent, shared_with: perms.length, moved: true };
  } catch (e) {
    return { id: resId, folder: parent, shared_with: 1, moved: false, warn: "creado pero no se pudo compartir/mover a la carpeta: " + ((e && e.message) || e) };
  }
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
  if (req.method === "POST" && req.url.replace(/\/$/, "") === "/credential/create") {
    // Escritura de credenciales: FAIL-CLOSED. Sin token configurado NO se permite crear.
    if (!TOKEN || req.headers["x-helper-token"] !== TOKEN) {
      return send(res, 401, { ok: false, error: "token requerido para crear credenciales" });
    }
    let body = "";
    req.on("data", (c) => { body += c; if (body.length > 1e6) req.destroy(); });
    req.on("end", async () => {
      let p = {};
      try { p = JSON.parse(body || "{}"); } catch { /* ignore */ }
      if (!p.password) return send(res, 400, { ok: false, error: "falta password" });
      try {
        const r = await createResource({
          cliente: p.cliente || "", cif: p.cif || "", ip: p.ip || "",
          username: p.username || "Ausarta", password: p.password, folderId: p.folder_id || "",
        });
        return send(res, 200, { ok: true, ...r });
      } catch (e) {
        return send(res, 502, { ok: false, error: String((e && e.message) || e) });
      }
    });
    return;
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
