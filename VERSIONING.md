# Versionado de draw_automatic

Este proyecto usa **Git** con etiquetas **semver** (`vMAJOR.MINOR.PATCH`) y, en despliegues a producción, etiquetas de **fecha** (`vAAAA.MM.DD`).

Repositorio remoto: https://github.com/inigosolana/draw_automatic

## Versiones publicadas

| Versión | Commit | Contenido principal |
|---------|--------|---------------------|
| **v1.5.0** / v2026.06.19 | `01c3224` | Import OT AIRE + extensiones VoIP, CSP completo, endpoints blueprint explícitos, validación librería |
| **v1.4.0** | `fdb9161` | Varios DECT compartiendo base, import extensiones, switch telefonía opcional |
| **v1.3.0** | `7992562` | Mapeo MásMóvil fibra+backup, UI móvil post-generación |
| **v1.2.0** | `274d74e` | Varios diagramas GLPI por sede, tracking de subidas |
| **v1.1.0** | `c171264` | Librería externa, panel admin, backups SQLite, CI |
| **v1.0.0** | `735df25` | Endurecimiento para Internet (`draw.ausarta.net`) |

El número en `VERSION` corresponde a la última versión estable desplegada.

## Comandos habituales

```bash
# Ver historial y etiquetas
git log --oneline --decorate -15
git tag -l 'v*'

# Inspeccionar una versión (solo lectura)
git checkout v1.4.0

# Volver a la rama principal
git checkout main

# Desplegar una versión concreta en el servidor
git fetch origin --tags
git checkout v1.4.0
docker compose -f docker-compose.host-nginx.yml build drawio-generator
docker compose -f docker-compose.host-nginx.yml up -d drawio-generator
git checkout main
```

## Crear una versión nueva

Tras cambios probados en local y en prod:

```bash
git add -A
git status   # comprobar que no entran .env, data/*.sqlite3 ni library/*.xml
git commit -m "Descripción del cambio."
git tag -a v1.6.0 -m "Resumen de la release."
git push origin main --tags
echo "1.6.0" > VERSION
git add VERSION && git commit -m "Bump VERSION to 1.6.0." && git push origin main
```

Opcional: etiqueta de fecha en el mismo commit de release (`git tag -a v2026.07.01 -m "..."`).

## Qué no se versiona en Git

Según `.gitignore`:

- `.env` — secretos y tokens
- `data/*.sqlite3` — catálogo, descargas, actividad, logs
- `library/*.xml` — librería de iconos (~12 MB); guardar copia aparte

Tras restaurar una versión antigua, copiar de nuevo la librería real a `library/libreria_Ausarta_JUN_2026.xml` si hace falta.
