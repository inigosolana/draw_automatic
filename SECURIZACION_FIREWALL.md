# SECURIZACIÓN URGENTE - Portainer y Firewall

## 🔴 PASO 1: Configurar Firewall AHORA (UFW)

Esto bloqueará TODOS los puertos excepto los que tú permitas explícitamente.

### Instalar y configurar UFW:

```bash
# Instalar UFW (si no está instalado)
sudo apt update
sudo apt install ufw -y

# IMPORTANTE: Permitir SSH primero para no perder acceso
sudo ufw allow 22/tcp
sudo ufw allow ssh

# Permitir solo HTTPS (no HTTP por ahora)
sudo ufw allow 443/tcp

# Denegar todo lo demás por defecto
sudo ufw default deny incoming
sudo ufw default allow outgoing

# Activar firewall
sudo ufw enable

# Verificar estado
sudo ufw status verbose
```

**Resultado**: Ahora SOLO los puertos 22 (SSH) y 443 (HTTPS) están abiertos. Portainer 9000 ya NO es accesible desde internet.

---

## 🔴 PASO 2: Acceder a Portainer de Forma Segura

Tienes 3 opciones (de más a menos segura):

### OPCIÓN A: Túnel SSH (MÁS SEGURO - Recomendado)

Portainer solo accesible desde tu IP mediante un túnel:

```bash
# Desde tu ordenador Windows/local
ssh -L 9443:localhost:9000 tu-usuario@tu-servidor

# Ahora accede a Portainer en tu navegador local:
# http://localhost:9443
```

**Ventaja**: Portainer NUNCA está expuesto a internet, imposible atacar.

---

### OPCIÓN B: Restricción por IP en el Firewall

Solo tu IP puede acceder a Portainer:

```bash
# Reemplaza TU_IP_PUBLICA con tu IP real
# Descubre tu IP en: https://ifconfig.me/

sudo ufw allow from TU_IP_PUBLICA to any port 9000 proto tcp

# Ejemplo:
# sudo ufw allow from 203.0.113.45 to any port 9000 proto tcp

# Verificar
sudo ufw status numbered
```

**Ventaja**: Solo tú puedes acceder, pero si tu IP cambia, perderás acceso.

---

### OPCIÓN C: VPN (Profesional)

Instalar WireGuard o OpenVPN y solo permitir acceso a Portainer desde la VPN.

Puedo ayudarte con esto si lo prefieres.

---

## 🔴 PASO 3: Cambiar Puerto de Portainer (9000 → 9443)

El puerto 9000 es muy conocido por atacantes. Cambiarlo añade una capa extra:

```bash
# Detener Portainer actual
docker stop portainer
docker rm portainer

# Reiniciar con puerto diferente y HTTPS
docker run -d \
  -p 127.0.0.1:9443:9443 \
  --name portainer \
  --restart=always \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v portainer_data:/data \
  portainer/portainer-ce:latest \
  --ssl \
  --sslcert /certs/cert.pem \
  --sslkey /certs/key.pem

# Nota: Usa --ssl solo si tienes certificados
# Si no, quita esas líneas
```

**IMPORTANTE**: Nota el `127.0.0.1:9443` - esto hace que Portainer SOLO sea accesible desde localhost (túnel SSH).

---

## 🔴 PASO 4: Solucionar el Puerto 80 SIN Abrirlo

### Estrategia: Detener el servicio en el puerto 80, usar solo HTTPS (443)

```bash
# 1. Detener Apache/Nginx
sudo systemctl stop apache2  # o nginx
sudo systemctl disable apache2

# 2. Verificar que 80 está libre
sudo lsof -i :80

# 3. Re-desplegar en Portainer (ahora funcionará)
# El puerto 80 solo estará abierto INTERNAMENTE para redirección

# 4. Configurar firewall para SOLO permitir 443 desde internet
sudo ufw status
# Debería mostrar:
# 22/tcp   ALLOW       Anywhere
# 443/tcp  ALLOW       Anywhere
```

