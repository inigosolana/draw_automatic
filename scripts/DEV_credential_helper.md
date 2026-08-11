# Completar el helper de credenciales Passbolt (2-3 líneas)

Todo el cableado está hecho. Falta **una sola cosa**: en
`scripts/credential_helper.js`, dentro de la función `resolvePassword(ip)`, hay un
bloque marcado `// === DEV: COMPLETAR ===`. Ahí ya tienes:

- `match.resourceId`  → el id del recurso Passbolt del router (resuelto por IP).
- `match.username`    → el usuario RouterOS.
- `provider`          → instancia de `PassboltProvider` de NOP, ya configurada.

## Qué escribir

Mira cómo lo hace NOP en `server.js`, en el endpoint
`app.post("/api/mikrotik/credential/password", ...)` (o la función que use,
p. ej. `resolveMikrotikRouterRuntimeConfig`) — ya recupera el recurso por id con
secreto y lo descifra. Copia esas 2-3 líneas aquí. El patrón típico con el provider es:

```js
// 1) Traer el recurso por id INCLUYENDO el secreto (contain[secret]=1) y
//    normalizarlo con el provider (descifra el secreto con la clave privada):
const resp = await provider.apiRequest({
  method: "GET",
  url: `/resources/${match.resourceId}.json`,
  params: { "contain[secret]": 1 },
});
const raw = resp?.data?.body ?? resp?.data ?? {};
const record = await provider.normalizeResourceRecord(raw, { includeSecret: true });
return {
  username: match.username || record.username || "",
  password: (record.secret && record.secret.password) || "",
};
```

> Nota: usa el MÉTODO que ya funcione en NOP. Si en server.js hay una función de
> alto nivel tipo `resolveMikrotikRouterRuntimeConfig(routerId)` que devuelve
> `{ username, password }`, es aún más simple: expórtala (o replica su cuerpo) y
> llámala aquí con `match` en vez de reimplementar el fetch.

Sustituye el `throw new Error("DEV: ...")` por ese `return`.

## Después

```bash
sudo bash scripts/install_credential_helper.sh
# pega las 2 líneas que imprime (PASSBOLT_HELPER_URL / PASSBOLT_HELPER_TOKEN) en el .env de draw_automatic
docker compose up -d --build drawio-generator
```

Comprobar el sidecar:
```bash
curl -s -XPOST http://127.0.0.1:49600/credential \
  -H "X-Helper-Token: $(grep CRED_HELPER_TOKEN /etc/ausarta-credential-helper.env|cut -d= -f2)" \
  -H 'Content-Type: application/json' -d '{"ip":"193.38.224.84"}'
# -> {"ok":true,"username":"Ausarta","password":"***"}
```

A partir de ahí, el alta en Zabbix rellena `{$ROUTEROS_PASSWORD}` sola.
