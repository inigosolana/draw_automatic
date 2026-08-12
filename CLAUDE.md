# CLAUDE.md — draw_automatic (Ausarta Draw.io)

Guía para sesiones de Claude Code. Léela antes de tocar nada.

## Qué es

App Flask que genera diagramas de red `.drawio` para instalaciones de telecomunicaciones
de AUSARTA e integra con GLPI (catálogo de clientes/sedes, publicación de diagramas),
más pestañas de Zabbix y Passbolt. Sirve como interfaz web interna en `https://draw.ausarta.net`.

Versión actual: ver fichero `VERSION` (1.5.0). CLI heredada en `app.py` sigue funcionando.

## DÓNDE VIVE EL CÓDIGO (importante)

- **El repo solo existe en el servidor remoto**: `NOP_inigo:/home/ubuntu/draw_automatic`
  (acceso por `ssh NOP_inigo`). NO hay copia local del repo.
- El directorio de trabajo local `D:\DrawsClientes` contiene **carpetas de clientes**
  (drawios de ejemplo), NO es el repositorio. No busques el código ahí.
- GitHub: `https://github.com/inigosolana/draw_automatic`.
- Rama de trabajo actual: `mejoras-draws-telefonia-2026-07` (no `main`).

## Restricciones permanentes (NO negociables)

1. **NO tocar Zabbix.** La página/integración Zabbix la mantiene otro agente. No editar
   `zabbix_*.py`, `web/blueprints/zabbix.py`, `static/js/zabbix-form.js`, plantillas zabbix,
   ni la lógica de subida de Zabbix salvo petición explícita del usuario para eso.
2. **NO crear clientes ni sedes en GLPI.** Usar únicamente los que ya existen en el catálogo.
3. **NO publicar en GLPI sin permiso explícito.** Generar/previsualizar diagramas está OK;
   subir/publicar a GLPI requiere un "sí" claro del usuario en cada caso.
4. **NO introducir credenciales/contraseñas.** Está prohibido. Las credenciales GLPI solo
   se leen de variables de entorno; nunca en el repo.

## Despliegue

El contenedor tiene **rootfs de solo lectura**; `docker cp` a `/app` falla.

Deploy estándar (tras cambios con efecto en runtime):
```bash
cd /home/ubuntu/draw_automatic && docker compose build drawio-generator && docker compose up -d
```
Comprobar salud: `curl -s http://127.0.0.1:8000/health` → `{"status":"ok"}`

- Contenedor: `ausarta-drawio` (+ `ausarta-drawio-redis`, `ausarta-drawio-backup`).
- Cambios solo cosméticos (p.ej. quitar imports sin usar) no requieren rebuild.
- Portainer también puede desplegar desde GitHub (`main`), ver `DESPLIEGUE_INTERNO.md`,
  pero el flujo habitual en esta rama es el `docker compose build/up` de arriba.

### Servir/verificar código en el contenedor
- Para probar código nuevo sin rebuild, usar el volumen escribible: staging en
  `/app/data/gp/generator`. Ejecutar scripts vía
  `docker exec -i ausarta-drawio sh -c "cd /app && python -"` usa el código **baked/desplegado**.
- Al correr scripts sueltos por ssh: `PYTHONPATH=/home/ubuntu/draw_automatic` (si no,
  `ModuleNotFoundError: app_factory`).

### Gotcha de shell (ssh)
Los heredocs / python inline con comillas o regex sobre ssh se rompen por el quoting.
Preferir: escribir el script con la tool Write al scratchpad y luego `scp` al remoto.

## Producción: gunicorn + nginx

- gunicorn: 3 workers, 2 threads, `--timeout 120`.
- nginx: `gzip on` (html gzipeado por defecto), `client_max_body_size 20M`.
- `SEND_FILE_MAX_AGE_DEFAULT=43200` (12h) en prod.
- Acceso filtrado por IP (`allow`/`deny all`) + HTTPS autofirmado. No exponer 8000 a Internet.

## Arquitectura

