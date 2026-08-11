#!/usr/bin/env bash
# Instala el helper de versión RouterOS en el HOST (opción A).
#
# Por qué en el host y no en el contenedor: la app corre en un contenedor Docker
# en una red bridge aislada y NO tiene ruta a los routers. Quien los alcanza es el
# host, por el túnel WireGuard `wg-mikrotik-api` (policy-routing por fwmark 0x8728
# hacia el puerto 8728, origen 10.10.10.3). Es el mismo camino que usa NOP; NO se
# toca NOP: solo se reutiliza el túnel del host.
#
# Qué hace este script (requiere sudo):
#   1. Genera un token compartido y escribe /etc/ausarta-routeros-helper.env
#   2. Instala y arranca el servicio systemd ausarta-routeros-helper
#   3. Abre en ufw el puerto del helper SOLO para la subred del contenedor
#   4. Imprime las 2 líneas que hay que añadir al .env de la app
#
# Uso:  sudo bash scripts/install_routeros_helper.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE=/etc/ausarta-routeros-helper.env
UNIT_SRC="$REPO_DIR/scripts/ausarta-routeros-helper.service"
UNIT_DST=/etc/systemd/system/ausarta-routeros-helper.service
HELPER_PORT="${ROUTEROS_HELPER_PORT:-49500}"
# Subred de la red bridge del contenedor draw_automatic (ajusta si cambia).
DOCKER_SUBNET="${DRAWIO_DOCKER_SUBNET:-172.28.0.0/16}"
DOCKER_GATEWAY="${DRAWIO_DOCKER_GATEWAY:-172.28.0.1}"

if [[ $EUID -ne 0 ]]; then echo "Ejecuta con sudo." >&2; exit 1; fi

# 1) Config + token (solo se genera si no existe, para no invalidar el de la app)
if [[ -f "$ENV_FILE" ]] && grep -q '^ROUTEROS_HELPER_TOKEN=' "$ENV_FILE"; then
  TOKEN="$(grep '^ROUTEROS_HELPER_TOKEN=' "$ENV_FILE" | cut -d= -f2-)"
  echo "Reutilizando token existente de $ENV_FILE"
else
  TOKEN="$(openssl rand -hex 24)"
  umask 077
  cat > "$ENV_FILE" <<EOF
ROUTEROS_HELPER_BIND=0.0.0.0
ROUTEROS_HELPER_PORT=$HELPER_PORT
ROUTEROS_WG_SOURCE_ADDR=10.10.10.3
ROUTEROS_API_PORT=8728
ROUTEROS_TIMEOUT_S=8
ROUTEROS_HELPER_TOKEN=$TOKEN
EOF
  chmod 600 "$ENV_FILE"
  echo "Escrito $ENV_FILE (token nuevo)"
fi

# 2) Servicio systemd
install -m 644 "$UNIT_SRC" "$UNIT_DST"
systemctl daemon-reload
systemctl enable --now ausarta-routeros-helper.service
sleep 1
systemctl --no-pager --lines=5 status ausarta-routeros-helper.service || true

# 3) Regla ufw: solo la subred del contenedor puede llegar al helper
#    (mismo patrón que la regla existente de AgenteEVO para el puerto 8087)
if command -v ufw >/dev/null 2>&1; then
  ufw allow from "$DOCKER_SUBNET" to any port "$HELPER_PORT" proto tcp \
    comment "draw_automatic -> routeros version helper" || true
  echo "Regla ufw añadida para $DOCKER_SUBNET -> $HELPER_PORT/tcp"
fi

# 4) Prueba local + líneas para la app
echo
echo "== Prueba local del helper =="
curl -sS -m 5 "http://127.0.0.1:$HELPER_PORT/health" && echo
echo
echo "== Añade estas 2 líneas al .env de la app (draw_automatic) y redepliega =="
echo "ROUTEROS_HELPER_URL=http://$DOCKER_GATEWAY:$HELPER_PORT"
echo "ROUTEROS_HELPER_TOKEN=$TOKEN"
