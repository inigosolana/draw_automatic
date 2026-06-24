# Despliegue interno (equipo técnico, sin exposición pública)

Objetivo: que los compañeros usen la app, pero **sin abrir puertos** al mundo. Solo acceso desde IPs de confianza (oficina / VPN) por HTTPS.

## Variantes de docker-compose

| Fichero | Cuándo usarlo |
|---|---|
| `docker-compose.yml` | Desarrollo local estándar |
| `docker-compose.host-nginx.yml` | Producción con nginx en el host |
| `docker-compose.portainer.yml` | Gestión vía Portainer con red externa |
| `docker-compose.portainer-internal.yml` | Portainer con nginx interno en el stack |

## Arquitectura recomendada

```
Técnico (IP permitida)
        │
        ▼
  Nginx del servidor :443  ← allow/deny por IP
        │
        ▼
  127.0.0.1:8000  ← contenedor Docker (Portainer)
```

- **No** uses `docker-compose.portainer.yml` (expone 80/443 a `0.0.0.0`).
- **Sí** usa `docker-compose.portainer-internal.yml` (solo `127.0.0.1:8000`).

---

## 1. Portainer — desplegar desde GitHub

### Requisito previo

El código debe estar en GitHub. Repositorio:

**https://github.com/inigosolana/draw_automatic**

Si acabas de cambiar cosas en local, súbelas antes:

```bash
git add .
git commit -m "Despliegue interno, importar oferta y campo IP terminal"
git push origin main
```

### Crear el stack en Portainer

1. Entra a Portainer → **Stacks** → **Add stack**
2. **Name:** `ausarta-drawio`
3. **Build method:** **Git repository**
4. Rellena:

| Campo | Valor |
|--------|--------|
| **Repository URL** | `https://github.com/inigosolana/draw_automatic` |
| **Repository reference** | `refs/heads/main` |
| **Compose path** | `docker-compose.portainer-internal.yml` |
| **Authentication** | Si el repo es privado: usuario GitHub + [Personal Access Token](https://github.com/settings/tokens) con permiso `repo` |

5. **Environment variables** — pulsa *Advanced mode* o añade una a una:

```
GLPI_URL=http://51.94.34.76/apirest.php
GLPI_WEB_URL=http://51.94.34.76
GLPI_APP_TOKEN=tu_token
GLPI_USER_TOKEN=tu_token
DRAWIO_SECRET_KEY=genera_una_clave_larga
DRAWIO_AUTH_REQUIRED=1
DRAWIO_COOKIE_SECURE=1
```

Generar `DRAWIO_SECRET_KEY` en el servidor:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

6. **Deploy the stack**

Portainer clona el repo, construye la imagen Docker y levanta app + Redis. La primera vez tarda **2–5 minutos**.

### Comprobar

En el servidor (SSH):

```bash
curl -s http://127.0.0.1:8000/health
```

Debe responder: `{"status":"ok"}`

### Actualizar después de un `git push`

Portainer → **Stacks** → `ausarta-drawio` → **Pull and redeploy** (o **Update the stack** → **Re-pull image and redeploy**).

---

## 1b. Portainer — alternativa sin Git (Web editor)

| Variable | Valor |
|----------|--------|
| `GLPI_URL` | URL API GLPI |
| `GLPI_WEB_URL` | URL web GLPI |
| `GLPI_APP_TOKEN` | token app |
| `GLPI_USER_TOKEN` | token usuario |
| `DRAWIO_SECRET_KEY` | clave aleatoria larga |

Generar clave:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

4. **Deploy the stack**

Comprobar en el servidor:

```bash
curl -s http://127.0.0.1:8000/health
# {"status":"ok"}
```

Desde fuera del servidor **no** debe responder el 8000.

---

## 2. Nginx del servidor (puerta de entrada filtrada)

Copia la plantilla:

```bash
sudo cp deploy/nginx-draw.ausarta.net.conf /etc/nginx/sites-available/draw.ausarta.net
```

Edita y pon las **IPs públicas** de los técnicos (una línea `allow` por IP):

```nginx
allow 45.141.240.254;   # ejemplo: tu IP
allow 203.0.113.50;     # otro técnico
deny all;
```

Certificado autofirmado (como Portainer, sin abrir puerto 80):

```bash
sudo mkdir -p /etc/nginx/ssl
sudo openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/draw.key \
  -out /etc/nginx/ssl/draw.crt \
  -subj "/CN=draw.ausarta.net"
```

Activar sitio:

```bash
sudo ln -sf /etc/nginx/sites-available/draw.ausarta.net /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

DNS (opcional): registro `draw.ausarta.net` → IP del servidor. Aunque el DNS sea público, **solo entran las IPs del `allow`**.

---

## 3. Firewall (UFW / AWS)

**Permitir:** 443 (nginx), 22 (SSH).

**No permitir:** 8000, 8085, 9000 hacia Internet.

En AWS Security Group: igual — solo 443 (y 22 si aplica), **no** 8000.

---

## 4. Cómo acceden los técnicos

1. Abrir **`https://draw.ausarta.net`** (o la IP del servidor si no hay DNS).
2. Aceptar aviso de certificado autofirmado (solo la primera vez).
3. Login con **usuario y clave de acceso** corporativos.

Si alguien no está en la lista `allow`, verá **403 Forbidden**.

---

## 5. Alternativa: túnel SSH (pruebas)

```bash
ssh -L 8000:127.0.0.1:8000 ubuntu@TU_SERVIDOR
```

Luego: `http://127.0.0.1:8000` en el navegador del técnico.

---

## Qué NO hacer

| Evitar | Motivo |
|--------|--------|
| `ports: "8000:8000"` en `0.0.0.0` | Expone la app a Internet |
| Abrir 8000 en UFW | Bypass del nginx con filtro |
| `docker-compose.portainer.yml` sin cambiar puertos | Nginx del contenedor en todas las interfaces |
