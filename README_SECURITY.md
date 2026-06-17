# Ausarta Draw.io Generator - Despliegue Seguro

## Mejoras de Seguridad Implementadas ✅

Este proyecto ha sido completamente securizado con las siguientes medidas:

### 🔒 Seguridad de Aplicación
- **Protección CSRF**: Tokens en todos los formularios
- **Rate Limiting**: Protección contra fuerza bruta y DDoS (doble capa: Flask + Nginx)
- **Headers de Seguridad**: HSTS, CSP, X-Frame-Options, etc.
- **Gestión Segura de Sesiones**: Cookies HttpOnly, Secure, SameSite
- **Logging de Seguridad**: Registro de intentos de login, uploads, y actividad sospechosa
- **Validación de Entrada**: Sanitización y validación estricta
- **SECRET_KEY fuerte**: Generación automática si no se configura

### 🛡️ Seguridad de Infraestructura
- **Nginx Reverse Proxy**: SSL/TLS terminación y rate limiting adicional
- **Aislamiento de Red**: Backend NO expuesto directamente
- **Hardening de Contenedores**: No-root user, capabilities mínimas, read-only
- **Redis para Rate Limiting**: Persistencia de límites entre reinicios

### 📋 Documentación Completa
- **SECURITY.md**: Guía exhaustiva de securización
- **nginx.conf**: Configuración de proxy reverso con SSL
- **docker-compose.yml**: Despliegue con aislamiento de red

---

## Inicio Rápido (Desarrollo)

```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Copiar configuración de ejemplo
cp .env.example .env

# 3. Editar .env y configurar las variables necesarias
nano .env

# 4. Ejecutar en modo desarrollo
python web_app.py
```

---

## Despliegue en Producción

### Requisitos Previos

- Docker y Docker Compose instalados
- Dominio apuntando a tu servidor (para SSL)
- Puertos 80 y 443 disponibles

### Paso 1: Generar SECRET_KEY

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### Paso 2: Configurar Variables de Entorno

```bash
# Copiar plantilla
cp .env.example .env

# Editar y configurar TODAS las variables
nano .env
```

**IMPORTANTE**: Cambiar al menos:
- `DRAWIO_SECRET_KEY` (usar el generado en Paso 1)
- `GLPI_URL`, `GLPI_WEB_URL`, `GLPI_APP_TOKEN`, `GLPI_USER_TOKEN`
- Verificar que `DRAWIO_COOKIE_SECURE=1`

### Paso 3: Configurar SSL/TLS

#### Opción A: Let's Encrypt (Recomendado)

```bash
# 1. Obtener certificados
sudo certbot certonly --standalone -d tu-dominio.com

# 2. Copiar certificados al volumen de Docker
sudo cp /etc/letsencrypt/live/tu-dominio.com/fullchain.pem /var/lib/docker/volumes/ausarta_drawio_nginx_ssl/_data/cert.pem
sudo cp /etc/letsencrypt/live/tu-dominio.com/privkey.pem /var/lib/docker/volumes/ausarta_drawio_nginx_ssl/_data/key.pem
```

#### Opción B: Certificados Autofirmados (Solo Pruebas)

```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout key.pem -out cert.pem
docker volume create ausarta_drawio_nginx_ssl
sudo cp cert.pem key.pem /var/lib/docker/volumes/ausarta_drawio_nginx_ssl/_data/
```

### Paso 4: Actualizar nginx.conf

```bash
# Editar nginx.conf y cambiar "server_name _" por tu dominio
nano nginx.conf

# Cambiar:
# server_name _;
# Por:
# server_name tu-dominio.com;
```

### Paso 5: Desplegar

```bash
# Construir e iniciar
docker-compose up -d --build

# Verificar estado
docker-compose ps

# Ver logs
docker-compose logs -f
```

### Paso 6: Verificar Seguridad

```bash
# Verificar headers de seguridad
curl -I https://tu-dominio.com

# Verificar redirección HTTP → HTTPS
curl -I http://tu-dominio.com

# Verificar rate limiting
for i in {1..15}; do curl https://tu-dominio.com/login; done

# Verificar que el puerto 8000 NO está expuesto
curl http://tu-servidor:8000  # Debería fallar
```

### Paso 7: Configurar Firewall

```bash
# UFW (Ubuntu/Debian)
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# Verificar
sudo ufw status
```

---

## Arquitectura de Seguridad

