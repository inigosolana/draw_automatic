from __future__ import annotations

import re


_SENSITIVE_PATTERN = re.compile(
    r"(password|contraseña|passwd|token|secret|authorization|app-token|session-token|"
    r"user_token|api[_-]?key|credential|credencial|bearer\s+\S+)",
    re.IGNORECASE,
)


def public_error_message(message: str, *, context: str = "operacion") -> str:
    text = " ".join(str(message or "").split()).strip()
    if not text:
        return f"No se ha podido completar la {context}."
    if _SENSITIVE_PATTERN.search(text):
        return f"No se ha podido completar la {context}. Revisa la configuracion o las credenciales."
    _json_markers = ('{"', '[{', '<html', '<?xml')
    if len(text) > 180 or any(marker in text for marker in _json_markers):
        return f"No se ha podido completar la {context}."
    if "GLPI" not in text.upper():
        return f"No se ha podido completar la {context}."
    return text
