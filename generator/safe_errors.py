from __future__ import annotations

import re


_SENSITIVE_PATTERN = re.compile(
    r"(password|contraseña|passwd|token|secret|authorization|app-token|session-token|"
    r"user_token|api[_-]?key|credential|credencial|bearer\s+\S+)",
    re.IGNORECASE,
)


_CODE_PATTERN = re.compile(r"\bcodigo (\d{3})\b", re.IGNORECASE)


def _friendly_message(text: str) -> str | None:
    """Traduce fallos técnicos conocidos a un mensaje claro y accionable para
    el técnico (qué pasó y qué hacer). Devuelve None si no hay traducción."""
    low = text.lower()
    if "no se ha podido conectar con glpi" in low or "no se ha podido consultar glpi" in low:
        return (
            "No se ha podido conectar con GLPI. Comprueba que GLPI está accesible "
            "e inténtalo de nuevo en unos minutos."
        )
    if "no esta configurado" in low and "glpi" in low:
        return "GLPI no está configurado en el servidor. Avisa a sistemas para revisar la conexión."
    if "lista de equipos" in low:
        # Mensaje ya construido explicando qué pasa y a quién avisar; se deja
        # pasar tal cual (si no, el filtro de longitud/JSON lo sustituiría por
        # uno genérico que no ayuda a diagnosticar el problema en comms).
        return text
    match = _CODE_PATTERN.search(low)
    if match:
        code = match.group(1)
        if code.startswith("5"):
            return (
                "GLPI ha tenido un error interno y no ha podido completar la operación. "
                "Inténtalo de nuevo en unos minutos; si sigue fallando, avisa a sistemas."
            )
        if code in ("401", "403"):
            return "GLPI ha rechazado el acceso. Revisa los permisos o el token de GLPI con sistemas."
        if code == "404":
            return "GLPI no encuentra ese recurso. Puede que el diagrama o la sede ya no exista."
        if code.startswith("4"):
            if any(k in low for k in ("exist", "duplicad", "duplicate", "already", "ya existe")):
                return (
                    "GLPI dice que ese diagrama ya existe para la sede. Revisa en GLPI si ya está subido; "
                    "si quieres otra copia, cámbiale el nombre antes de subirlo."
                )
            if any(k in low for k in ("too large", "demasiado", "max", "size", "length", "longitud", "payload")):
                return (
                    "GLPI ha rechazado el diagrama por tamaño. Es demasiado grande: simplifícalo "
                    "(menos elementos) o súbelo en partes."
                )
            return (
                "GLPI ha rechazado el diagrama (código 400). Suele pasar si ya está subido para esa sede "
                "o si algún dato no es válido. Revisa en GLPI si ya aparece; si no, cámbiale el nombre e "
                "inténtalo de nuevo. Si vuelve a fallar, avisa a sistemas con la hora y el nombre del archivo."
            )
    return None


def public_error_message(message: str, *, context: str = "operacion") -> str:
    text = " ".join(str(message or "").split()).strip()
    if not text:
        return f"No se ha podido completar la {context}."
    if _SENSITIVE_PATTERN.search(text):
        return f"No se ha podido completar la {context}. Revisa la configuracion o las credenciales."
    friendly = _friendly_message(text)
    if friendly:
        return friendly
    _json_markers = ('{"', '[{', '<html', '<?xml')
    if len(text) > 180 or any(marker in text for marker in _json_markers):
        return f"No se ha podido completar la {context}."
    if "GLPI" not in text.upper():
        return f"No se ha podido completar la {context}."
    return text