```
Internet
    │
    ├─── Puerto 80 (HTTP) ──┐
    └─── Puerto 443 (HTTPS) ─┤
                             │
                        ┌────▼────┐
                        │  Nginx  │  (Red Externa + Interna)
                        │ Reverse │  - SSL/TLS Termination
                        │  Proxy  │  - Rate Limiting
                        └────┬────┘  - Security Headers
                             │
                   ┌─────────┴─────────┐
                   │  Red Interna      │
                   │  (No Internet)    │
                   │                   │
              ┌────▼────┐         ┌───▼───┐
              │  Flask  │────────▶│ Redis │
              │  App    │         │       │
              └─────────┘         └───────┘
              Puerto 8000         Puerto 6379
              (NO expuesto)       (NO expuesto)
```

**Capas de Seguridad**:
1. **Nginx**: Primera línea de defensa (rate limiting, headers)
2. **Flask-Limiter**: Segunda capa de rate limiting
3. **CSRF Protection**: Prevención de ataques CSRF
4. **Autenticación GLPI**: Validación de usuarios
5. **Network Isolation**: Backend aislado
6. **Container Hardening**: No-root, capabilities limitadas

---

## Monitorización

### Ver Logs de Seguridad

```bash
# Logs de la aplicación
docker-compose logs -f drawio-generator | grep SECURITY

# Logs de nginx
docker-compose logs -f nginx

# Intentos de login fallidos
docker-compose logs drawio-generator | grep "Login attempt failed"

# IPs bloqueadas por rate limiting
docker-compose logs nginx | grep "429"
```

### Estadísticas de Redis

```bash
# Conectar a Redis
docker exec -it ausarta-drawio-redis redis-cli

# Ver keys (rate limiting)
KEYS *

# Ver estadísticas
INFO stats
```

---

## Mantenimiento

### Actualizar Certificados SSL

```bash
# Renovar con certbot
sudo certbot renew

# Copiar al volumen
sudo cp /etc/letsencrypt/live/tu-dominio.com/fullchain.pem /var/lib/docker/volumes/ausarta_drawio_nginx_ssl/_data/cert.pem
sudo cp /etc/letsencrypt/live/tu-dominio.com/privkey.pem /var/lib/docker/volumes/ausarta_drawio_nginx_ssl/_data/key.pem

# Recargar nginx
docker-compose exec nginx nginx -s reload
```

### Actualizar Dependencias

```bash
# Actualizar requirements.txt
pip list --outdated

# Reconstruir contenedores
docker-compose build --no-cache
docker-compose up -d
```

### Backup

```bash
# Backup de datos
docker run --rm -v ausarta_drawio_drawio_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/drawio-backup-$(date +%F).tar.gz /data

# Backup de configuración
tar czf config-backup-$(date +%F).tar.gz .env nginx.conf docker-compose.yml
```

---

## Securización de Portainer

Ver la sección completa en `SECURITY.md`, pero los puntos clave son:

1. **Cambiar puerto por defecto** (usar 9443 en lugar de 9000)
2. **Usar TLS** con certificados propios
3. **Configurar firewall** para restringir IPs
4. **Usar Docker Socket Proxy** en lugar de montar el socket directamente
5. **Autenticación fuerte** y permisos mínimos

```bash
# Ejemplo de restricción con firewall
sudo ufw allow from <tu_ip> to any port 9443
sudo ufw deny 9443
```

---

## Solución de Problemas

### Error: "CSRF token missing"

**Causa**: Las cookies no se están enviando correctamente.

**Solución**:
1. Verifica que `DRAWIO_COOKIE_SECURE=1` solo si usas HTTPS
2. Verifica que el dominio es correcto
3. Limpia las cookies del navegador

### Error: "429 Too Many Requests"

**Causa**: Rate limiting activado.

**Solución**:
1. Espera unos minutos
2. Si es legítimo, ajusta los límites en `nginx.conf` y `web_app.py`

### El contenedor no inicia

```bash
# Ver logs completos
docker-compose logs drawio-generator

# Verificar variables de entorno
docker-compose config

# Verificar permisos
ls -la /var/lib/docker/volumes/ausarta_drawio_drawio_data/_data/
```

---

## Testing

```bash
# Ejecutar tests
pytest

# Con cobertura
pytest --cov=generator --cov-report=html

# Solo tests de seguridad (si existen)
pytest -k security
```

---

## Contribuir

Antes de hacer un PR:

1. Ejecutar tests: `pytest`
2. Verificar linting: `flake8` o `ruff`
3. No incluir `.env` ni archivos sensibles
4. Documentar cambios de seguridad en `SECURITY.md`

---

## Licencia

[Tu licencia aquí]

---

## Soporte

Para problemas de seguridad, consulta `SECURITY.md`.

Para otros problemas, abre un issue en GitHub.

---

**Última actualización**: Junio 2026  
**Estado**: ✅ Producción Ready con Seguridad Completa
