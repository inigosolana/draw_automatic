# Composes obsoletos — NO USAR

Estos ficheros se conservan solo como referencia histórica. **No deben usarse
para desplegar** en el servidor de producción.

- `docker-compose.portainer.yml` — publicaba `0.0.0.0:443/80` (peligroso: expone
  la app y un nginx propio al exterior, choca con el nginx del host).
- `docker-compose.portainer-internal.yml` — publicaba el puerto `8000` (obsoleto;
  el nginx del host hace proxy a `8015`, no a `8000`).

## Despliegue real

El único fichero canónico es `docker-compose.yml` en la raíz del repo. Sirve la
app en `127.0.0.1:8015` para el **nginx del host** (systemd) que termina TLS en
443 con Let's Encrypt (`certbot.timer`). Ese compose NO levanta nginx ni certbot.

```
cd /home/ubuntu/draw_automatic && docker compose up -d --build
```
