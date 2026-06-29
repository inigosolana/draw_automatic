#!/usr/bin/env bash
#
# Restaura las copias SQLite de draw_automatic desde el volumen de backup
# (draw_automatic_drawio_backup) al volumen de datos (draw_automatic_drawio_data).
#
# Uso:
#   scripts/restore_backup.sh            # restaura la copia MÁS RECIENTE de cada BD
#   scripts/restore_backup.sh 2026-06-28 # restaura la copia de esa fecha
#   scripts/restore_backup.sh --list     # solo lista las copias disponibles
#
# Para la app mientras restaura y la vuelve a arrancar al terminar.
set -euo pipefail

DATA_VOL="draw_automatic_drawio_data"
BACKUP_VOL="draw_automatic_drawio_backup"
DBS="downloads sites catalog activity security"
HELPER_IMAGE="alpine:3.19"

cd "$(dirname "$0")/.."

if [ "${1:-}" = "--list" ]; then
  echo "Copias disponibles en ${BACKUP_VOL}:"
  docker run --rm -v "${BACKUP_VOL}:/backup:ro" "${HELPER_IMAGE}" \
    sh -c "ls -1 /backup/*.sqlite3 2>/dev/null | sort" || echo "(ninguna)"
  exit 0
fi

DATE_FILTER="${1:-}"
echo "==> Parando la app (los datos no deben cambiar durante la restauración)…"
docker compose stop drawio-generator

echo "==> Restaurando desde ${BACKUP_VOL} -> ${DATA_VOL} (fecha: ${DATE_FILTER:-última})…"
docker run --rm \
  -v "${BACKUP_VOL}:/backup:ro" \
  -v "${DATA_VOL}:/data" \
  -e "DBS=${DBS}" \
  -e "DATE_FILTER=${DATE_FILTER}" \
  "${HELPER_IMAGE}" sh -eu -c '
    for db in $DBS; do
      if [ -n "$DATE_FILTER" ]; then
        src="/backup/${db}-${DATE_FILTER}.sqlite3"
      else
        src="$(ls -1 /backup/${db}-*.sqlite3 2>/dev/null | sort | tail -n1 || true)"
      fi
      if [ -z "${src:-}" ] || [ ! -f "$src" ]; then
        echo "  skip ${db}: no hay copia"
        continue
      fi
      cp "$src" "/data/${db}.sqlite3"
      echo "  restaurado ${db} <- $(basename "$src")"
    done
  '

echo "==> Arrancando la app…"
docker compose start drawio-generator
echo "==> Restauración completada."
