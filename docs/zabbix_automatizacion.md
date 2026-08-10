# Automatización de Zabbix (draw_automatic)

Guía de cómo se dan de alta y se mantienen los hosts de Zabbix (fibras, backups,
LTE, chateau), sus macros/plantillas, y las coordenadas del geomapa. Todo lo que
sigue está probado en producción (Zabbix 7.2, servidor `45.13.211.10:181`).

---

## 1. Modelo de host (cómo tiene que quedar)

### Fibra (FTTH)
- **Nombre**: `FTTH_<PROV>_<CLIENTE>_<SEDE>_<LOCALIDAD>_<CALLE>` (mayúsculas, sin acentos, máx 128).
- **Interfaz**: SNMP v2, puerto 161, community `{$SNMP_COMMUNITY}`, IP = **IP pública** del router.
- **Plantillas** (2): `Mikrotik SNMP FIBRA` (10747) **+** RouterOS BGP:
  - RouterOS **v6** → `Template RouterOS BGP` (11208)
  - RouterOS **v7** → `Template RouterOS BGP V7` (13463)
- **3 macros**: `{$SNMP_COMMUNITY}` = `ausarta@conecta`, `{$ROUTEROS_USERNAME}` = `Ausarta`,
  `{$ROUTEROS_PASSWORD}` = contraseña real del router (de Passbolt).
- **Tag**: `PROVEEDOR` = operador (AIRE, MOVISTAR, MASMOVIL, ADAMO, SARENET, EUSKALTEL…).
- **Proxy**: el de su zona (`monitored_by=1` + `proxyid`).
- **Inventario**: `location_lat` / `location_lon` (coordenada real de la sede; `inventory_mode=1`).

> El BGP monitoriza por **API RouterOS** (login con `{$ROUTEROS_PASSWORD}`). Requiere que
> el router tenga la **API activa** (puerto 8728 accesible desde el proxy). Sin API, aunque
> esté todo bien, los ítems BGP dan "Timeout while executing a shell script".

### Backup
- **Nombre**: `BACKUP_<TIPO>_<CLIENTE>_<SEDE>_…` (`KIT`=Mikrotik, `TEL`=Teltonika).
- **Interfaz**: SNMP v2, IP = **IP privada del túnel** (172.x), del router "Creador de Túneles".
- **Plantilla** (1): `Mikrotik SNMP BACKUP` (10758) o `Teltonika SNMP any device` (Teltonika).
- **1 macro**: `{$SNMP_COMMUNITY}`.
- **Tag**: `PROVEEDOR` = operador del backup (KITE por defecto; TELEFONICA, VODAFONE…).
- Comparte **coordenada** con la fibra de la misma sede.

### Chateau / Dual / LTE
- **Chateau**: fibra + backup integrados en 1 host → `Mikrotik SNMP FIBRA CHATEAU` (14924) + BGP V7.
- **Dual**: `15558` + BGP V7. **LTE**: plantillas LTE según modelo.

**Desde la interfaz el alta normal es FIBRA + BACKUP** (tipo `fibra_backup`): crea los dos a la vez.

---

## 2. Alta de hosts

### 2.1 Desde la web (`/zabbix`) — un cliente
Sólo habilitado para `inigo.solana`, `alberto.ferez`, `marcos.medina`.
1. Introducir la OT o elegir cliente/sede. La app **autorrellena**:
   - IP + versión (v6/v7) → **NOP** (`/routers`).
   - Proveedor + si tiene backup → **Yeastar Unificado** (`/services`).
   - Provincia / sede / localidad / calle → **GLPI**.
   - IP privada del backup → **router de túneles** (`/tunnel-ip`).
   - Contraseña → **Passbolt** (`/credential`).
2. Elegir tipo (**fibra + backup** por defecto) y crear. Al crear:
   - Se enlazan plantillas + macros + tag + proxy de la zona.
   - Se **geocodifica** la dirección de GLPI y se escriben las coordenadas (`generator/geocode.py`).
   - La Description recoge quién lo subió (nombre GLPI del técnico) y la fecha.

### 2.2 Alta masiva — `scripts/alta_masiva_zabbix.py`
CSV de entrada: `cif,cliente,fiber_ip` (fiber_ip opcional). Autodetecta todo como la web.
```bash
# dry-run (no escribe): muestra qué crearía y qué salta y por qué
docker exec -e ALTA_CSV=/app/data/pendientes.csv -i ausarta-drawio \
  python3 /app/data/alta_masiva_zabbix.py
# crear de verdad
docker exec -e ALTA_CSV=/app/data/pendientes.csv -i ausarta-drawio \
  python3 /app/data/alta_masiva_zabbix.py --create --by "Nombre Tecnico"
```
Es **idempotente**: salta hosts que ya existen o a los que les faltan datos
(sin IP en NOP no se crea la fibra; sin IP de túnel el backup queda pendiente).

### 2.3 Fibras contratadas que faltan en Zabbix — `scripts/yeastar_missing.py`
Cruza las fibras **activas en Yeastar** con los FTTH de Zabbix (emparejamiento por
nombre con ponderación IDF, tolerante a acentos) y saca las **no creadas** +
si tienen backup. Genera `/app/data/fibras_no_creadas.csv`.
```bash
docker exec -i ausarta-drawio python3 /app/data/yeastar_missing.py
```

---

## 3. Coordenadas del geomapa — `scripts/zabbix_coords.py`

**Problema que resolvió**: las coordenadas eran el centroide de la capital de
provincia (cientos de hosts apilados en Bilbao/Madrid…). Ahora cada sede tiene su
punto real.

