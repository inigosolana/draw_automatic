# Solución: Puerto 80 en uso

## Identificar el proceso

Ejecuta estos comandos en tu servidor para ver qué está usando el puerto 80:

```bash
# Opción 1: lsof
sudo lsof -i :80

# Opción 2: netstat
sudo netstat -tlnp | grep :80

# Opción 3: ss
sudo ss -tlnp | grep :80
```

Probablemente verás uno de estos:
- **Apache** (httpd o apache2)
- **Nginx** existente
- **Otro contenedor Docker**

---

## ✅ Soluciones (elige una)

### SOLUCIÓN 1: Detener el servicio conflictivo (Recomendado si no lo necesitas)

#### Si es Apache:
```bash
# Detener Apache
sudo systemctl stop apache2     # Debian/Ubuntu
sudo systemctl stop httpd       # CentOS/RHEL

# Deshabilitar para que no inicie en el arranque
sudo systemctl disable apache2  # Debian/Ubuntu
sudo systemctl disable httpd    # CentOS/RHEL

# Verificar que se detuvo
sudo lsof -i :80
```

#### Si es Nginx:
```bash
# Detener Nginx
sudo systemctl stop nginx

# Deshabilitar
sudo systemctl disable nginx

# Verificar
sudo lsof -i :80
```

#### Si es otro contenedor Docker:
```bash
# Ver contenedores corriendo
docker ps

# Detener el contenedor que usa el puerto 80
docker stop <nombre_o_id_del_contenedor>
```

**Después, volver a Portainer y re-desplegar el stack.**

---

### SOLUCIÓN 2: Cambiar el puerto HTTP en el .env

Si necesitas mantener el otro servicio en el puerto 80:

#### En Portainer:

1. **Ir a tu stack** → **Editor**
2. **Scroll hasta "Environment variables"**
3. **Cambiar o añadir:**
   ```
   DRAWIO_HTTP_PORT=8080
   ```
   (O cualquier puerto libre: 8080, 8081, 3000, etc.)

4. **Update the stack**

Luego podrás acceder:
- HTTP: `http://tu-servidor:8080` (redirige a HTTPS)
- HTTPS: `https://tu-servidor:443`

---

### SOLUCIÓN 3: Deshabilitar HTTP completamente (Solo HTTPS)

Si solo quieres HTTPS (443) y el puerto 443 está libre:

#### Modificar docker-compose:

1. **En Portainer** → **Tu stack** → **Editor**

2. **Buscar la sección del servicio nginx:**
   ```yaml
   nginx:
     ...
     ports:
       - "${DRAWIO_PUBLIC_PORT:-443}:443"
       - "${DRAWIO_HTTP_PORT:-80}:80"    # ⬅️ ELIMINAR ESTA LÍNEA
   ```

3. **Dejar solo:**
   ```yaml
   nginx:
     ...
     ports:
       - "${DRAWIO_PUBLIC_PORT:-443}:443"
   ```

4. **Update the stack**

**⚠️ Advertencia**: Sin el puerto 80, no habrá redirección automática HTTP → HTTPS. Los usuarios deberán escribir `https://` manualmente.

---

### SOLUCIÓN 4: Usar Nginx existente como reverse proxy

Si ya tienes Nginx o Apache corriendo y lo necesitas, puedes configurarlo como proxy:

#### Nginx existente:

Crear archivo `/etc/nginx/sites-available/drawio`:

```nginx
server {
    listen 80;
    server_name tu-dominio.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name tu-dominio.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:8443;  # Puerto interno del contenedor
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Luego:
```bash
sudo ln -s /etc/nginx/sites-available/drawio /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

Y en el docker-compose, cambiar los puertos del nginx a internos:
```yaml
ports:
  - "8443:443"  # Solo accesible desde localhost
```

---

## 🚀 Recomendación Rápida

**La más sencilla es SOLUCIÓN 1**: Detener el servicio que no necesitas.

```bash
# Detener Apache (el más común)
sudo systemctl stop apache2
sudo systemctl disable apache2

# Verificar
sudo lsof -i :80
# Debería no mostrar nada

# Volver a Portainer y re-desplegar
```

---

## 📋 Después de solucionar

Una vez que el puerto 80 esté libre:

1. **En Portainer** → **Stacks** → **ausarta-drawio** → **Redeploy**
2. Esperar a que inicie
3. Verificar:
   ```bash
   docker ps --filter "name=ausarta-drawio"
   curl http://localhost    # Debería redirigir a HTTPS
   ```

---

¿Cuál servicio está usando el puerto 80? Ejecuta `sudo lsof -i :80` y dime qué te aparece, te ayudo a detenerlo de forma segura.
