# Guía de Despliegue en Portainer

## Problema Común: "not a directory" Error

El error que recibiste ocurre porque Portainer tiene problemas con bind mounts de archivos individuales. La solución es usar una imagen custom de nginx con la configuración incluida.

---

## Solución Rápida

### Opción A: Usar docker-compose.portainer.yml (Recomendado)

Este archivo usa una imagen custom de nginx que incluye la configuración.

#### Pasos en Portainer:

1. **Ir a Stacks** en Portainer

2. **Click en "Add stack"**

3. **Configurar el stack:**
   - **Name**: `ausarta-drawio`
   - **Build method**: `Repository`
   - **Repository URL**: `https://github.com/inigosolana/draw_automatic`
   - **Repository reference**: `refs/heads/main`
   - **Compose path**: `docker-compose.portainer.yml`

4. **Configurar Variables de Entorno** (muy importante):

   Click en "Add an environment variable" para cada una:

   ```
   GLPI_URL=https://tu-glpi.com/apirest.php
   GLPI_WEB_URL=https://tu-glpi.com
   GLPI_APP_TOKEN=tu_token_app
   GLPI_USER_TOKEN=tu_token_usuario
   DRAWIO_SECRET_KEY=GENERAR_UNA_CLAVE_ALEATORIA_LARGA
   DRAWIO_PUBLIC_PORT=443
   DRAWIO_HTTP_PORT=80
   DRAWIO_COOKIE_SECURE=1
   ```

   **IMPORTANTE**: Genera la SECRET_KEY con:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

5. **Click en "Deploy the stack"**

6. **Esperar a que se construyan las imágenes** (primera vez tarda ~2-3 minutos)

---

### Opción B: Build Manual (Si la Opción A falla)

Si Portainer tiene problemas con el build desde el repositorio:

#### 1. Clonar el repositorio localmente en el servidor:

```bash
cd /opt
git clone https://github.com/inigosolana/draw_automatic.git
cd draw_automatic
```

#### 2. Construir las imágenes manualmente:

```bash
# Construir imagen de la app
docker build -t ausarta-drawio:latest -f Dockerfile .

# Construir imagen de nginx
docker build -t ausarta-drawio-nginx:latest -f Dockerfile.nginx .
```

#### 3. En Portainer, usar "Web editor":

1. **Stacks** → **Add stack**
2. **Name**: `ausarta-drawio`
3. **Build method**: `Web editor`
4. **Pegar el contenido de `docker-compose.portainer.yml`** pero cambiando las líneas de build:

```yaml
  drawio-generator:
    image: ausarta-drawio:latest  # Quitar la sección build:
    container_name: ausarta-drawio
    # ... resto igual

  nginx:
    image: ausarta-drawio-nginx:latest  # Quitar la sección build:
    container_name: ausarta-drawio-nginx
    # ... resto igual
```

5. **Añadir variables de entorno** (igual que en Opción A)

6. **Deploy**

---

## Configurar SSL/TLS

Después de desplegar, necesitas añadir certificados SSL:

### Opción 1: Certificados Autofirmados (Pruebas)

```bash
# En el servidor
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout key.pem -out cert.pem \
  -subj "/CN=localhost"

# Copiar al volumen de nginx_ssl
# Primero, encontrar el volumen
docker volume inspect ausarta_drawio_nginx_ssl | grep Mountpoint

# Copiar (reemplaza /var/lib/docker/volumes/... con tu path real)
sudo cp cert.pem /var/lib/docker/volumes/ausarta_drawio_nginx_ssl/_data/
sudo cp key.pem /var/lib/docker/volumes/ausarta_drawio_nginx_ssl/_data/

# Reiniciar nginx
docker restart ausarta-drawio-nginx
```

### Opción 2: Let's Encrypt (Producción)

```bash
# Instalar certbot en el servidor (no en Docker)
sudo apt update && sudo apt install certbot -y

# Obtener certificados (asegúrate de que el dominio apunta a tu servidor)
sudo certbot certonly --standalone -d tu-dominio.com

# Copiar al volumen
sudo cp /etc/letsencrypt/live/tu-dominio.com/fullchain.pem \
  /var/lib/docker/volumes/ausarta_drawio_nginx_ssl/_data/cert.pem

sudo cp /etc/letsencrypt/live/tu-dominio.com/privkey.pem \
  /var/lib/docker/volumes/ausarta_drawio_nginx_ssl/_data/key.pem

# Reiniciar nginx
docker restart ausarta-drawio-nginx
```

### Opción 3: Subir Certificados desde Portainer

1. **Exec Console** en el contenedor nginx (desde Portainer)

2. **Ejecutar**:
```bash
# Esto creará archivos vacíos temporales
touch /etc/nginx/ssl/cert.pem /etc/nginx/ssl/key.pem
```

