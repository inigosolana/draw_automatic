---
name: draw-deploy
description: Despliega y verifica la app draw_automatic (contenedor ausarta-drawio) tras cambios en el código. Úsala SIEMPRE que haya que desplegar, reconstruir, reiniciar, "subir los cambios al contenedor", comprobar si algo ya está en producción, o averiguar por qué un cambio no se ve en https://draw.ausarta.net — incluso si el usuario solo pregunta "¿está desplegado?" o dice "no me sale el cambio". Contiene los tres gotchas que hacen perder tiempo: el rootfs de solo lectura, el /health que devuelve 403 desde el host, y la caché de 12 h del JS en el navegador.
---

# Desplegar draw_automatic

El código se **hornea en la imagen** (`COPY` en el Dockerfile). No hay bind mount del
código, así que editar ficheros en el host no cambia nada en el contenedor: hasta que no
se reconstruye la imagen, la web sigue sirviendo lo viejo.

## Despliegue estándar

```bash
cd /home/ubuntu/draw_automatic && docker compose build drawio-generator && docker compose up -d
```

Contenedores: `ausarta-drawio` (la app), más `ausarta-drawio-redis` y
`ausarta-drawio-backup`, que no hace falta tocar.

## Verificar que ha subido de verdad

Tres comprobaciones, de menos a más concluyente. Interesa la tercera: el contenedor puede
estar `healthy` sirviendo la imagen anterior si el build no se hizo.

```bash
docker ps --filter name=ausarta-drawio --format '{{.Names}}  {{.Status}}  (creado {{.RunningFor}})'
docker exec ausarta-drawio python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=10).read().decode())"
docker exec ausarta-drawio sh -c "grep -c '<una cadena que solo exista en el cambio nuevo>' /app/ruta/al/fichero.py"
```

Para ficheros estáticos, comparar el hash del host con el del contenedor es la prueba más
directa de que se sirve el código nuevo:

```bash
docker exec ausarta-drawio md5sum /app/static/js/creation-form-terminals.js
md5sum static/js/creation-form-terminals.js
```

## Los tres gotchas

**`/health` da 403 desde el host.** nginx filtra por IP (`allow`/`deny all`), así que un
`curl http://127.0.0.1:8000/health` desde el host no prueba nada. Hay que consultarlo
**desde dentro** del contenedor, como arriba. Un 403 no significa que la app esté caída.

**El rootfs del contenedor es de solo lectura.** `docker cp` a `/app` falla. Si hace falta
colar un script sin reconstruir, el único sitio escribible es el volumen `/app/data`.
Para ejecutar código puntual contra el código ya desplegado, lo más limpio es pasarlo por
stdin (no toca disco):

```bash
docker exec -i -e PYTHONPATH=/app ausarta-drawio python - <<'EOF'
from generator.glpi_client import GlpiClient
print(GlpiClient.from_environment() is not None)
EOF
```

Sin `PYTHONPATH=/app` sale `ModuleNotFoundError: app_factory` (o `generator`).

**El navegador cachea el JS 12 h.** En producción `SEND_FILE_MAX_AGE_DEFAULT=43200`. Tras
desplegar un cambio de frontend, decirle al usuario que recargue con **Ctrl+F5**; si no,
jurará que el arreglo no funciona. Las URLs de `static/` van versionadas por hash, pero la
recarga forzada evita discusiones.

## Cuándo NO hace falta reconstruir

Cambios que no afectan al runtime: quitar imports sin usar, comentarios, documentación,
tests. Si el cambio altera cualquier cosa que se ejecute o se sirva, hay que reconstruir.

## Antes de dar por bueno un despliegue

Verificar el comportamiento concreto que se arregló, no solo que el contenedor arranque.
Lo más valioso es reproducir el caso real contra el contenedor desplegado — por ejemplo
reimportar la orden de trabajo que fallaba y ver el dato correcto. Un `healthy` solo dice
que el proceso vive.

Si el despliegue va acompañado de cambios en el repo, recordar que **desplegar no es
commitear**: el flujo de Portainer reconstruye desde `main` en GitHub, así que un cambio
desplegado pero sin push desaparece en la siguiente reconstrucción desde ahí.
