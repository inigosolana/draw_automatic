from __future__ import annotations

import base64
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from .aliases import normalize_name, resolve_alias
from .knowledge_base import load_learned_items

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Cache del parseo pesado de la libreria (~13 MB de XML + iconos en base64).
# Se invalida solo cuando cambia el fichero (mtime/tamaño), de modo que un
# despliegue con nueva libreria se recoge sin reiniciar. Los iconos "aprendidos"
# NO se cachean aqui: se re-aplican en cada load_library() para que la base de
# conocimiento siga viva sin reinicio.
_BASE_CACHE: dict[str, tuple[tuple[int, int], list["LibraryItem"]]] = {}
_BASE_CACHE_LOCK = threading.Lock()
# Cache de validación por (mtime, size): validate_library_file releía el XML de
# ~13 MB + regex en cada /generate.
_VALIDATE_CACHE: dict[str, tuple[tuple[int, int], list[str]]] = {}
_VALIDATE_CACHE_LOCK = threading.Lock()


@dataclass
class LibraryItem:
    title: str
    data: str
    width: int
    height: int
    aspect: str = "fixed"


class LibraryIndex:
    def __init__(self, items: list[LibraryItem]) -> None:
        self.items = items
        self.by_title = {item.title: item for item in items}
        self.by_normalized = {normalize_name(item.title): item for item in items}

    def find(self, name: str) -> LibraryItem | None:
        candidates = [name]
        stripped = re.sub(r"^switch\s+", "", (name or "").strip(), flags=re.IGNORECASE)
        if stripped and stripped != name:
            candidates.append(stripped)
        for candidate in candidates:
            alias = resolve_alias(candidate)
            if alias in self.by_title:
                return self.by_title[alias]
            found = self.by_normalized.get(normalize_name(alias))
            if found:
                return found
        return None


def _load_local_icon(title: str, image_path: Path, width: int = 120, height: int = 120) -> LibraryItem | None:
    if not image_path.exists():
        return None
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return LibraryItem(title=title, data=f"data:image/png;base64,{encoded}", width=width, height=height)


def _looks_like_test_stub(entries: list[dict]) -> bool:
    if len(entries) < 10:
        return True
    for entry in entries[:5]:
        data = str(entry.get("data", ""))
        if len(data) < 200 or re.search(r"base64,[A-Z]{3}\"?", data):
            return True
    return False


def validate_library_file(path: str | Path) -> list[str]:
    library_path = Path(path)
    if not library_path.is_file():
        return [f"No se ha encontrado la libreria en {library_path}."]
    try:
        stat = library_path.stat()
        signature = (int(stat.st_mtime_ns), int(stat.st_size))
        key = str(library_path)
        with _VALIDATE_CACHE_LOCK:
            cached = _VALIDATE_CACHE.get(key)
            if cached and cached[0] == signature:
                return list(cached[1])
    except OSError:
        signature = key = None
    text = library_path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"<mxlibrary>(.*)</mxlibrary>", text, re.DOTALL)
    if not match:
        return ["La libreria no contiene un bloque <mxlibrary> valido."]
    try:
        entries = json.loads(match.group(1))
    except json.JSONDecodeError:
        return ["La libreria no contiene JSON valido."]
    warnings: list[str] = []
    if _looks_like_test_stub(entries):
        warnings.append(
            "La libreria parece ser la fixture de tests (iconos falsos). "
            "Copia la libreria real a library/libreria_Ausarta_JUN_2026.xml."
        )
    titles = {entry.get("title", "") for entry in entries}
    for required in ("ONT ZTE", "Microtik_hAPc", "T-31"):
        if required not in titles:
            warnings.append(f"Falta el icono obligatorio '{required}' en la libreria.")
    if signature is not None and key is not None:
        with _VALIDATE_CACHE_LOCK:
            _VALIDATE_CACHE[key] = (signature, list(warnings))
    return warnings


def _parse_base_items(library_path: Path) -> list[LibraryItem]:
    """Parsea el XML de la libreria + iconos locales. Parte cara (~13 MB)."""
    text = library_path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"<mxlibrary>(.*)</mxlibrary>", text, re.DOTALL)
    if not match:
        raise ValueError("No se ha encontrado <mxlibrary> en la libreria.")
    entries = json.loads(match.group(1))
    items: list[LibraryItem] = []
    for entry in entries:
        title = entry.get("title")
        data = entry.get("data")
        if not title or not data:
            continue
        items.append(
            LibraryItem(
                title=title,
                data=data,
                width=int(entry.get("w", 120)),
                height=int(entry.get("h", 120)),
                aspect=entry.get("aspect", "fixed"),
            )
        )

    for icon_title, icon_file in [
        ("W71H", "w71h.png"),
        ("W70B", "yealink_w70b.png"),
        ("Mikrotik wAP LTE", "mikrotik_wap_lte.png"),
        ("TELTONIKA", "teltonika.png"),
        ("Grandstream AP", "grandstream_ap.png"),
        ("MikroTik hAP ac3", "mikrotik_hap_ac3.png"),
    ]:
        custom_icon = _load_local_icon(icon_title, PROJECT_ROOT / "assets" / icon_file)
        if custom_icon:
            items.append(custom_icon)
    return items


def _cached_base_items(library_path: Path) -> list[LibraryItem]:
    """Devuelve los items base cacheados, re-parseando solo si cambia el fichero."""
    key = str(library_path)
    try:
        stat = library_path.stat()
        signature = (int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        # Si no podemos consultar el fichero, no cacheamos: parseamos directo.
        return _parse_base_items(library_path)
    with _BASE_CACHE_LOCK:
        cached = _BASE_CACHE.get(key)
        if cached and cached[0] == signature:
            return cached[1]
    items = _parse_base_items(library_path)
    with _BASE_CACHE_LOCK:
        _BASE_CACHE[key] = (signature, items)
    return items


def load_library(path: str | Path) -> LibraryIndex:
    library_path = Path(path)
    # Copia de la lista cacheada: los items aprendidos se añaden por encima sin
    # mutar la base compartida.
    items = list(_cached_base_items(library_path))
    known_titles = {normalize_name(item.title) for item in items}
    for entry in load_learned_items():
        title = entry.get("title", "")
        data = entry.get("data", "")
        if not title or not data or normalize_name(title) in known_titles:
            continue
        items.append(
            LibraryItem(
                title=title,
                data=data,
                width=int(entry.get("width", 120)),
                height=int(entry.get("height", 120)),
            )
        )
    return LibraryIndex(items)