**Resultado**: El contenedor usa el puerto 80 internamente para redirigir a HTTPS, pero el firewall bloquea el 80 desde internet. Solo 443 está abierto.

---

## 🔥 CONFIGURACIÓN COMPLETA DE FIREWALL (Copy-Paste)

```bash
#!/bin/bash
# Script de configuración de firewall seguro

# Instalar UFW
sudo apt update && sudo apt install ufw -y

# Reset (cuidado, esto borra reglas existentes)
sudo ufw --force reset

# Reglas por defecto
sudo ufw default deny incoming
sudo ufw default allow outgoing

# Permitir SSH (CAMBIAR 22 si usas otro puerto)
sudo ufw allow 22/tcp

# Permitir HTTPS (aplicación web)
sudo ufw allow 443/tcp

# Opcional: Permitir HTTP solo si lo necesitas
# sudo ufw allow 80/tcp

# Portainer: Solo desde tu IP (CAMBIAR TU_IP)
# Opción 1: Restringir por IP
# sudo ufw allow from TU_IP_PUBLICA to any port 9443 proto tcp

# Opción 2: No permitir desde internet (solo túnel SSH)
# No añadir ninguna regla para Portainer

# Activar firewall
sudo ufw --force enable

# Ver estado
sudo ufw status verbose

echo "Firewall configurado correctamente"
echo "Puertos abiertos: 22 (SSH), 443 (HTTPS)"
echo "Portainer: Solo accesible via túnel SSH"
```

---

## 🛡️ CONFIGURACIÓN ADICIONAL: Fail2Ban

Para proteger contra ataques de fuerza bruta en SSH:

```bash
# Instalar Fail2Ban
sudo apt install fail2ban -y

# Configurar
sudo systemctl enable fail2ban
sudo systemctl start fail2ban

# Verificar que está corriendo
sudo fail2ban-client status
```

---

## 📊 RESUMEN DE SEGURIDAD

### ANTES:
```
❌ Puerto 22 (SSH) → Abierto a todo el mundo
❌ Puerto 80 (HTTP) → Abierto
❌ Puerto 443 (HTTPS) → Abierto
❌ Puerto 9000 (Portainer) → EXPUESTO (MUY PELIGROSO)
```

### DESPUÉS:
```
✅ Puerto 22 (SSH) → Abierto pero protegido con Fail2Ban
✅ Puerto 443 (HTTPS) → Abierto (necesario para la app)
✅ Puerto 80 (HTTP) → Bloqueado por firewall (interno solo)
✅ Puerto 9000 (Portainer) → BLOQUEADO, solo túnel SSH
```

---

## 🔐 ACCESO SEGURO A PORTAINER

### Desde tu ordenador Windows:

```powershell
# PowerShell o CMD
ssh -L 9443:localhost:9443 tu-usuario@tu-servidor

# Mantén esta ventana abierta
# En tu navegador:
https://localhost:9443
```

---

## 🎯 PLAN DE ACCIÓN INMEDIATO

Ejecuta estos comandos en orden:

```bash
# 1. Configurar firewall
sudo apt install ufw -y
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# 2. Verificar firewall
sudo ufw status verbose

# 3. Detener servicio en puerto 80
sudo systemctl stop apache2
sudo systemctl disable apache2

# 4. Verificar puertos abiertos
sudo ss -tlnp | grep -E ':(22|80|443|9000)'

# 5. Re-desplegar en Portainer
# (desde la interfaz web de Portainer)
```

---

## ⚡ SI PIERDES ACCESO AL SERVIDOR

Si el firewall te bloquea el SSH (poco probable pero posible):

1. Accede por consola de tu proveedor (DigitalOcean, AWS, etc.)
2. Ejecuta: `sudo ufw disable`
3. Reconecta por SSH
4. Reconfigura con `sudo ufw allow 22/tcp` antes de reactivar

---

¿Quieres que te ayude a ejecutar estos pasos uno por uno? Empezamos con el firewall primero (lo más crítico).
