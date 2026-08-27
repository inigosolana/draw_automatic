from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .utils import MADRID_TZ, now_madrid


def format_activity_timestamp(created_at: float | None) -> str:
    if created_at is None:
        return ""
    try:
        return datetime.fromtimestamp(created_at, MADRID_TZ).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def diagram_source_meta(source: str) -> dict[str, str]:
    normalized = (source or "").strip().lower()
    if normalized in {"draw subido", "archivo antiguo"}:
        return {
            "key": "subido",
            "label": "Subido",
            "description": "Archivo .drawio subido manualmente",
            "badge_class": "source-badge-upload",
        }
    if normalized == "version":
        return {
            "key": "version",
            "label": "Version",
            "description": "Copia guardada al editar un diagrama en GLPI",
            "badge_class": "source-badge-version",
        }
    if normalized == "glpi":
        return {
            "key": "glpi",
            "label": "En GLPI",
            "description": "Guardado en GLPI. Puedes previsualizarlo aquí sin entrar a GLPI.",
            "badge_class": "source-badge-version",
        }
    return {
        "key": "generado",
        "label": "Generado",
        "description": "Creado desde la app draw.io",
        "badge_class": "source-badge-generated",
    }


def build_diagram_description(
    *,
    client_name: str,
    site_name: str,
    technician: dict,
    source: str,
    filename: str = "",
) -> str:
    technician = technician or {}
    tech = (technician.get("name") or technician.get("username") or "desconocido").strip()
    when = now_madrid().strftime("%d/%m/%Y %H:%M")
    parts = [source, when, tech, f"{client_name} - {site_name}"]
    if filename:
        parts.insert(1, Path(filename).name[:24])
    return " | ".join(parts)[:100]


# Limite REAL de la columna `glpi_plugin_archimap_graphs.name` en GLPI,
# verificado contra el servidor: 45 acepta, 46 responde
# "ERROR_GLPI_ADD Data too long for column 'name'". Ademas la columna tiene
# indice UNIQUE GLOBAL (name_UNIQUE), no por sede: dos sedes del mismo cliente
# no pueden compartir nombre. Por eso el nombre no se puede truncar a lo bruto
# (el "Sede N" del final se perdia y todas las sedes colisionaban): hay que
# comprimirlo conservando lo que distingue una sede de otra.
GLPI_NAME_MAX = 45

_SEDE_RE = re.compile(r"\bSEDE[\s_-]*0*(\d+)\b", re.IGNORECASE)
# Palabras que introducen una via: marcan donde acaba el cliente y empieza la
# direccion.
_VIA_WORDS = {
    "CALLE", "C", "AVDA", "AVENIDA", "AV", "PLAZA", "PZA", "PL", "POLIGONO",
    "POL", "CARRETERA", "CTRA", "PASEO", "PS", "BARRIO", "BARRIADA", "CAMINO",
    "RONDA", "TRAVESIA", "PARQUE", "RUA", "BIDEA", "KALEA", "ETORBIDEA",
}
_VIA_ABBR = {
    "CALLE": "C/", "AVENIDA": "Av", "AVDA": "Av", "AV": "Av", "PLAZA": "Pl",
    "PZA": "Pl", "POLIGONO": "Pol", "POL": "Pol", "CARRETERA": "Ctra",
    "CTRA": "Ctra", "PASEO": "Ps", "BARRIO": "Bo", "BARRIADA": "Bo",
    "TRAVESIA": "Tv", "CAMINO": "Cno", "PARQUE": "Pq",
}
# Relleno del nombre del cliente: se cae primero, no identifica nada.
_CLIENT_FILLER = {
    "DE", "DEL", "LA", "EL", "LOS", "LAS", "Y", "EN", "SA", "SL", "SLU",
    "SLL", "SCOOP", "COOP", "SC", "CB", "SOCIEDAD", "LIMITADA", "ANONIMA",
}
_CLIENT_ABBR = {
    "ASOCIACION": "ASOC", "FUNDACION": "FUND", "AYUNTAMIENTO": "AYTO",
    "SERVICIOS": "SERV", "COOPERATIVA": "COOP", "INDUSTRIAS": "IND",
    "INDUSTRIAL": "IND", "HERMANOS": "HNOS", "CENTRO": "CTRO",
    "ADMINISTRACION": "ADMON", "CONSTRUCCIONES": "CONSTR",
    "DISTRIBUCIONES": "DISTR", "TRANSPORTES": "TRANSP",
    "TELECOMUNICACIONES": "TELECOM", "INTERNACIONAL": "INTL",
}


def _tokens(text: str) -> list[str]:
    return [tok for tok in re.split(r"[\s_]+", (text or "").strip()) if tok]


