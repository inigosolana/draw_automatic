#!/bin/sh
set -eu

DATE="$(date +%F)"
RETENTION_DAYS="${DRAWIO_BACKUP_RETENTION_DAYS:-7}"
LOG_PREFIX="[drawio-backup ${DATE}]"

for db in downloads sites catalog activity security; do
  source_db="/app/data/${db}.sqlite3"
  target_db="/backup/${db}-${DATE}.sqlite3"
  if [ ! -f "${source_db}" ]; then
    echo "${LOG_PREFIX} skip ${db}: source not found"
    continue
  fi
  if sqlite3 "${source_db}" ".backup '${target_db}'"; then
    echo "${LOG_PREFIX} ok ${db}"
  else
    echo "${LOG_PREFIX} error ${db}: backup failed" >&2
  fi
done

deleted="$(find /backup -name '*.sqlite3' -mtime +"${RETENTION_DAYS}" -print -delete | wc -l | tr -d ' ')"
echo "${LOG_PREFIX} retention: removed ${deleted} file(s) older than ${RETENTION_DAYS} day(s)"
