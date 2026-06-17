#!/bin/bash

# Script de Securización Automática
# Ausarta Draw.io + Portainer
# 
# Este script:
# 1. Configura un firewall restrictivo (UFW)
# 2. Instala Fail2Ban para proteger SSH
# 3. Configura Portainer en modo seguro
# 4. Libera el puerto 80 para la aplicación
#
# IMPORTANTE: Lee todo antes de ejecutar

set -e  # Salir si hay error

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}Securización Automática${NC}"
echo -e "${GREEN}======================================${NC}"
echo ""

# Verificar que se ejecuta como root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}Este script debe ejecutarse como root (sudo)${NC}" 
   exit 1
fi

# Preguntar puerto SSH (por si no es el 22)
read -p "¿Qué puerto usas para SSH? [22]: " SSH_PORT
SSH_PORT=${SSH_PORT:-22}

# Preguntar IP pública para Portainer (opcional)
echo ""
echo -e "${YELLOW}Opción 1 (Recomendado): Acceder a Portainer solo via túnel SSH${NC}"
echo -e "${YELLOW}Opción 2: Permitir acceso desde tu IP específica${NC}"
echo ""
read -p "¿Quieres permitir acceso a Portainer desde una IP específica? (s/N): " ALLOW_PORTAINER_IP

PORTAINER_IP=""
if [[ "$ALLOW_PORTAINER_IP" =~ ^[Ss]$ ]]; then
    echo ""
    echo -e "${YELLOW}Tu IP pública actual:${NC}"
    curl -s https://ifconfig.me
    echo ""
    read -p "Ingresa tu IP pública (o presiona Enter para usar la detectada): " PORTAINER_IP
    if [ -z "$PORTAINER_IP" ]; then
        PORTAINER_IP=$(curl -s https://ifconfig.me)
    fi
    echo -e "${GREEN}Portainer será accesible solo desde: $PORTAINER_IP${NC}"
else
    echo -e "${GREEN}Portainer solo será accesible via túnel SSH (más seguro)${NC}"
fi

echo ""
echo -e "${YELLOW}Presiona Enter para continuar o Ctrl+C para cancelar...${NC}"
read

# ==========================================
# 1. INSTALAR UFW
# ==========================================
echo ""
echo -e "${GREEN}[1/6] Instalando UFW (Firewall)...${NC}"
apt update -qq
apt install -y ufw

# Reset UFW (limpiar reglas previas)
ufw --force reset

# Configurar políticas por defecto
ufw default deny incoming
ufw default allow outgoing

# ==========================================
# 2. CONFIGURAR REGLAS DE FIREWALL
# ==========================================
echo -e "${GREEN}[2/6] Configurando reglas de firewall...${NC}"

# Permitir SSH
ufw allow ${SSH_PORT}/tcp comment 'SSH'

# Permitir HTTPS (aplicación web)
ufw allow 443/tcp comment 'HTTPS - Ausarta Draw.io'

# Opcional: HTTP (si quieres permitirlo desde internet)
# Por ahora lo dejamos cerrado desde internet, nginx lo usa internamente
# ufw allow 80/tcp comment 'HTTP - Redirect to HTTPS'

# Portainer: Solo si se especificó IP
if [ ! -z "$PORTAINER_IP" ]; then
    ufw allow from $PORTAINER_IP to any port 9443 proto tcp comment 'Portainer - Restricted IP'
fi

# Activar firewall
ufw --force enable

echo -e "${GREEN}Firewall activado${NC}"
ufw status verbose

# ==========================================
# 3. INSTALAR FAIL2BAN
# ==========================================
echo ""
echo -e "${GREEN}[3/6] Instalando Fail2Ban (protección SSH)...${NC}"
apt install -y fail2ban

# Configurar Fail2Ban
cat > /etc/fail2ban/jail.local <<EOF
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true
port = ${SSH_PORT}
logpath = %(sshd_log)s
backend = %(sshd_backend)s
EOF

systemctl enable fail2ban
systemctl restart fail2ban

echo -e "${GREEN}Fail2Ban configurado${NC}"

# ==========================================
# 4. DETENER SERVICIOS EN PUERTO 80
# ==========================================
echo ""
echo -e "${GREEN}[4/6] Liberando puerto 80...${NC}"

# Detener Apache si existe
if systemctl is-active --quiet apache2; then
    echo "Deteniendo Apache..."
    systemctl stop apache2
    systemctl disable apache2
    echo -e "${GREEN}Apache detenido${NC}"
fi

# Detener Nginx si existe (no el de Docker)
if systemctl is-active --quiet nginx; then
    echo "Deteniendo Nginx del sistema..."
    systemctl stop nginx
    systemctl disable nginx
    echo -e "${GREEN}Nginx detenido${NC}"
fi

# Verificar puerto 80
if lsof -i :80 > /dev/null 2>&1; then
    echo -e "${YELLOW}Advertencia: El puerto 80 todavía está en uso${NC}"
    echo "Procesos usando puerto 80:"
    lsof -i :80
else
    echo -e "${GREEN}Puerto 80 libre${NC}"
fi

# ==========================================
# 5. SECURIZAR PORTAINER
# ==========================================
echo ""
echo -e "${GREEN}[5/6] Configurando Portainer en modo seguro...${NC}"

# Detener Portainer actual si existe
if docker ps -a | grep -q portainer; then
    echo "Deteniendo Portainer actual..."
    docker stop portainer 2>/dev/null || true
    docker rm portainer 2>/dev/null || true
fi

# Reiniciar Portainer en modo seguro
echo "Iniciando Portainer en localhost:9443..."
docker run -d \
  -p 127.0.0.1:9443:9443 \
  --name portainer \
  --restart=always \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v portainer_data:/data \
  portainer/portainer-ce:latest

echo -e "${GREEN}Portainer configurado en localhost:9443${NC}"

# ==========================================
# 6. RESUMEN Y SIGUIENTES PASOS
# ==========================================
echo ""
echo -e "${GREEN}[6/6] Configuración completada${NC}"
echo ""
echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}       RESUMEN DE SEGURIDAD${NC}"
echo -e "${GREEN}======================================${NC}"
echo ""
echo -e "Puerto SSH:    ${GREEN}${SSH_PORT}${NC} (protegido con Fail2Ban)"
echo -e "Puerto HTTPS:  ${GREEN}443${NC} (abierto para la aplicación)"
echo -e "Puerto HTTP:   ${YELLOW}80${NC} (bloqueado desde internet, interno solo)"

