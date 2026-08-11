"""Emparejamiento difuso de nombres de host Zabbix ↔ clientes/sedes (ponderado IDF).

Un host de router en Zabbix se llama, p. ej.,
``FTTH_AIRE_CLIENTE_SEDE1_LOCALIDAD_CALLE`` y hay que reconocer a qué cliente/sede
pertenece (o si un cliente ya tiene host dado de alta) comparando tokens y
ponderando la RAREZA de cada uno (IDF: ``log(N/df)``), para no confundir por
palabras genéricas ("OFICINA", "CENTRAL", "EXPRESS"...) ni por el prefijo de
operador ("FTTH", "AIRE"...).

Este módulo es la única implementación del matcher; lo usan tanto el alta web
(``web/blueprints/zabbix.py``, "¿este cliente ya tiene host?") como los scripts
de mantenimiento (``scripts/zabbix_coords.py`` y afines). Antes había dos copias
divergentes (con stoplists distintas), lo que hacía que el alta emparejara peor
que el geoposicionamiento.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict

# Palabras genéricas que no ayudan a identificar cliente/sede.
STOP = {
    "SEDE", "MATRIZ", "PRINCIPAL", "CENTRAL", "OFICINA", "OFICINAS", "EMPRESA", "CASA",
    "LOCAL", "PISO", "PLANTA", "BAJO", "PAB", "PABELLON", "NAVE", "PORTAL", "EDIFICIO",
    "CALLE", "AVENIDA", "AVDA", "PLAZA", "POLIGONO", "PARQUE", "BARRIO", "CAMINO",
    "CARRETERA", "CTRA", "LUGAR", "URBANIZACION", "RESIDENCIAL", "GRUPO", "PZA",
    "KALEA", "KALE", "AUZOA", "BAILARA", "ENEA", "ETORBIDEA", "PLAZUELA", "PASEO",
    "IP44", "IP", "DERECHA", "IZQUIERDA", "DCHA", "IZDA", "CONSULTORIO", "ALMACEN",
    "DE", "DEL", "LA", "EL", "LOS", "LAS", "Y", "EN", "CON", "POR",
}
# Tokens de operador/prefijo que aparecen delante del host y no están en GLPI.
PROV_TOK = {
    "FTTH", "FTHH", "BACKUP", "BACK", "UP", "LTE", "KIT", "KITE", "TEL", "TELTONIKA",
    "AIR", "AIRE", "ADA", "ADAMO", "MM", "MAS", "MOVIL", "MASMOVIL", "SAR", "EUS",
    "EUSKALTEL", "VDF", "VODAFONE", "MOV", "MOVISTAR", "TELEFONICA", "ORANGE", "O2",
    "DIGI", "PEPEPHONE", "JAZZTEL", "YOIGO", "CHATEAU", "DUAL", "SNMP", "IMPAGO",
    "CHECKPOINT", "PROXMOX", "GESTION", "THO", "PTV", "TAS", "VAD", "SOA",
}

MATCH_MIN = 4.0   # peso de nombre mínimo total para aceptar el emparejamiento
DISTINCT = 3.0    # al menos un token compartido con este peso (token distintivo)

_TOKEN_SPLIT = re.compile(r"[^A-Z0-9]+")
_SEDE_NUM = re.compile(r"\bSEDE[_ ]?(\d+)\b")


def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c))


def norm(s: str) -> str:
    return strip_accents(s).upper().strip()


def tokenize(s: str, *, drop_prov: bool = False, min_len: int = 3) -> set[str]:
    """Tokens significativos de un nombre: sin acentos, mayúsculas, sin genéricos.

    ``drop_prov=True`` elimina además los prefijos de operador (para tokenizar el
    nombre del host, donde ``FTTH``/``AIRE``... no identifican al cliente).
    """
    out = set()
    for t in _TOKEN_SPLIT.split(norm(s)):
        if len(t) < min_len or t in STOP or t.isdigit():
            continue
        if drop_prov and t in PROV_TOK:
            continue
        out.add(t)
    return out


def sede_num(s: str) -> str:
    m = _SEDE_NUM.search(norm(s))
    return m.group(1) if m else ""


def build_idf_index(token_sets: list[set[str]]):
    """De una lista de conjuntos de tokens → (índice invertido, peso IDF por token).

    ``inv[token]`` = lista ordenada de índices que contienen ese token.
    ``weight[token]`` = ``log(N/df)`` (más raro ⇒ más peso).
    """
    inv: dict[str, set] = defaultdict(set)
    for i, toks in enumerate(token_sets):
        for t in toks:
            inv[t].add(i)
    inv = {k: sorted(v) for k, v in inv.items()}
    n = max(1, len(token_sets))
    weight = {t: math.log(n / len(idxs)) for t, idxs in inv.items()}
    return inv, weight


def score_candidates(query_tokens: set[str], inv: dict, weight: dict):
    """Para cada candidato con algún token compartido → (peso_total, peso_max).

    Devuelve ``{indice: (namew, maxw)}`` considerando solo tokens con peso > 0.
    """
    namew: dict[int, float] = defaultdict(float)
    maxw: dict[int, float] = defaultdict(float)
    for t in query_tokens:
        w = weight.get(t, 0)
        if w <= 0:
            continue
        for i in inv.get(t, ()):  # noqa: E1133
            namew[i] += w
            if w > maxw[i]:
                maxw[i] = w
    return {i: (namew[i], maxw[i]) for i in namew}
