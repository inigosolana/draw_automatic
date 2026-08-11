"use strict";
/*
 * PRUEBA de creación de recursos en Passbolt v5 (reutiliza el passbolt-provider de NOP).
 *
 * Crea N recursos de PRUEBA (contraseñas FALSAS, nombre PRUEBA-DRAW-v5-*) en el espacio
 * personal del usuario API, para VALIDAR el flujo de escritura v5 (metadatos + secreto
 * cifrados) contra vuestro servidor. No toca carpetas de clientes.
 *
 * Correr EN EL HOST (donde están las llaves de NOP):
 *   node /home/ubuntu/draw_automatic/scripts/passbolt_create_test.js
 *
 * Si el servidor rechaza por el formato exacto de metadata/secret, el script imprime el
 * error del servidor para ajustar object_type / estructura y reintentar. Borra las pruebas
 * desde la UI de Passbolt cuando termines de validar.
 */
const fs = require("fs"), path = require("path");
const NOP_DIR = process.env.NOP_DIR || "/home/ubuntu/Network Operations Platform Marcos";
function loadEnvFile(p) {
  try {
    for (const line of fs.readFileSync(p, "utf8").split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
      if (!m) continue;
      let v = m[2];
      if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) v = v.slice(1, -1);
      if (process.env[m[1]] === undefined) process.env[m[1]] = v;
    }
  } catch (e) { /* usa el entorno presente */ }
}
loadEnvFile(path.join(NOP_DIR, ".env"));
const openpgp = require(path.join(NOP_DIR, "node_modules", "openpgp"));
const { PassboltProvider } = require(path.join(NOP_DIR, "passbolt-provider.js"));
const provider = new PassboltProvider({
  baseUrl: process.env.PASSBOLT_BASE_URL, userId: process.env.PASSBOLT_USER_ID,
  privateKeyPath: process.env.PASSBOLT_PRIVATE_KEY_PATH,
  privateKeyPassphrase: process.env.PASSBOLT_PRIVATE_KEY_PASSPHRASE,
  serverFingerprint: process.env.PASSBOLT_SERVER_FINGERPRINT,
});
function body(r) { return (r && r.data && r.data.body) || (r && r.data) || r; }
const RT = "dd1f723d-0d1e-513f-8218-4055dc0530d0"; // v5-default
const N = Number(process.env.PRUEBAS_N || 3);

(async () => {
  const uid = process.env.PASSBOLT_USER_ID;
  const ks = await provider.ensurePrivateKey();
  const userPriv = ks.privateKey;
  const mkMap = await provider.fetchMetadataKeys();
  const shared = [...mkMap.values()].find((k) => k.metadataKeyType === "shared_key") || [...mkMap.values()][0];
  if (!shared) { console.log("No hay metadata key compartida disponible."); return; }
  const mkPub = shared.privateKey.toPublic();
  const me = body(await provider.apiRequest({ method: "GET", url: `/users/${uid}.json`, params: { "contain[gpgkey]": 1 } }));
  const ownerPub = await openpgp.readKey({ armoredKey: me.gpgkey.armored_key });
  console.log(`metadata_key_id=${shared.id} · creando ${N} recursos de prueba...`);
  const created = [];
  for (let i = 1; i <= N; i++) {
    const pw = "PruebaDraw_v5_" + i + "_" + Date.now();
    const metaJson = JSON.stringify({ object_type: "PASSBOLT_RESOURCE_METADATA", resource_type_id: RT,
      name: "PRUEBA-DRAW-v5-" + i, username: "test-draw", uris: ["router-prueba-" + i], description: "prueba draw_automatic" });
    const secJson = JSON.stringify({ object_type: "PASSBOLT_SECRET_DATA", password: pw, description: "prueba draw_automatic" });
    const metadata = await openpgp.encrypt({ message: await openpgp.createMessage({ text: metaJson }), encryptionKeys: mkPub, signingKeys: userPriv });
    const secret = await openpgp.encrypt({ message: await openpgp.createMessage({ text: secJson }), encryptionKeys: ownerPub, signingKeys: userPriv });
    try {
      const res = body(await provider.apiRequest({ method: "POST", url: "/resources.json", data: {
        resource_type_id: RT, metadata, metadata_key_id: shared.id, metadata_key_type: "shared_key",
        secrets: [{ data: secret }],
      } }));
      created.push(res && res.id);
      console.log(`  CREADO #${i}: id=${res && res.id}`);
    } catch (e) {
      const detail = (e.response && JSON.stringify(e.response.data)) || e.message;
      console.log(`  ERROR #${i}: ${String(detail).slice(0, 400)}`);
    }
  }
  console.log("\nIDs creados:", created.filter(Boolean).join(", ") || "(ninguno)");
})().catch((e) => console.log("FATAL:", e.message));
