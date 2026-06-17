# Guía de Securización - Ausarta Draw.io Generator

Esta guía detalla las medidas de seguridad implementadas y las configuraciones necesarias para un despliegue seguro en producción.

## Índice

1. [Mejoras de Seguridad Implementadas](#mejoras-de-seguridad-implementadas)
2. [Configuración de Producción](#configuración-de-producción)
3. [Certificados SSL/TLS](#certificados-ssltls)
4. [Securización de Portainer](#securización-de-portainer)
5. [Monitorización y Logs](#monitorización-y-logs)
6. [Respuesta a Incidentes](#respuesta-a-incidentes)
7. [Checklist de Seguridad](#checklist-de-seguridad)

---

## Mejoras de Seguridad Implementadas

### 1. Protección CSRF (Cross-Site Request Forgery)
✅ **Implementado**: Flask-WTF con tokens CSRF en todos los formularios
- Todos los formularios POST incluyen tokens CSRF
- Validación automática en el backend
- Protección contra ataques CSRF

### 2. Rate Limiting
✅ **Implementado**: Doble capa de rate limiting

**Flask (Flask-Limiter)**:
- Login: 10 peticiones/minuto
- Operaciones pesadas (generate, upload): 20-30/hora
- Health check: 30/minuto
- General: 200/día, 50/hora

**Nginx**:
- Login: 10 req/min con burst de 3
- API endpoints: 30 req/min con burst de 10
- General: 100 req/min con burst de 20

### 3. Headers de Seguridad HTTP
✅ **Implementado**: Flask-Talisman + Nginx

**Headers configurados**:
- `Strict-Transport-Security` (HSTS): Forzar HTTPS por 2 años
- `Content-Security-Policy` (CSP): Prevenir XSS
- `X-Frame-Options: SAMEORIGIN`: Prevenir clickjacking
- `X-Content-Type-Options: nosniff`: Prevenir MIME sniffing
- `X-XSS-Protection`: Protección XSS adicional
- `Referrer-Policy`: Control de referrers

### 4. Gestión Segura de Sesiones
✅ **Implementado**:
- Cookies con `HttpOnly`, `Secure`, `SameSite=Lax`
- Sesiones con timeout configurable (por defecto 8 horas)
- Generación automática de SECRET_KEY si no se configura (con advertencia)
- Regeneración de sesión en login

### 5. Logging de Eventos de Seguridad
✅ **Implementado**:
- Registro de intentos de login (exitosos y fallidos)
- Registro de logout con IP y usuario
- Registro de subidas de archivos con validación
- Logs estructurados para análisis

### 6. Aislamiento de Red (Docker)
✅ **Implementado**:
- Red interna (`internal_network`): Solo para comunicación entre contenedores
- Red externa (`external_network`): Solo nginx tiene acceso
- El backend Flask NO está expuesto directamente
- Redis en red interna únicamente

### 7. Hardening de Contenedores
✅ **Implementado**:
- Usuario no-root en todos los contenedores
- `cap_drop: ALL` + capabilities mínimas necesarias
- `no-new-privileges:true`
- `read_only: true` donde sea posible
- tmpfs para directorios temporales

### 8. Validación de Entrada
✅ **Implementado**:
- `defusedxml` para parsear XML de forma segura
- Validación de tipos y rangos en inputs
- Sanitización de paths y nombres de archivo
- Límite de tamaño de uploads (15MB por defecto)

---

## Configuración de Producción

### Paso 1: Generar SECRET_KEY Segura

**CRÍTICO**: Nunca uses la SECRET_KEY de ejemplo en producción.

```bash
# Genera una clave secreta fuerte
python -c "import secrets; print(secrets.token_hex(32))"
```

Copia el resultado y añádelo a tu archivo `.env`:

```bash
DRAWIO_SECRET_KEY=<tu_clave_generada_aqui>
```

### Paso 2: Configurar Variables de Entorno

Crea un archivo `.env` basado en `.env.example`:

```bash
cp .env.example .env
```

Edita `.env` y configura:

```bash
# SEGURIDAD - OBLIGATORIO cambiar en producción
DRAWIO_SECRET_KEY=<tu_clave_generada>
GLPI_APP_TOKEN=<tu_token_de_glpi>
GLPI_USER_TOKEN=<tu_token_de_usuario_glpi>

# Configuración de red
DRAWIO_PUBLIC_PORT=443
DRAWIO_HTTP_PORT=80

# Seguridad de cookies (siempre 1 con HTTPS)
DRAWIO_COOKIE_SECURE=1

# URLs de GLPI
GLPI_URL=https://tu-glpi.com/apirest.php
GLPI_WEB_URL=https://tu-glpi.com
```

### Paso 3: Configurar Nginx y SSL

#### Opción A: Usar Let's Encrypt (Recomendado)

1. **Instala certbot** (si no está instalado):

```bash
# En el host (no en Docker)
sudo apt install certbot
```

2. **Obtén certificados**:

```bash
# Asegúrate de que el dominio apunta a tu servidor
sudo certbot certonly --standalone -d drawio.tudominio.com
```

3. **Copia los certificados al volumen de Docker**:

```bash
# Encuentra el volumen
docker volume inspect ausarta_drawio_nginx_ssl

# Copia los certificados
sudo cp /etc/letsencrypt/live/drawio.tudominio.com/fullchain.pem /var/lib/docker/volumes/ausarta_drawio_nginx_ssl/_data/cert.pem
sudo cp /etc/letsencrypt/live/drawio.tudominio.com/privkey.pem /var/lib/docker/volumes/ausarta_drawio_nginx_ssl/_data/key.pem
```

4. **Actualiza nginx.conf** con tu dominio:

```nginx
server_name drawio.tudominio.com;
```

#### Opción B: Usar Certificados Propios

1. **Genera certificados autofirmados** (solo para pruebas):

```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout key.pem -out cert.pem \
  -subj "/CN=drawio.local"
```

2. **Copia al volumen**:

```bash
docker volume inspect ausarta_drawio_nginx_ssl
sudo cp cert.pem key.pem /var/lib/docker/volumes/ausarta_drawio_nginx_ssl/_data/
```

### Paso 4: Desplegar con Docker Compose

```bash
# Construir e iniciar los servicios
docker-compose up -d --build

# Verificar que todo está funcionando
docker-compose ps
docker-compose logs -f nginx
docker-compose logs -f drawio-generator
```

### Paso 5: Verificar la Configuración de Seguridad

```bash
# Verificar headers de seguridad
curl -I https://tu-dominio.com

# Verificar que HTTP redirige a HTTPS
curl -I http://tu-dominio.com

# Verificar rate limiting
for i in {1..15}; do curl https://tu-dominio.com/login; done

# Verificar que el backend no está expuesto directamente
curl http://tu-servidor:8000  # Debería fallar
```

---

## Certificados SSL/TLS

### Renovación Automática con Let's Encrypt

Si usas Let's Encrypt, configura la renovación automática:

1. **Descomentar el servicio certbot** en `docker-compose.yml`:

```yaml
certbot:
  image: certbot/certbot:latest
  container_name: ausarta-drawio-certbot
  volumes:
    - nginx_ssl:/etc/letsencrypt
    - certbot_webroot:/var/www/certbot
  entrypoint: "/bin/sh -c 'trap exit TERM; while :; do certbot renew; sleep 12h & wait $${!}; done;'"
```

2. **Reiniciar nginx después de la renovación**:

```bash
# Cron job para recargar nginx después de renovar
0 3 * * * docker exec ausarta-drawio-nginx nginx -s reload
```

### Verificar Configuración SSL

Usa [SSL Labs](https://www.ssllabs.com/ssltest/) para verificar tu configuración SSL:

```
https://www.ssllabs.com/ssltest/analyze.html?d=tu-dominio.com
```

**Objetivo**: Obtener calificación A o A+

---

## Securización de Portainer

### 1. Proteger el Acceso

#### Cambiar el Puerto por Defecto

```yaml
# docker-compose.yml de Portainer
ports:
  - "9443:9443"  # Usa puerto no estándar
  # NO expongas el puerto 8000 de Portainer
```

#### Usar Autenticación Fuerte

1. **Activa autenticación LDAP/OAuth** si está disponible
2. **Cambia la contraseña de admin** inmediatamente después de la instalación
3. **Crea usuarios con permisos mínimos** (principio de least privilege)

### 2. Configurar TLS en Portainer

```bash
# Genera certificados para Portainer
docker run -d -p 9443:9443 \
  --name portainer \
  --restart=always \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v portainer_data:/data \
  -v /ruta/a/cert.pem:/certs/cert.pem:ro \
  -v /ruta/a/key.pem:/certs/key.pem:ro \
  portainer/portainer-ce:latest \
  --ssl \
  --sslcert /certs/cert.pem \
  --sslkey /certs/key.pem
```

### 3. Configurar Firewall

**IMPORTANTE**: Portainer solo debe ser accesible desde IPs confiables.

```bash
# UFW (Ubuntu/Debian)
sudo ufw allow from <tu_ip> to any port 9443
sudo ufw deny 9443

# iptables
sudo iptables -A INPUT -p tcp -s <tu_ip> --dport 9443 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 9443 -j DROP
```

### 4. Usar Reverse Proxy para Portainer

Similar a la aplicación principal, configura nginx como reverse proxy:

```nginx
server {
    listen 443 ssl http2;
    server_name portainer.tudominio.com;
    
    ssl_certificate /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;
    
    location / {
        proxy_pass https://localhost:9443;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 5. Limitar Acceso al Socket de Docker

**CRÍTICO**: El socket de Docker (`/var/run/docker.sock`) da control total del sistema.

```yaml
# Opción 1: Usar Docker Socket Proxy (RECOMENDADO)
services:
  docker-proxy:
    image: tecnativa/docker-socket-proxy
    container_name: docker-proxy
    environment:
      CONTAINERS: 1
      SERVICES: 1
      TASKS: 1
      NETWORKS: 1
      VOLUMES: 1
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - portainer_network

  portainer:
    image: portainer/portainer-ce:latest
    # NO montar /var/run/docker.sock directamente
    environment:
      DOCKER_HOST: tcp://docker-proxy:2375
    networks:
      - portainer_network
```

### 6. Auditoría de Portainer

```bash
# Revisar logs de acceso
docker logs portainer | grep "authentication"

# Revisar usuarios activos
# Desde la UI de Portainer: Settings > Users

# Revisar actividad
# Desde la UI: Activity Logs
```

---

## Monitorización y Logs

### 1. Logs de la Aplicación

```bash
# Ver logs de seguridad
docker-compose logs -f drawio-generator | grep SECURITY

# Ver logs de nginx (acceso)
docker-compose logs nginx | grep -E "(login|upload|generate)"

# Buscar intentos de login fallidos
docker-compose logs drawio-generator | grep "Login attempt failed"

# Buscar IPs bloqueadas por rate limiting
docker-compose logs nginx | grep "429"
```

### 2. Centralizar Logs (Opcional)

Para entornos de producción, considera usar:

- **ELK Stack** (Elasticsearch + Logstash + Kibana)
- **Loki + Grafana**
- **Syslog remoto**

Ejemplo con Loki:

```yaml
# docker-compose.yml
services:
  drawio-generator:
    logging:
      driver: loki
      options:
        loki-url: "http://localhost:3100/loki/api/v1/push"
        loki-retries: 5
        loki-batch-size: 400
```

### 3. Alertas

Configura alertas para:

- ✅ Múltiples intentos de login fallidos desde la misma IP
- ✅ Rate limiting activado frecuentemente
- ✅ Errores 5xx en nginx
- ✅ Contenedores que se reinician
- ✅ Uso excesivo de CPU/memoria

---

## Respuesta a Incidentes

### Si Detectas un Acceso No Autorizado

1. **Bloquea la IP inmediatamente**:

```bash
# En el firewall
sudo ufw deny from <ip_maliciosa>

# O en nginx
# Añade a nginx.conf:
deny <ip_maliciosa>;
```

2. **Revoca todas las sesiones**:

```bash
# Reinicia la aplicación (destruye sesiones en memoria)
docker-compose restart drawio-generator

# Si usas Redis
docker exec -it ausarta-drawio-redis redis-cli FLUSHALL
```

3. **Cambia SECRET_KEY**:

```bash
# Genera nueva clave
python -c "import secrets; print(secrets.token_hex(32))"

# Actualiza .env
DRAWIO_SECRET_KEY=<nueva_clave>

# Reinicia
docker-compose up -d
```

4. **Revisa los logs**:

```bash
# Busca actividad sospechosa
docker-compose logs drawio-generator | grep "<ip_maliciosa>"
docker-compose logs nginx | grep "<ip_maliciosa>"
```

5. **Actualiza contraseñas GLPI** si es necesario

### Si Hay una Brecha de Seguridad

1. **Detén los servicios** si es crítico:

```bash
docker-compose down
```

2. **Haz backup de datos y logs**:

```bash
docker cp ausarta-drawio:/app/data ./backup-$(date +%F)
docker-compose logs > incident-logs-$(date +%F).txt
```

3. **Analiza los logs** para entender el vector de ataque

4. **Aplica parches** y actualiza dependencias:

```bash
pip list --outdated
docker pull nginx:1.25-alpine
docker pull redis:7-alpine
```

5. **Restaura el servicio** con las correcciones aplicadas

6. **Notifica a los usuarios** si se vieron afectados

---

## Checklist de Seguridad

### Pre-Producción

- [ ] `DRAWIO_SECRET_KEY` generada aleatoriamente (NO usar la de ejemplo)
- [ ] Certificados SSL/TLS configurados y válidos
- [ ] `DRAWIO_COOKIE_SECURE=1` en `.env`
- [ ] `DRAWIO_AUTH_REQUIRED=1` activado
- [ ] Todas las variables `GLPI_*` configuradas correctamente
- [ ] Nginx configurado como reverse proxy
- [ ] Puertos internos NO expuestos directamente (solo nginx en 80/443)
- [ ] Red interna de Docker configurada
- [ ] Firewall configurado (solo 80/443 abiertos)
- [ ] Contraseñas de Portainer cambiadas
- [ ] Usuarios de Portainer con permisos mínimos

### Post-Despliegue

- [ ] Verificar headers de seguridad con `curl -I`
- [ ] Probar rate limiting con múltiples peticiones
- [ ] Verificar redirección HTTP → HTTPS
- [ ] Probar login con credenciales incorrectas (verificar logs)
- [ ] Verificar que CSRF funciona (intento sin token = error)
- [ ] Prueba de SSL en SSL Labs (objetivo: A/A+)
- [ ] Verificar que el puerto 8000 del backend NO es accesible
- [ ] Configurar monitorización de logs
- [ ] Configurar backup automático de volúmenes

### Mantenimiento Regular

- [ ] Revisar logs de seguridad semanalmente
- [ ] Actualizar dependencias mensualmente
- [ ] Renovar certificados SSL antes de expirar
- [ ] Auditar usuarios de Portainer trimestralmente
- [ ] Probar procedimiento de restauración desde backup
- [ ] Revisar reglas de firewall
- [ ] Actualizar imágenes Docker

---

## Recursos Adicionales

### Documentación

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Mozilla Security Guidelines](https://infosec.mozilla.org/guidelines/web_security)
- [Docker Security Best Practices](https://docs.docker.com/engine/security/)
- [Nginx Security Controls](https://nginx.org/en/docs/http/ngx_http_ssl_module.html)

### Herramientas de Auditoría

```bash
# Escaneo de puertos
nmap -sV -sC <tu-servidor>

# Verificación de headers
curl -I https://tu-dominio.com

# Análisis de SSL
sslscan tu-dominio.com

# Escaneo de vulnerabilidades en contenedores
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy image ausarta-drawio:latest
```

### Contacto

Si encuentras una vulnerabilidad de seguridad, por favor repórtala de forma responsable a través de los canales apropiados en lugar de crear un issue público.

---

**Última actualización**: Junio 2026  
**Versión**: 2.0