**Cómo funciona**: empareja cada host FTTH/BACKUP/LTE con su entidad **GLPI**
(nombre cliente/sede con IDF + join fuerte por "Sede N"; la provincia del grupo
Zabbix sólo desempata). Resuelve la coordenada:
1. `latitude/longitude` de GLPI si existe.
2. geocodificación de `calle, localidad` (nivel calle) → si no, `localidad, provincia`
   (municipio). Motores: **Photon** (validado país=ES + bbox) y **Nominatim**
   (`countrycodes=es`) de reserva. **Nunca escribe fuera de España.**

Es **incremental** (escribe por lotes, aguanta cortes) y **caché-primero**
(`/app/data/geocode_cache.json`). Fibra y backup de la misma sede comparten punto.
```bash
docker exec -i ausarta-drawio python3 /app/data/zabbix_coords.py            # DRY-RUN
docker exec -i ausarta-drawio python3 /app/data/zabbix_coords.py --apply
docker exec -i ausarta-drawio python3 /app/data/zabbix_coords.py --apply --only-missing
docker exec -i ausarta-drawio python3 /app/data/zabbix_coords.py --upgrade --apply  # sube a nivel calle
```
> **Gotcha**: los `null` de la caché son *pegajosos* (no se reintentan). Si los
> geocoders estaban caídos, purgar los null antes de re-geocodificar:
> `python3 -c "import json;p='/app/data/geocode_cache.json';c=json.load(open(p));json.dump({k:v for k,v in c.items() if v},open(p,'w'))"`

**Auxiliares**:
- `scripts/fix_sea.py` — recoloca en su municipio los hosts a >35 km (mar / error de signo / homónimo).
- `scripts/fix_france.py` — reverse-geocoding por país en la franja fronteriza; recoloca los que caen en Francia.

**Cron nocturno** (`scripts/cron_zabbix_coords.sh`, en crontab de `ubuntu` a las 03:00):
purga null + ejecuta el barrido → completa lo que falte y coge hosts nuevos.
Log en `scripts/coords_cron.log`.

---

## 4. Plantilla BGP + macros en fibras mal configuradas

Muchas FTTH tenían **1 sola macro** (`{$SNMP_COMMUNITY}`) y **sin plantilla BGP**
→ no monitorizaban BGP. **No era la contraseña**, era la config.

1. `scripts/fix_ftth_macros.py --apply` → pone `{$ROUTEROS_USERNAME}` + `{$ROUTEROS_PASSWORD}`
   (contraseña real de Passbolt) a las FTTH con <3 macros.
2. `scripts/link_bgp.py --apply` → sondea la API de cada router, enlaza la plantilla
   BGP correcta (v6/v7) a los que responden, y vuelca los que tienen la **API caída**
   en `/app/data/api_caida.csv` (motivo, host, ip, provincia, estado).
```bash
docker exec -i ausarta-drawio python3 /app/data/fix_ftth_macros.py --apply
docker exec -i ausarta-drawio python3 /app/data/link_bgp.py --apply
```
Los routers con **API caída** no monitorizarán BGP hasta que se active la API
(RouterOS: servicio `api` en puerto 8728, con acceso desde el proxy/monitorización).

---

## 5. Fuentes de datos y helpers

| Dato | Fuente | Cómo se llega |
|---|---|---|
| IP pública + versión router | NOP (Network Operations Platform) | sidecar `/routers` (49600) |
| Proveedor + tiene backup | Yeastar Unificado (postgres `yeastar_unificado`) | sidecar `/services` |
| Sede / localidad / calle / coords GLPI | GLPI | `GlpiClient` |
| IP privada del backup | Router "Creador de Túneles" (`/ppp/secret`, `*_BU`) | sidecar `/tunnel-ip` |
| Contraseña del router | Passbolt (`passboltnoc.ausarta.net`) | sidecar `/credential` |
| Versión v6/v7 (login API) | router RouterOS (8728) | helper de versión (49500) |

**Sidecars del host** (systemd, corren como `ubuntu`, la app los alcanza por
`172.28.0.1:<puerto>`):
- `ausarta-credential-helper` (Node, 49600): `/credential`, `/routers`, `/services`, `/tunnel-ip`.
  Reutiliza el `passbolt-provider` de NOP (OpenPGP + JWT).
- `ausarta-routeros-helper` (Python, 49500): `/version` (login API → versión, board, v6/v7).

Variables en `.env` de draw_automatic: `PASSBOLT_HELPER_URL`/`_TOKEN`,
`ROUTEROS_HELPER_URL`/`_TOKEN`, `ZABBIX_BASE_URL`.

---

## 6. Notas de operación

- **Despliegue**: el código va horneado en la imagen (`COPY`). Un cambio de código
  necesita `docker compose up -d --build drawio-generator`. El rootfs del contenedor
  es **read-only** salvo `/app/data`; por eso los scripts de mantenimiento se copian
  y ejecutan desde `/app/data/` (sobreviven a reinicios, no a un rebuild → subirlos
  también al repo `scripts/`).
- **Provincias**: GLPI usa variantes (Vizcaya/Bizkaia, A Coruña/Coruña, Jaen/Jaén,
  Leon/León); `_normalize_province` las unifica.
- **Grupos Zabbix**: `Routers Fibra <Prov>`, `Routers Backup <Prov>`, `Routers LTE <Prov>`.
- **Encoding Yeastar**: algunos nombres tienen el acento corrupto (`?`); los matchers
  lo toleran por prefijo, pero conviene ojear los que lleven `?`.