def _split_name_parts(raw_name: str) -> tuple[list[str], list[str], str]:
    """Parte un nombre crudo en (cliente, direccion, sede).

    La sede se busca en cualquier posicion (los ficheros la llevan al final,
    los nombres generados al principio) y se extrae del resto.
    """
    # Los guiones bajos van a espacio ANTES de buscar la sede: en regex `_` es
    # parte de \w, asi que "..._SEDE_2" no tiene frontera \b delante de SEDE y
    # la sede se quedaba sin detectar (que es como todas las sedes de un mismo
    # cliente acababan compartiendo nombre).
    text = diagram_base_name(raw_name).replace("_", " ")
    sede = ""
    match = _SEDE_RE.search(text)
    if match:
        sede = f"Sede {int(match.group(1))}"
        text = (text[: match.start()] + " " + text[match.end() :]).strip(" -_")
    tokens = _tokens(text)
    # Un separador " - " tras el cliente es la pista mas fiable; si no hay,
    # buscamos la palabra de via y, en su defecto, el primer numero (portal).
    cut = None
    for index, token in enumerate(tokens):
        if token == "-" and index:
            cut = index + 1
            break
    if cut is None:
        for index, token in enumerate(tokens):
            if token.strip(".,").upper() in _VIA_WORDS and index:
                cut = index
                break
    if cut is None:
        # Sin palabra de via, el portal es la unica pista. Retrocedemos hasta
        # dos palabras para no dejar el numero huerfano ("13 BARAKALDO" en vez
        # de "SAN JUAN 13").
        for index, token in enumerate(tokens):
            if any(ch.isdigit() for ch in token) and index:
                cut = max(1, index - 2)
                break
    if cut is None:
        return [tok for tok in tokens if tok != "-"], [], sede
    client = [tok for tok in tokens[:cut] if tok != "-"]
    address = [tok for tok in tokens[cut:] if tok != "-"]
    return client, address, sede


def _drop_municipality(address: list[str]) -> list[str]:
    """Quita el municipio final: ya lo identifica la entidad GLPI de la sede.

    Solo lo hace si detrás del numero de portal queda algo mas, para no
    dejarse por el camino el propio nombre de la via.
    """
    numeric = [i for i, tok in enumerate(address) if any(ch.isdigit() for ch in tok)]
    if numeric and numeric[-1] < len(address) - 1:
        return address[: numeric[-1] + 1]
    return address


def _assemble(client: list[str], address: list[str], sede: str) -> str:
    head = " ".join(client).strip()
    tail = " ".join(part for part in (sede, " ".join(address).strip()) if part).strip()
    if head and tail:
        return f"{head} - {tail}"
    return head or tail


def fit_diagram_name(raw_name: str, max_len: int = GLPI_NAME_MAX) -> str:
    """Comprime un nombre de diagrama para que quepa en `max_len` caracteres.

    Se reescribe por partes en vez de cortar por el caracter N, con este orden
    de prioridad (lo que se conserva hasta el final): numero de SEDE, via y
    portal, cliente, municipio. Asi dos sedes del mismo cliente nunca acaban
    con el mismo nombre, que es lo que hacia que GLPI rechazara la segunda por
    `Duplicate entry`.
    """
    raw = (raw_name or "").strip()
    if len(raw) <= max_len:
        return raw
    client, address, sede = _split_name_parts(raw)
    candidates = [_assemble(client, address, sede)]

    address = _drop_municipality(address)
    candidates.append(_assemble(client, address, sede))

    client = [tok for tok in client if tok.strip(".,").upper() not in _CLIENT_FILLER] or client
    candidates.append(_assemble(client, address, sede))

    client = [_CLIENT_ABBR.get(tok.strip(".,").upper(), tok) for tok in client]
    address = [_VIA_ABBR.get(tok.strip(".,").upper(), tok) for tok in address]
    candidates.append(_assemble(client, address, sede))

    # Ultimo recurso antes de recortar: menos palabras de cliente, nunca cero.
    for keep in (3, 2, 1):
        if len(client) > keep:
            candidates.append(_assemble(client[:keep], address, sede))

    for candidate in candidates:
        if candidate and len(candidate) <= max_len:
            return candidate
    # Si nada cabe, se recorta el CLIENTE: la sede y el portal son lo que
    # distingue una sede de otra, asi que se reservan primero.
    tail = " ".join(part for part in (sede, " ".join(address)) if part).strip()
    if len(tail) > max_len:
        tail = (sede or tail)[:max_len].strip()
    head = " ".join(client[:1])
    room = max_len - len(tail) - 3  # 3 = separador " - "
    if not head or room < 3:
        return tail[:max_len].rstrip(" -")
    return f"{head[:room].rstrip(' -_')} - {tail}"[:max_len].rstrip(" -")


