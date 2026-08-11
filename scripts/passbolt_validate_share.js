"use strict";
/*
 * VALIDACIÓN del flujo de creación+compartición Passbolt v5 (patrón correcto:
 * crear → simular → compartir → mover a la carpeta), sobre una carpeta de cliente
 * REAL con varios usuarios, usando una contraseña FALSA y borrando al final.
 * No deja nada en Passbolt. Sirve para confirmar el contrato del servidor antes de
 * fiarse de la casilla "Guardar en Passbolt" del alta.
 *
 *   node /home/ubuntu/draw_automatic/scripts/passbolt_validate_share.js
 */
const fs = require("fs"), path = require("path");
const NOP_DIR = process.env.NOP_DIR || "/home/ubuntu/Network Operations Platform Marcos";
function loadEnvFile(p) { try { for (const line of fs.readFileSync(p, "utf8").split(/\r?\n/)) { const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/); if (!m) continue; let v = m[2]; if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) v = v.slice(1, -1); if (process.env[m[1]] === undefined) process.env[m[1]] = v; } } catch (e) { } }
loadEnvFile(path.join(NOP_DIR, ".env"));
const openpgp = require(path.join(NOP_DIR, "node_modules", "openpgp"));
const { PassboltProvider } = require(path.join(NOP_DIR, "passbolt-provider.js"));
const provider = new PassboltProvider({ baseUrl: process.env.PASSBOLT_BASE_URL, userId: process.env.PASSBOLT_USER_ID, privateKeyPath: process.env.PASSBOLT_PRIVATE_KEY_PATH, privateKeyPassphrase: process.env.PASSBOLT_PRIVATE_KEY_PASSPHRASE, serverFingerprint: process.env.PASSBOLT_SERVER_FINGERPRINT });
const B = (r) => (r && r.data && r.data.body) || (r && r.data) || r;
const RT = "dd1f723d-0d1e-513f-8218-4055dc0530d0";
const err = (e) => JSON.stringify((e.response && e.response.data) || { msg: e.message });
async function enc(secJson, armored, sign) { const k = await openpgp.readKey({ armoredKey: armored }); return openpgp.encrypt({ message: await openpgp.createMessage({ text: secJson }), encryptionKeys: k, signingKeys: sign }); }

(async () => {
  const uid = process.env.PASSBOLT_USER_ID;
  const ks = await provider.ensurePrivateKey();
  const mk = [...(await provider.fetchMetadataKeys()).values()].find((k) => k.metadataKeyType === "shared_key");
  const users = B(await provider.apiRequest({ method: "GET", url: "/users.json", params: { "contain[gpgkey]": 1 } }));
  const keyById = new Map((users || []).map((u) => [u.id, u.gpgkey && u.gpgkey.armored_key]));
  const fols = B(await provider.apiRequest({ method: "GET", url: "/folders.json" }));
  // buscar una carpeta con >=2 usuarios
  let target = null, perms = null;
  for (const f of (fols || []).slice(0, 80)) {
    const full = B(await provider.apiRequest({ method: "GET", url: `/folders/${f.id}.json`, params: { "contain[permissions]": 1 } }));
    const us = (full.permissions || []).filter((p) => String(p.aro) === "User" && keyById.get(p.aro_foreign_key));
    if (us.length >= 2) { target = { id: f.id, name: f.name }; perms = full.permissions; break; }
  }
  if (!target) { console.log("no encontré carpeta con >=2 usuarios"); return; }
  console.log("carpeta:", target.name, "| permisos:", (perms || []).length);

  const secJson = JSON.stringify({ object_type: "PASSBOLT_SECRET_DATA", password: "PruebaDrawShare_" + Date.now(), description: "" });
  const metaJson = JSON.stringify({ object_type: "PASSBOLT_RESOURCE_METADATA", resource_type_id: RT, name: "PRUEBA-DRAW-BORRAR-SHARE", username: "test", uris: ["9.9.9.9"], description: "prueba" });
  const metadata = await openpgp.encrypt({ message: await openpgp.createMessage({ text: metaJson }), encryptionKeys: mk.privateKey.toPublic(), signingKeys: ks.privateKey });

  let resId = "";
  try {
    const created = B(await provider.apiRequest({ method: "POST", url: "/resources.json", data: { resource_type_id: RT, metadata, metadata_key_id: mk.id, metadata_key_type: "shared_key", secrets: [{ data: await enc(secJson, keyById.get(uid), ks.privateKey) }] } }));
    resId = created.id; console.log("1) creado (propietario):", resId);
  } catch (e) { console.log("ERROR crear:", err(e)); return; }

  // permisos: los ACTUALES del recurso (sin is_new) + los usuarios de la carpeta (is_new, con aco).
  const cur = B(await provider.apiRequest({ method: "GET", url: `/resources/${resId}.json`, params: { "contain[permissions]": 1 } }));
  const perm = (cur.permissions || []).map((p) => ({ id: p.id, aro: p.aro, aro_foreign_key: p.aro_foreign_key, aco: p.aco, aco_foreign_key: p.aco_foreign_key, type: p.type }));
  const already = new Set(perm.map((p) => p.aro_foreign_key));
  for (const p of perms) if (String(p.aro) === "User" && !already.has(p.aro_foreign_key) && keyById.get(p.aro_foreign_key)) {
    perm.push({ is_new: true, aro: "User", aro_foreign_key: p.aro_foreign_key, aco: "Resource", aco_foreign_key: resId, type: p.type || 1 });
  }
  try {
    const sim = B(await provider.apiRequest({ method: "POST", url: `/share/simulate/resource/${resId}.json`, data: { permissions: perm } }));
    const added = (sim && sim.changes && sim.changes.added) || [];
    console.log("2) simular → usuarios a cifrar:", added.length);
    const secrets = [];
    for (const a of added) { const id = (a.User && a.User.id) || a.id || a.aro_foreign_key; if (keyById.get(id)) secrets.push({ user_id: id, data: await enc(secJson, keyById.get(id), ks.privateKey) }); }
    await provider.apiRequest({ method: "PUT", url: `/share/resource/${resId}.json`, data: { permissions: perm, secrets } });
    console.log("3) compartido con", perm.length, "usuarios");
    await provider.apiRequest({ method: "POST", url: `/move/resource/${resId}.json`, data: { folder_parent_id: target.id } });
    console.log("4) movido a la carpeta:", target.name);
  } catch (e) { console.log("ERROR compartir/mover:", err(e)); }

  try { await provider.apiRequest({ method: "DELETE", url: `/resources/${resId}.json` }); console.log("5) BORRADO (limpio)"); } catch (e) { console.log("borrar:", err(e), "-> BORRA A MANO", resId); }
})().catch((e) => console.log("FATAL:", e.message));
