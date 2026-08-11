"""Geocodifica una dirección española (calle, localidad, provincia) a (lat, lon).

Photon (validado país=ES + bbox España) con Nominatim (countrycodes=es) de reserva.
Pensado para uso puntual al dar de alta un host. Devuelve ("", "") si no resuelve
(nunca lanza). Las coordenadas van al inventario de Zabbix (location_lat/location_lon).
"""
from __future__ import annotations

import json
import os
import re
import threading
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SPAIN_BBOX = (-18.5, 27.4, 4.6, 44.2)  # lon_min, lat_min, lon_max, lat_max
UA = "ausarta-geocoder/1.0 (ops@ausarta.es)"
_cache: dict[str, tuple | None] = {}
_cache_lock = threading.Lock()
_CACHE_MAX = 5000


_ADDR_TAIL = re.compile(r",\s*(?:local|bajo|piso|planta|pab|nave|puerta)", re.I)


def parse_address(address: str) -> tuple[str, str]:
    """De una dirección de calle → (primer_tramo, tramo_sin_número).

    Recorta el sufijo de local/piso/planta..., se queda con el primer tramo antes
    de la coma, y una variante sin el número de portal (para reintentar). Ambos
    ``geocode_es`` y el geocoder de ``zabbix_coords`` construyen sus intentos con
    esto, así que vive aquí una sola vez.
    """
    street = str(address or "").strip().strip(",")
    street = _ADDR_TAIL.split(street)[0]
    first = street.split(",")[0].strip()
    nonum = re.sub(r"\d.*$", "", first).strip(" ,-")
    return first, nonum


def _in_spain(lat, lon) -> bool:
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    return SPAIN_BBOX[1] <= la <= SPAIN_BBOX[3] and SPAIN_BBOX[0] <= lo <= SPAIN_BBOX[2]


def _photon(q: str, timeout: float):
    try:
        url = "https://photon.komoot.io/api?" + urlencode(
            {"q": q, "limit": 1, "bbox": "%f,%f,%f,%f" % SPAIN_BBOX})
        with urlopen(Request(url, headers={"User-Agent": UA}), timeout=timeout) as resp:
            data = json.load(resp)
        feats = data.get("features") or []
        if feats:
            props = feats[0].get("properties") or {}
            lon, lat = feats[0]["geometry"]["coordinates"][:2]
            if str(props.get("countrycode", "")).upper() == "ES" and _in_spain(lat, lon):
                return (str(lat), str(lon))
    except Exception:  # noqa: BLE001
        pass
    return None


def _nominatim(q: str, timeout: float):
    try:
        url = "https://nominatim.openstreetmap.org/search?" + urlencode(
            {"q": q, "format": "json", "limit": 1, "countrycodes": "es"})
        with urlopen(Request(url, headers={"User-Agent": UA}), timeout=timeout) as resp:
            data = json.load(resp)
        if data:
            return (str(data[0]["lat"]), str(data[0]["lon"]))
    except Exception:  # noqa: BLE001
        pass
    return None


def geocode_es(calle: str = "", localidad: str = "", provincia: str = "", *, timeout: float = 10.0):
    """Devuelve (lat, lon) como strings con 6 decimales, o ("", "")."""
    if os.environ.get("GEOCODE_DISABLED"):
        return ("", "")  # tests / entornos sin red
    calle = str(calle or "").strip()
    localidad = str(localidad or "").strip()
    provincia = str(provincia or "").strip()
    if not (localidad or calle):
        return ("", "")
    street, nonum = parse_address(calle)
    attempts = []
    if street and localidad:
        attempts.append(f"{street}, {localidad}, {provincia}")
    if nonum and nonum.lower() != street.lower() and localidad:
        attempts.append(f"{nonum}, {localidad}, {provincia}")
    if localidad:
        attempts.append(f"{localidad}, {provincia}")
    elif provincia:
        attempts.append(provincia)
    for q in attempts:
        with _cache_lock:
            hit = q in _cache
            r = _cache.get(q)
        if not hit:
            r = _photon(q, timeout) or _nominatim(q, timeout)
            with _cache_lock:
                if len(_cache) >= _CACHE_MAX:
                    # expulsa el ~10% más antiguo (orden de inserción) en vez de
                    # vaciar todo, para no re-geocodificar direcciones ya resueltas
                    for _old in list(_cache)[: max(1, _CACHE_MAX // 10)]:
                        _cache.pop(_old, None)
                _cache[q] = r
        if r:
            try:
                return (f"{float(r[0]):.6f}", f"{float(r[1]):.6f}")
            except (TypeError, ValueError):
                return ("", "")
    return ("", "")