def unique_diagram_name(base_name: str, existing_diagrams: list[dict]) -> str:
    base = fit_diagram_name(base_name.strip())
    if not existing_diagrams:
        return base
    existing_names = {str(item.get("name", "")).strip().lower() for item in existing_diagrams}
    if base.lower() not in existing_names:
        return base
    return suffixed_diagram_name(base, existing_names)


def suffixed_diagram_name(base: str, taken: set[str] | None = None) -> str:
    """Reescribe `base` con un sufijo de fecha-hora para esquivar un duplicado.

    Si el nombre con sello tambien esta cogido (dos subidas en el mismo
    minuto), añade un contador. El resultado siempre cabe en GLPI_NAME_MAX.
    """
    taken = {name.strip().lower() for name in (taken or set())}
    stamp = now_madrid().strftime("%d%m%y-%H%M")
    for attempt in range(1, 100):
        mark = stamp if attempt == 1 else f"{stamp}-{attempt}"
        trimmed = base[: max(1, GLPI_NAME_MAX - len(mark) - 1)].rstrip(" -_")
        candidate = f"{trimmed} {mark}"[:GLPI_NAME_MAX]
        if candidate.lower() not in taken:
            return candidate
    return f"{base[: GLPI_NAME_MAX - len(stamp) - 1]} {stamp}"[:GLPI_NAME_MAX]


_VERSION_SUFFIX_RE = re.compile(r"_\d{8}_\d{6}$")
_LEGACY_VERSION_SUFFIX_RE = re.compile(r" \d{6}\d{2}-\d{4}$")


def diagram_base_name(name: str) -> str:
    stem = Path(name).stem if name else ""
    stem = stem.strip()
    while stem:
        if _VERSION_SUFFIX_RE.search(stem):
            stem = _VERSION_SUFFIX_RE.sub("", stem)
            continue
        legacy = _LEGACY_VERSION_SUFFIX_RE.search(stem)
        if legacy:
            stem = stem[: legacy.start()].rstrip()
            continue
        break
    return stem.strip() or "diagrama"


def versioned_diagram_name(base_name: str, when: datetime | None = None) -> str:
    when = when or now_madrid()
    suffix = when.strftime("_%Y%m%d_%H%M%S")
    base = diagram_base_name(base_name)
    max_len = max(1, GLPI_NAME_MAX - len(suffix))
    # Comprimido, no cortado: si no, la copia fechada perdia el "Sede N" del
    # final y dos sedes del mismo cliente daban el mismo nombre de version.
    trimmed = fit_diagram_name(base, max_len).rstrip("_ ").strip()
    return f"{trimmed or 'diagrama'}{suffix}"


def versioned_drawio_filename(base_name: str, when: datetime | None = None) -> str:
    return f"{versioned_diagram_name(base_name, when=when)}.drawio"


def enrich_activity_rows(rows: list[dict], client) -> list[dict]:
    enriched: list[dict] = []
    for item in rows:
        row = dict(item)
        row["created_label"] = format_activity_timestamp(row.get("created_at"))
        row["technician"] = row.get("technician_name") or row.get("technician_username") or "—"
        diagram_id = row.get("diagram_id")
        row["url"] = ""
        if client and diagram_id:
            try:
                row["url"] = client.diagram_url(int(diagram_id))
            except (TypeError, ValueError):
                row["url"] = ""
        source_meta = diagram_source_meta(row.get("source", ""))
        row["source_key"] = source_meta["key"]
        row["source_label"] = source_meta["label"]
        row["source_description"] = source_meta["description"]
        row["source_badge_class"] = source_meta["badge_class"]
        enriched.append(row)
    return enriched


def enrich_diagram_row(diagram: dict, activity_by_id: dict[int, dict]) -> dict:
    row = dict(diagram)
    activity = activity_by_id.get(int(row.get("id") or row.get("diagram_id") or 0))
    if activity:
        row["created_label"] = format_activity_timestamp(activity["created_at"])
        row["technician"] = activity.get("technician_name") or activity.get("technician_username") or ""
        row["source"] = activity.get("source") or ""
    else:
        row["created_label"] = ""
        row["technician"] = ""
        row["source"] = "GLPI"
    source_meta = diagram_source_meta(row.get("source", ""))
    row["source_key"] = source_meta["key"]
    row["source_label"] = source_meta["label"]
    row["source_description"] = source_meta["description"]
    row["source_badge_class"] = source_meta["badge_class"]
    return row
