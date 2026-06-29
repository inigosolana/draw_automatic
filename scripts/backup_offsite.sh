#!/usr/bin/env bash
#
# Copia las copias de seguridad de draw_automatic FUERA del servidor, para que
# un fallo de disco/host no se lleve a la vez los datos y su backup.
#
# Empaqueta el contenido del volumen draw_automatic_drawio_backup en un .tgz y
# lo envía al destino que configures en la variable de entorno DRAWIO_OFFSITE_DEST.
#
# Configura el destino (uno de):
#   DRAWIO_OFFSITE_DEST="user@host:/ruta/backups"     -> usa rsync sobre SSH
#   DRAWIO_OFFSITE_DEST="s3://bucket/prefijo"          -> usa aws s3 cp
#
# Pensado para ejecutarse por cron del HOST (las claves SSH/AWS viven en el host,
# nunca en el contenedor). Ejemplo de cron diario a las 03:30:
#   30 3 * * * DRAWIO_OFFSITE_DEST="user@nas:/vol/backups/drawio" /home/ubuntu/draw_automatic/scripts/backup_offsite.sh >> /var/log/drawio-offsite.log 2>&1
set -euo pipefail

BACKUP_VOL="draw_automatic_drawio_backup"
HELPER_IMAGE="alpine:3.19"
STAMP="$(date +%Y%m%d-%H%M%S)"
WORKDIR="$(mktemp -d)"
ARCHIVE="${WORKDIR}/drawio-backup-${STAMP}.tgz"
trap 'rm -rf "${WORKDIR}"' EXIT

DEST="${DRAWIO_OFFSITE_DEST:-}"
if [ -z "${DEST}" ]; then
  echo "ERROR: define DRAWIO_OFFSITE_DEST (user@host:/ruta  o  s3://bucket/prefijo)." >&2
  exit 2
fi

echo "==> Empaquetando ${BACKUP_VOL} -> ${ARCHIVE}…"
docker run --rm -v "${BACKUP_VOL}:/backup:ro" -v "${WORKDIR}:/out" "${HELPER_IMAGE}" \
  tar czf "/out/$(basename "${ARCHIVE}")" -C /backup .

case "${DEST}" in
  s3://*)
    echo "==> Subiendo a ${DEST} con aws s3…"
    aws s3 cp "${ARCHIVE}" "${DEST%/}/$(basename "${ARCHIVE}")"
    ;;
  *)
    echo "==> Sincronizando a ${DEST} con rsync sobre SSH…"
    rsync -avz -e ssh "${ARCHIVE}" "${DEST%/}/"
    ;;
esac

echo "==> Copia off-host completada: $(basename "${ARCHIVE}")"
