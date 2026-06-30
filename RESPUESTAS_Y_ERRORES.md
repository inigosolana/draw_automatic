# Patrón de respuestas y errores

Convención única para las vistas de `web/blueprints/`. El objetivo (directriz de
producto): **pocos fallos, y cuando los haya, avisar y decir qué pasa, en
español y accionable.**

## 1. Elegir el tipo de respuesta según quién la consume

| Quién pide | Tipo de respuesta | Cómo |
|---|---|---|
| Navegación de página (GET/POST que renderiza HTML) | Página completa | `render_template("index.html", **index_context(...))` |
| Fetch/AJAX del frontend (JS) | JSON | `jsonify({...})`, con código de estado explícito en error |
| Acción puntual con resultado de texto (descarga, confirmación, borrado) | Texto plano | `Response(texto, status=..., mimetype="text/plain; charset=utf-8")` |

Regla práctica: **si lo invoca `fetch()` desde JS → JSON; si es una navegación
del navegador → render o texto plano.** No mezclar (no devolver HTML a un
endpoint que el JS espera en JSON).

## 2. Mensajes de error: siempre por `public_error_message`

Cualquier error que venga de GLPI / red / parsing y vaya a llegar al usuario
pasa por `generator.safe_errors.public_error_message(str(exc), context="…")`.
Traduce códigos (5xx, 401/403/404, conexión) a un texto en español que dice
**qué pasó y qué hacer**, y evita filtrar trazas o URLs internas.

```python
try:
    ...llamada a GLPI...
except GlpiError as exc:
    return jsonify({"error": public_error_message(str(exc), context="consulta de diagramas")}), 502
```

- AJAX/JSON: `{"error": "<mensaje>"}` + código HTTP coherente (4xx/5xx).
- Texto plano: `Response(public_error_message(...), status=..., mimetype="text/plain; charset=utf-8")`.
- Página: `render_template(..., errors=[...])` con la lista `errors` que la
  plantilla pinta arriba del formulario.

## 3. Códigos de estado

- `400` validación de entrada del usuario (campo obligatorio, formato).
- `403` sin permisos (admin), `404` recurso no encontrado, `409` conflicto
  (p. ej. la sede ya tiene diagrama; reintentar confirma).
- `502` GLPI respondió error; `503` GLPI no está configurado.
- Rate limit: `429` (handler global en `app_factory`).

## 4. Logging de seguridad

Los fallos relevantes se registran con `security_logger` (incluyendo usuario e
IP cuando aplica) **además** de devolver el mensaje al usuario. El log es para
operación; el mensaje es para el técnico.
