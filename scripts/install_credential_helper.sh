#!/usr/bin/env bash
# Instala el helper de credenciales Passbolt (opción B) en el HOST.
# Reutiliza el passbolt-provider.js de NOP. Requiere sudo.
#
# ANTES de que funcione, un dev debe completar la llamada de descifrado marcada
# en scripts/credential_helper.js (bloque "DEV: COMPLETAR"). El resto queda listo.
#
# Uso:  sudo bash scripts/install_credential_helper.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
NOP_DIR="${NOP_DIR:-/home/ubuntu/Network Operations Platform Marcos}"
ENV_FILE=/etc/ausarta-credential-helper.env
UNIT_DST=/etc/systemd/system/ausarta-credential-helper.service
PORT="${CRED_HELPER_PORT:-49600}"
DOCKER_SUBNET="${DRAWIO_DOCKER_SUBNET:-172.28.0.0/16}"
DOCKER_GATEWAY="${DRAWIO_DOCKER_GATEWAY:-172.28.0.1}"
NODE_BIN="${NODE_BIN:-$(command -v node || echo /home/ubuntu/.nvm/versions/node/v22.22.2/bin/node)}"

if [[ $EUID -ne 0 ]]; then echo "Ejecuta con sudo." >&2; exit 1; fi

# 1) Config + token (reutiliza si ya existe)
if [[ -f "$ENV_FILE" ]] && grep -q '^CRED_HELPER_TOKEN=' "$ENV_FILE"; then
  TOKEN="$(grep '^CRED_HELPER_TOKEN=' "$ENV_FILE" | cut -d= -f2-)"
else
  TOKEN="$(openssl rand -hex 24)"
  umask 077
  cat > "$ENV_FILE" <<EOF
CRED_HELPER_BIND=0.0.0.0
CRED_HELPER_PORT=$PORT
CRED_HELPER_TOKEN=$TOKEN
NOP_DIR=$NOP_DIR
EOF
  chmod 600 "$ENV_FILE"
fi

# 2) Asegura dotenv para el sidecar (usa el node_modules de NOP)
if [[ ! -d "$NOP_DIR/node_modules/dotenv" ]]; then
  echo "AVISO: falta 'dotenv' en $NOP_DIR/node_modules; instálalo o exporta las PASSBOLT_* en $ENV_FILE" >&2
fi

# 3) systemd (corre como ubuntu, que puede leer las llaves de NOP)
cat > "$UNIT_DST" <<EOF
[Unit]
Description=Ausarta credential helper (Passbolt via NOP) para alta Zabbix
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
EnvironmentFile=$ENV_FILE
WorkingDirectory=$NOP_DIR
ExecStart=$NODE_BIN $REPO_DIR/scripts/credential_helper.js
Restart=on-failure
RestartSec=3
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now ausarta-credential-helper.service
sleep 1
systemctl --no-pager --lines=5 status ausarta-credential-helper.service || true

# 4) ufw: solo la subred del contenedor
if command -v ufw >/dev/null 2>&1; then
  ufw allow from "$DOCKER_SUBNET" to any port "$PORT" proto tcp \
    comment "draw_automatic -> credential helper" || true
fi

echo
echo "== Añade estas 2 líneas al .env de draw_automatic y redepliega =="
echo "PASSBOLT_HELPER_URL=http://$DOCKER_GATEWAY:$PORT"
echo "PASSBOLT_HELPER_TOKEN=$TOKEN"
echo
echo "RECUERDA: completar el bloque 'DEV: COMPLETAR' en scripts/credential_helper.js."
