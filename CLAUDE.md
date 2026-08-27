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

## Antes de leer código: usa graft

El repo está indexado con **graft** (`graft build`, ~6 s, 100 % local). Para localizar,
entender o trazar cualquier cosa, consúltalo **antes** de `grep` o `Read`: una consulta
cuesta unos cientos de tokens y ahorra decenas de miles. Medido aquí: un `graft ask
--source` ahorró ~30.400 tokens (88 %).

```bash
graft ask "<pregunta>" --source        # localizar + entender de una vez
graft callers <simbolo> --depth all    # ANTES de cambiar algo compartido
graft grep "<literal>"                 # todas las ocurrencias
```

Detalle en la skill `graft`. **Nunca `--deep`** (manda código de clientes a un LLM
externo). No indexa `templates/*.html`, CSS ni la librería XML: para eso, grep.

## Skills del proyecto

`draw-deploy`, `draw-glpi`, `draw-auditar-ot` y `draw-verificar` (en `.claude/skills/`)
tienen el detalle operativo y los gotchas. **Invócalas en vez de explorar el repo a mano**:
ya sabes cuándo por su descripción, y este fichero no repite lo que hay en ellas.

## Despliegue

El código se **hornea en la imagen**: sin `docker compose build` la web sigue sirviendo lo
viejo. Deploy estándar (tras cambios con efecto en runtime):
```bash
cd /home/ubuntu/draw_automatic && docker compose build drawio-generator && docker compose up -d
```

Contenedor `ausarta-drawio` (+ `ausarta-drawio-redis`, `ausarta-drawio-backup`). Portainer
también despliega desde GitHub (`main`), ver `DESPLIEGUE_INTERNO.md`.

→ **Invoca la skill `draw-deploy`** para desplegar o comprobar si algo está en producción:
tiene la verificación de salud (el `/health` da 403 desde el host, hay que consultarlo por
`docker exec`), el rootfs de solo lectura, la caché de 12 h del JS en el navegador y cómo
ejecutar código contra el contenedor (`PYTHONPATH=/app` y stdin en vez de heredoc, que se
rompe por el quoting sobre ssh).

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

Suite pytest (~362 tests) + pyflakes + ESLint 9 + arneses jsdom que ejecutan el frontend
real sin login. Ojo: `python` no existe en el sistema, hay que usar `.venv/bin/python`.

```bash
.venv/bin/python -m pytest -q
```

→ **Invoca la skill `draw-verificar`** antes de dar un cambio por terminado: tiene los
comandos completos, los golden hashes del layout, el re-export que pyflakes marca y que
**no** hay que borrar, y cómo comprobar que un test falla sin su arreglo.

## Historial reciente (rama mejoras-draws-telefonia-2026-07)

- `a460172` Fix subida GLPI colgada (config JS scope) + red de tests de front.
- `a21aa76` Rendimiento: catálogo GLPI como JS externo cacheable.
- `685113b` Limpieza de imports sin usar en layout/placement engine.

## Documentación relacionada en el repo

`README.md`, `DESPLIEGUE_INTERNO.md`, `VERSIONING.md`, `SECURITY.md`,
`SECURIZACION_FIREWALL.md`, `RESPUESTAS_Y_ERRORES.md`.
