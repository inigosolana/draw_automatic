#!/usr/bin/env bash
# Cron nocturno: refresca las coordenadas de los hosts de Zabbix desde GLPI.
# - Purga los null pegajosos de la caché (reintenta geocodificaciones que fallaron
#   por límite de los geocoders).
# - Ejecuta el barrido incremental (caché-primero): coloca coords a hosts nuevos y
#   completa los que quedaron a nivel provincia.
# Instalar en crontab de ubuntu:  0 3 * * * /home/ubuntu/draw_automatic/scripts/cron_zabbix_coords.sh
set -u
LOG=/home/ubuntu/draw_automatic/scripts/coords_cron.log
CONT=ausarta-drawio
# usa el script horneado en la imagen si existe; si no, la copia del volumen /app/data
SCRIPT=/app/scripts/zabbix_coords.py
docker exec -i "$CONT" test -f "$SCRIPT" 2>/dev/null || SCRIPT=/app/data/zabbix_coords.py
{
  echo "===== $(date -Is) INICIO (script=$SCRIPT) ====="
  docker exec -i "$CONT" python3 - <<'PY'
import json, os
p = "/app/data/geocode_cache.json"
if os.path.exists(p):
    c = json.load(open(p)); k = {kk: v for kk, v in c.items() if v}
    json.dump(k, open(p, "w"))
    print(f"cache purge nulls: {len(c)} -> {len(k)}")
PY
  docker exec -i "$CONT" python3 "$SCRIPT" --apply --sample 0
  echo "===== $(date -Is) FIN ====="
} >> "$LOG" 2>&1