### Pipeline de layout (generator/)
- `layout_engine.py` — `build_layout` orquesta: `_place_expanders`, `_separate_floors`,
  `_relocate_unfloored_overlaps`, `_reroute_lower_cables_through_gaps`, `_compute_floors`,
  `_reflow_waypoints_after_shift`.
  - `_place_expanders` corre ANTES del reroute de cables (para que los cables esquiven
    expanders). Usa fit-check: solo dibuja el expander si no solapa; si no cabe, lo omite.
    Constantes: EX_W=88, EX_H=118, GAP=12, RIGHT_LIMIT=PAGE_RIGHT+140.
  - `_relocate_unfloored_overlaps` desplaza en bloque rígido los dispositivos sin planta
    que colisionarían con las bandas de planta empujadas hacia abajo.
- `placement_engine.py`, `drawio_writer.py`, `cable_routing.py`, `geometry.py`.
- Catálogo GLPI: `catalog_cache.py` (CatalogStore, TTL 300s).

### Web (web/)
- `blueprints/`: home, auth, diagrams, glpi_import, admin, zabbix (¡no tocar!).
- `services/`: glpi_catalog (`load_glpi_catalog` cache 300s + `apply_saved_addresses`
  por request + `build_customer_catalog` en miss; `glpi_catalog_asset_url`), diagram_publish,
  upload_service, export, stats.
- Auth: login con credenciales GLPI, sin guardar contraseña. Admins vía `DRAWIO_ADMIN_USERS`.

### Frontend (static/js/)
- Todos los JS son IIFE, `sourceType: "script"` (NO módulos). Sin bundler.
- Config de página inyectada como `<script type="application/json">`:
  `drawio-page-config`, `diagram-glpi-config`, `upload-glpi-config`.
- El catálogo GLPI (~964 KB) NO va inline: se sirve como script externo cacheado
  `/assets/glpi-catalog.js` que define `window.__GLPI_CATALOG` (endpoint en
  `web/blueprints/glpi_import.py`, URL versionada por hash en `glpi_catalog_asset_url`).
  Los consumidores leen `window.__GLPI_CATALOG || <fallback>`. Esto aligeró las páginas 40-200x.
- Consumidores del catálogo: glpi-select.js, diagram-glpi-cascade.js, upload-glpi-form.js.
- **Gotcha JS**: cada IIFE tiene su propio scope. Si un segundo IIFE necesita la config,
  debe re-leerla localmente del `<script application/json>`, NO referenciar variables del
  primer IIFE (esto causó el bug "config is not defined" que colgaba la subida a GLPI).

## Tests y análisis estático

- Suite pytest (~332 tests): `python -m pytest` (o `-m unittest` para los antiguos).
- Golden hashes en `test_layout_golden.py` excluyen `node.meta`.
- Frontend jsdom (tests/frontend/): harnesses que renderizan páginas y simulan interacción
  (`creation_form_harness.js`, `upload_form_harness.js`, `zabbix_form_harness.js`).
  Node/ESLint/jsdom instalados en `tests/frontend/node_modules` (vía npm).
- **ESLint 9** flat config (`eslint.config.mjs`) con `no-undef` (error) + recommended.
  Corre desde `test_frontend_eslint.py` (se salta si falta node). Caza la clase de bug
  "variable no definida" en JS. Ignora `*.min.js` y `chart-*.js`.
- **pyflakes** para Python: sin nombres no definidos en producción.
- Al limpiar imports "sin usar": VERIFICAR con grep que no sean re-exports usados por tests.
  Ejemplo: `comms_client.normalize_work_order_payload` parece sin usar pero lo usan
  `test_offer_import.py` y `test_crm_import.py` — NO borrar.

## Historial reciente (rama mejoras-draws-telefonia-2026-07)

- `a460172` Fix subida GLPI colgada (config JS scope) + red de tests de front.
- `a21aa76` Rendimiento: catálogo GLPI como JS externo cacheable.
- `685113b` Limpieza de imports sin usar en layout/placement engine.

## Documentación relacionada en el repo

`README.md`, `DESPLIEGUE_INTERNO.md`, `VERSIONING.md`, `SECURITY.md`,
`SECURIZACION_FIREWALL.md`, `RESPUESTAS_Y_ERRORES.md`.