if [ -z "$PORTAINER_IP" ]; then
    echo -e "Portainer:     ${GREEN}localhost:9443${NC} (solo túnel SSH)"
else
    echo -e "Portainer:     ${GREEN}9443${NC} (solo desde $PORTAINER_IP)"
fi

echo ""
echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}       CÓMO ACCEDER${NC}"
echo -e "${GREEN}======================================${NC}"
echo ""
echo -e "${YELLOW}Aplicación Web:${NC}"
echo "  https://tu-dominio.com (o https://tu-ip)"
echo ""
echo -e "${YELLOW}Portainer:${NC}"

if [ -z "$PORTAINER_IP" ]; then
    echo "  Desde tu ordenador local, ejecuta:"
    echo "    ssh -L 9443:localhost:9443 tu-usuario@tu-servidor"
    echo "  Luego en tu navegador:"
    echo "    http://localhost:9443"
else
    echo "  Desde tu IP permitida ($PORTAINER_IP):"
    echo "    http://tu-servidor:9443"
fi

echo ""
echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}       SIGUIENTES PASOS${NC}"
echo -e "${GREEN}======================================${NC}"
echo ""
echo "1. Accede a Portainer y re-despliega el stack ausarta-drawio"
echo "2. Verifica que la aplicación funciona: https://tu-dominio.com"
echo "3. Revisa los logs: docker logs ausarta-drawio-nginx"
echo ""
echo -e "${YELLOW}IMPORTANTE:${NC}"
echo "- Guarda tu configuración de firewall: ufw status > firewall-backup.txt"
echo "- Cambia la contraseña de Portainer si usas la por defecto"
echo "- Configura certificados SSL para producción"
echo ""
echo -e "${GREEN}¡Securización completada!${NC}"
