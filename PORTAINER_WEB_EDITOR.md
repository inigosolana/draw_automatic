# GUÍA RÁPIDA: Desplegar en Portainer (Web Editor)

## Usar esta opción si el deploy desde Repository falla

### Paso 1: Preparar el servidor

```bash
# Conectar por SSH al servidor
ssh tu-usuario@tu-servidor

# Clonar el repositorio
cd /opt
git clone https://github.com/inigosolana/draw_automatic.git
cd draw_automatic

# Construir las imágenes manualmente
docker build -t ausarta-drawio:latest .
docker build -t ausarta-drawio-nginx:latest -f Dockerfile.nginx .
```

### Paso 2: En Portainer

1. **Stacks** → **Add stack**
2. **Name**: `ausarta-drawio`
3. **Build method**: **Web editor**

### Paso 3: Copiar este docker-compose en el editor

```yaml
version: '3.8'

services:
  drawio-generator:
    image: ausarta-drawio:latest
    container_name: ausarta-drawio
    restart: unless-stopped
    expose:
      - "8000"
    environment:
      GLPI_URL: "${GLPI_URL}"
      GLPI_WEB_URL: "${GLPI_WEB_URL}"
      GLPI_APP_TOKEN: "${GLPI_APP_TOKEN}"
      GLPI_USER_TOKEN: "${GLPI_USER_TOKEN}"
      DRAWIO_LIBRARY_PATH: "/app/libreria_Ausarta_JUN_2026.xml"
      DRAWIO_DOWNLOAD_DB: "/app/data/downloads.sqlite3"
      DRAWIO_SITE_DB: "/app/data/sites.sqlite3"
      DRAWIO_CATALOG_DB: "/app/data/catalog.sqlite3"
      DRAWIO_ACTIVITY_DB: "/app/data/activity.sqlite3"
      DRAWIO_CATALOG_TTL: "${DRAWIO_CATALOG_TTL:-300}"
      DRAWIO_DOWNLOAD_TTL: "${DRAWIO_DOWNLOAD_TTL:-86400}"
      DRAWIO_MAX_UPLOAD_BYTES: "${DRAWIO_MAX_UPLOAD_BYTES:-15728640}"
      DRAWIO_AUTH_REQUIRED: "1"
      DRAWIO_COOKIE_SECURE: "1"
      DRAWIO_FORCE_HTTPS: "0"
      DRAWIO_SECRET_KEY: "${DRAWIO_SECRET_KEY}"
      DRAWIO_SESSION_HOURS: "${DRAWIO_SESSION_HOURS:-8}"
      DRAWIO_PREVIEW_URL: "${DRAWIO_PREVIEW_URL:-https://embed.diagrams.net/}"
      DRAWIO_RATELIMIT_STORAGE: "redis://redis:6379"
    volumes:
      - drawio_data:/app/data
    networks:
      - internal_network
    depends_on:
      - redis
    cap_drop:
      - ALL
    cap_add:
      - CHOWN
      - SETGID
      - SETUID
    security_opt:
      - no-new-privileges:true
    read_only: true
    tmpfs:
      - /tmp:noexec,nosuid,size=100M

  nginx:
    image: ausarta-drawio-nginx:latest
    container_name: ausarta-drawio-nginx
    restart: unless-stopped
    ports:
      - "${DRAWIO_PUBLIC_PORT:-443}:443"
      - "${DRAWIO_HTTP_PORT:-80}:80"
    volumes:
      - nginx_ssl:/etc/nginx/ssl:ro
      - certbot_webroot:/var/www/certbot:ro
      - nginx_logs:/var/log/nginx
    networks:
      - internal_network
      - external_network
    depends_on:
      - drawio-generator
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE
      - CHOWN
      - SETGID
      - SETUID
    security_opt:
      - no-new-privileges:true

  redis:
    image: redis:7-alpine
    container_name: ausarta-drawio-redis
    restart: unless-stopped
    command: redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru
    volumes:
      - redis_data:/data
    networks:
      - internal_network
    cap_drop:
      - ALL
    cap_add:
      - SETGID
      - SETUID
    security_opt:
      - no-new-privileges:true
    read_only: true
    tmpfs:
      - /tmp:noexec,nosuid,size=50M

volumes:
  drawio_data:
  redis_data:
  nginx_ssl:
  certbot_webroot:
  nginx_logs:

networks:
  internal_network:
    driver: bridge
    internal: true
  external_network:
    driver: bridge
```

### Paso 4: Añadir Variables de Entorno

En Portainer, scroll hasta "Environment variables" y añadir:

```
GLPI_URL=https://tu-glpi.com/apirest.php
GLPI_WEB_URL=https://tu-glpi.com
GLPI_APP_TOKEN=tu_token_app
GLPI_USER_TOKEN=tu_token_usuario
DRAWIO_SECRET_KEY=<generar con python -c "import secrets; print(secrets.token_hex(32))">
DRAWIO_PUBLIC_PORT=443
DRAWIO_HTTP_PORT=80
```

### Paso 5: Deploy

Click en **"Deploy the stack"**

---

## Añadir Certificados SSL

Después del despliegue:

```bash
# Opción 1: Autofirmados (para pruebas)
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout key.pem -out cert.pem -subj "/CN=localhost"

# Copiar al volumen
docker volume inspect ausarta_drawio_nginx_ssl
sudo cp cert.pem key.pem /var/lib/docker/volumes/ausarta_drawio_nginx_ssl/_data/

# Reiniciar nginx
docker restart ausarta-drawio-nginx

# Opción 2: Let's Encrypt (producción)
sudo certbot certonly --standalone -d tu-dominio.com
sudo cp /etc/letsencrypt/live/tu-dominio.com/fullchain.pem \
  /var/lib/docker/volumes/ausarta_drawio_nginx_ssl/_data/cert.pem
sudo cp /etc/letsencrypt/live/tu-dominio.com/privkey.pem \
  /var/lib/docker/volumes/ausarta_drawio_nginx_ssl/_data/key.pem
docker restart ausarta-drawio-nginx
```

---

## Verificar

```bash
docker ps --filter "name=ausarta-drawio"
docker logs ausarta-drawio-nginx
docker logs ausarta-drawio
curl -k https://localhost
```

Debería funcionar ahora!