3. **Desde tu máquina**, copiar los certificados:
```bash
# Obtener el ID del volumen
docker volume inspect ausarta_drawio_nginx_ssl

# Copiar desde Windows/local usando SCP o Portainer file browser
# O usar el navegador de archivos de Portainer en Volumes
```

---

## Verificar que Funciona

```bash
# Ver logs
docker logs ausarta-drawio-nginx
docker logs ausarta-drawio

# Probar acceso
curl -k https://localhost  # -k ignora certificado autofirmado

# Verificar que el puerto 8000 NO está expuesto
docker ps | grep ausarta  # No debería ver 0.0.0.0:8000
```

---

## Solución de Problemas

### Error: "nginx_config not found"

Si ves este error con `docker-compose.yml` (no el `.portainer.yml`), es porque Docker Configs no funciona bien en tu versión de Portainer.

**Solución**: Usa `docker-compose.portainer.yml` en su lugar.

### Error: "Address already in use"

Otro servicio está usando los puertos 80 o 443.

```bash
# Ver qué está usando el puerto
sudo lsof -i :80
sudo lsof -i :443

# Detener el servicio conflictivo (ejemplo: apache)
sudo systemctl stop apache2
```

### Error: "permission denied" al copiar certificados

```bash
# Dar permisos correctos
sudo chown -R 101:101 /var/lib/docker/volumes/ausarta_drawio_nginx_ssl/_data/
sudo chmod 600 /var/lib/docker/volumes/ausarta_drawio_nginx_ssl/_data/key.pem
sudo chmod 644 /var/lib/docker/volumes/ausarta_drawio_nginx_ssl/_data/cert.pem
```

### Nginx no inicia: "certificate file not found"

Crea certificados autofirmados temporales:

```bash
docker exec ausarta-drawio-nginx sh -c '
  apk add openssl && \
  openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/nginx/ssl/key.pem \
    -out /etc/nginx/ssl/cert.pem \
    -subj "/CN=localhost"
'

docker restart ausarta-drawio-nginx
```

### La aplicación no conecta con Redis

```bash
# Verificar que Redis está corriendo
docker logs ausarta-drawio-redis

# Si falla, verificar la red interna
docker network inspect ausarta_drawio_internal_network

# Redis debería aparecer en "Containers"
```

---

## Actualizar la Aplicación

### Desde Portainer:

1. **Stacks** → **ausarta-drawio**
2. **Click en "Pull and redeploy"**
3. Esperar a que se reconstruyan las imágenes

### Desde CLI:

```bash
cd /opt/draw_automatic
git pull
docker-compose -f docker-compose.portainer.yml build --no-cache
docker-compose -f docker-compose.portainer.yml up -d
```

---

## Securización de Portainer

**IMPORTANTE**: Sigue estos pasos inmediatamente después de desplegar:

1. **Cambiar la contraseña de admin** de Portainer

2. **Restringir acceso por IP** en el firewall:
```bash
sudo ufw allow from TU_IP to any port 9443
sudo ufw deny 9443
```

3. **Usar HTTPS** en Portainer:
```bash
docker run -d -p 9443:9443 \
  --name portainer --restart=always \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v portainer_data:/data \
  portainer/portainer-ce:latest \
  --ssl --sslcert /path/cert.pem --sslkey /path/key.pem
```

4. **No exponer Portainer a internet directamente** - usa VPN o túnel SSH

5. **Crear usuarios con permisos limitados** para desarrolladores

Ver más detalles en `SECURITY.md`.

---

## Acceder a la Aplicación

Una vez desplegado:

1. **HTTP**: `http://tu-servidor` → Redirige automáticamente a HTTPS
2. **HTTPS**: `https://tu-servidor` o `https://tu-dominio.com`

**Login**: Usa tus credenciales de GLPI

---

## Comandos Útiles

```bash
# Ver todos los contenedores del stack
docker ps --filter "name=ausarta-drawio"

# Ver logs en tiempo real
docker logs -f ausarta-drawio-nginx
docker logs -f ausarta-drawio

# Entrar en un contenedor
docker exec -it ausarta-drawio sh

# Ver estadísticas de recursos
docker stats ausarta-drawio-nginx ausarta-drawio ausarta-drawio-redis

# Reiniciar todo el stack
docker restart ausarta-drawio-nginx ausarta-drawio ausarta-drawio-redis

# Ver volúmenes
docker volume ls | grep ausarta

# Backup de datos
docker run --rm -v ausarta_drawio_drawio_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/backup-$(date +%F).tar.gz /data
```

---

## Resumen de Archivos

- **docker-compose.yml**: Para desarrollo local (usa bind mount)
- **docker-compose.portainer.yml**: Para Portainer (usa imagen custom)
- **Dockerfile.nginx**: Imagen custom de nginx con configuración incluida
- **nginx.conf**: Configuración del reverse proxy

---

Si tienes problemas, revisa los logs primero:
```bash
docker logs ausarta-drawio-nginx
docker logs ausarta-drawio
```

Y consulta `SECURITY.md` para más información sobre configuración segura.
