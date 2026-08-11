#!/usr/bin/env python3
"""Coordenadas reales por sede en el inventario de Zabbix (mapa geográfico).

Las coordenadas actuales de casi todos los hosts eran el CENTROIDE DE LA PROVINCIA
(cientos de hosts apilados en la capital). Este script pone la coordenada REAL de
cada sede a partir de GLPI: empareja cada host de fibra/backup/LTE con su entidad
GLPI (nombre de cliente/sede con ponderación IDF, join fuerte por "Sede N", y la
provincia del grupo Zabbix solo como desempate) y resuelve la coordenada:

  1) latitude/longitude de GLPI si la entidad ya las tiene (exacto).
  2) geocodificación de "calle, localidad, provincia" y, en cascada, calle sin
     número y por último "localidad, provincia" (municipio).

Geocodificación PARALELA: Photon (acotado a España por bbox + sesgo al centroide
de la provincia, validando que el resultado cae en España) y Nominatim
(countrycodes=es) como reserva. La caché se persiste en /app/data.

Uso (dentro del contenedor):
  python3 /app/data/zabbix_coords.py                  # DRY-RUN: informe + muestra
  python3 /app/data/zabbix_coords.py --apply          # escribe en Zabbix
  python3 /app/data/zabbix_coords.py --apply --limit 20         # prueba
  python3 /app/data/zabbix_coords.py --apply --only-missing     # solo sin coord
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator.host_matching import (  # noqa: E402
    DISTINCT,
    MATCH_MIN,
    PROV_TOK,
    STOP,
    build_idf_index,
    norm,
    score_candidates,
    sede_num,
)
from generator.host_matching import tokenize as toks  # noqa: E402
from generator.host_matching import strip_accents as _strip_accents  # noqa: E402
from generator.geocode import parse_address  # noqa: E402

CACHE_PATH = os.environ.get("GEOCODE_CACHE") or "/app/data/geocode_cache.json"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
PHOTON = "https://photon.komoot.io/api"
UA = "ausarta-zabbix-geocoder/1.0 (ops@ausarta.es)"
GEO_WORKERS = int(os.environ.get("GEO_WORKERS", "6"))
UPD_WORKERS = int(os.environ.get("UPD_WORKERS", "6"))
# bbox de España (lon_min, lat_min, lon_max, lat_max) incluidas Canarias
SPAIN_BBOX = (-18.5, 27.4, 4.6, 44.2)

# Centroides de provincia para sesgar el geocoder y como último recurso.
PROV_CENTROID = {
    "BIZKAIA": (43.2241, -2.9726), "ASTURIAS": (43.5313, -5.6585),
    "CORUNA": (43.3636, -8.4373), "CANTABRIA": (43.4136, -3.9000),
    "PONTEVEDRA": (42.4294, -8.6533), "MALAGA": (36.7332, -4.4328),
    "ALMERIA": (36.8875, -2.4074), "MADRID": (40.4165, -3.7026),
    "GIPUZKOA": (43.3000, -1.9800), "GRANADA": (37.1800, -3.6000),
    "JAEN": (37.7700, -3.7900), "LEON": (42.6000, -5.5700),
    "ALAVA": (42.8500, -2.6700), "LUGO": (43.0100, -7.5600),
    "OURENSE": (42.3400, -7.8600), "NAVARRA": (42.8100, -1.6400),
    "GUADALAJARA": (40.6300, -3.1600), "BARCELONA": (41.3900, 2.1700),
}

# STOP, PROV_TOK, _strip_accents, norm, toks (=tokenize) y sede_num viven en
# generator.host_matching (importados arriba). Aquí solo la lógica específica de
# geoposicionamiento (provincia y sufijo de grupo).


def prov_key(p: str) -> str:
    n = norm(p)
    n = re.sub(r"\s+(NORTE|SUR)$", "", n).strip()
    if n.startswith("A CORUNA") or n == "CORUNA":
        return "CORUNA"
    return {"VIZCAYA": "BIZKAIA", "GUIPUZCOA": "GIPUZKOA", "ARABA": "ALAVA"}.get(n, n)


def group_province(groups: list[dict]) -> str:
    for g in groups or []:
        m = re.match(r"Routers (?:Fibra|Backup|LTE)\s+(.+)", g.get("name", ""))
        if m:
            return prov_key(m.group(1))
    return ""


# ---------------------------------------------------------------- geocodificación
def _in_spain(lat: float, lon: float) -> bool:
    return SPAIN_BBOX[1] <= lat <= SPAIN_BBOX[3] and SPAIN_BBOX[0] <= lon <= SPAIN_BBOX[2]


class Geocoder:
    def __init__(self):
        self.cache: dict[str, list] = {}
        self.lock = threading.Lock()
        self.nomi_lock = threading.Lock()
        self._nomi_last = 0.0
        self.calls = 0
        self.photon_ok = True      # se autodesactiva si Photon nos bloquea
        self.photon_fails = 0
        if os.path.exists(CACHE_PATH):
            try:
                with open(CACHE_PATH, encoding="utf-8") as _f:
                    self.cache = json.load(_f)
            except Exception:  # noqa: BLE001
                self.cache = {}

    def save(self):
        try:
            os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
            with self.lock:
                snapshot = dict(self.cache)
            with open(CACHE_PATH, "w", encoding="utf-8") as _f:
                json.dump(snapshot, _f)
        except Exception:  # noqa: BLE001
            pass

    def _photon_typed(self, q: str, bias):
        """Devuelve (lat, lon, tipo) del primer resultado EN ESPAÑA (countrycode ES),
        o None. tipo = properties.type (house/street/locality/city/...). Si Photon
        nos bloquea (varios fallos seguidos) se autodesactiva y tira solo de Nominatim."""
        if not self.photon_ok:
            return None
        params = {"q": q, "limit": 1, "lang": "default",
                  "bbox": "%f,%f,%f,%f" % SPAIN_BBOX}
        if bias:
            params["lat"], params["lon"] = bias[0], bias[1]
        req = Request(PHOTON + "?" + urlencode(params), headers={"User-Agent": UA})
        try:
            time.sleep(0.15)  # cortesía
            data = json.load(urlopen(req, timeout=15))
            self.photon_fails = 0
            feats = data.get("features") or []
            if feats:
                props = feats[0].get("properties") or {}
                cc = str(props.get("countrycode") or "").upper()
                lon, lat = feats[0]["geometry"]["coordinates"][:2]
                # SOLO España: exige countrycode ES (la bbox sola cuela Francia/Portugal)
                if cc == "ES" and _in_spain(float(lat), float(lon)):
                    return (str(lat), str(lon), str(props.get("type") or ""))
        except Exception:  # noqa: BLE001
            self.photon_fails += 1
            if self.photon_fails >= 8:
                self.photon_ok = False
        return None

    def _photon(self, q: str, bias):
        r = self._photon_typed(q, bias)
        return [r[0], r[1]] if r else None

    def _nominatim(self, q: str):
        with self.nomi_lock:  # Nominatim: 1 req/s como mucho
            dt = time.time() - self._nomi_last
            if dt < 1.05:
                time.sleep(1.05 - dt)
            self._nomi_last = time.time()
            url = NOMINATIM + "?" + urlencode(
                {"q": q, "format": "json", "limit": 1, "countrycodes": "es"})
            req = Request(url, headers={"User-Agent": UA})
            try:
                data = json.load(urlopen(req, timeout=20))
                if data:
                    return [str(data[0]["lat"]), str(data[0]["lon"])]
            except Exception:  # noqa: BLE001
                pass
        return None

    def _query(self, q: str, bias, cache_only=False):
        key = q.strip().lower()
        with self.lock:
            if key in self.cache:
                return self.cache[key]
        if cache_only:
            return None
        r = self._photon(q, bias) or self._nominatim(q)
        with self.lock:
            self.cache[key] = r
            self.calls += 1
        return r

    def resolve(self, address: str, town: str, prov: str, bias, cache_only=False):
        town = str(town or "").strip()
        prov = str(prov or "").strip()
        street_first, street_nonum = parse_address(address)
        attempts = []
        if street_first and town:
            attempts.append((f"{street_first}, {town}, {prov}", "calle"))
        if street_nonum and street_nonum.lower() != street_first.lower() and town:
            attempts.append((f"{street_nonum}, {town}, {prov}", "calle"))
        if town:
            attempts.append((f"{town}, {prov}", "municipio"))
        elif prov:
            attempts.append((f"{prov}", "provincia"))
        for q, prec in attempts:
            r = self._query(q, bias, cache_only=cache_only)
            if r:
                return r[0], r[1], prec
        return None, None, ""

    def street_point(self, address: str, town: str, prov: str, bias, ref):
        """Intenta ubicar a nivel de CALLE/portal. Solo acepta resultados de tipo
        house/street y que caigan cerca del municipio de referencia `ref` (lat,lon).
        Devuelve (lat, lon) o None (para no degradar lo que ya hay)."""
        town = str(town or "").strip()
        prov = str(prov or "").strip()
        first, nonum = parse_address(address)
        if not first or not town:
            return None
        variants = [f"{first}, {town}, {prov}", f"{first}, {town}"]
        if nonum and nonum.lower() != first.lower():
            variants += [f"{nonum}, {town}, {prov}", f"{nonum}, {town}"]
        for q in variants:
            key = "street::" + q.strip().lower()
            with self.lock:
                cached = self.cache.get(key, "MISS")
            if cached == "MISS":
                r = self._photon_typed(q, bias)
                with self.lock:
                    self.cache[key] = r
                    self.calls += 1
            else:
                r = cached
            if not r:
                continue
            lat, lon, ptype = r
            if ptype not in ("house", "street", "construction"):
                continue
            if ref:
                try:
                    if abs(float(lat) - ref[0]) > 0.25 or abs(float(lon) - ref[1]) > 0.30:
                        continue  # calle homónima en otro municipio
                except (TypeError, ValueError):
                    pass
            return lat, lon
        return None


# ---------------------------------------------------------------- índice GLPI
def build_glpi_index(entities: list[dict]):
    by_id = {e["id"]: e for e in entities if isinstance(e.get("id"), int)}
    sites = []
    for e in entities:
        town = str(e.get("town") or "").strip()
        addr = str(e.get("address") or "").strip()
        if not (town or addr):
            continue
        parent = by_id.get(e.get("entities_id"))
        t = toks(e.get("name", "")) | toks(town)
        if parent:
            t |= toks(parent.get("name", ""))
        state = str(e.get("state") or (parent or {}).get("state") or "").strip()
        sites.append({
            "id": e["id"], "name": e.get("name", ""),
            "parent": (parent or {}).get("name", ""),
            "town": town, "addr": addr, "state": state,
            "lat": str(e.get("latitude") or "").strip(),
            "lon": str(e.get("longitude") or "").strip(),
            "tokens": t, "prov": prov_key(state), "num": sede_num(e.get("name", "")),
        })

    inv, weight = build_idf_index([s["tokens"] for s in sites])
    return sites, inv, weight


def match_host(hostname: str, prov: str, sites, inv, weight):
    htoks = toks(hostname, drop_prov=True)
    if not htoks:
        return None, 0
    hnum = sede_num(hostname)
    scored = score_candidates(htoks, inv, weight)
    if not scored:
        return None, 0
    best = None
    best_score = 0.0
    best_namew = 0.0
    best_maxw = 0.0
    for i, (namew, maxw) in scored.items():
        s = sites[i]
        score = namew
        if prov and s["prov"] == prov:
            score += 1.0
        if hnum and s["num"]:
            score += 3.0 if hnum == s["num"] else -2.5
        if score > best_score:
            best_score, best, best_namew, best_maxw = score, s, namew, maxw
    if best and best_namew >= MATCH_MIN and best_maxw >= DISTINCT:
        return best, best_score
    return None, best_score


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="escribir en Zabbix (por defecto dry-run)")
    ap.add_argument("--limit", type=int, default=0, help="procesar como mucho N hosts")
    ap.add_argument("--sample", type=int, default=25, help="ejemplos a mostrar")
    ap.add_argument("--only-missing", action="store_true", help="solo hosts sin coordenada actual")
    ap.add_argument("--upgrade", action="store_true",
                    help="segunda pasada: sube a nivel CALLE las sedes que tengan calle en GLPI")
    args = ap.parse_args()

    from app_factory import create_app
    from generator.zabbix_client import ZabbixClient
    from generator.glpi_client import GlpiClient

    app = create_app()
    with app.app_context():
        zc = ZabbixClient.from_environment()
        if not zc:
            print("Zabbix no configurado."); return 2
        glpi = GlpiClient.from_environment()
        sites, inv, weight = build_glpi_index(glpi.list_entities())
        print(f"GLPI: {len(sites)} sedes geocodables indexadas", flush=True)

        hosts = zc._jsonrpc("host.get", {
            "output": ["hostid", "host"],
            "selectHostGroups": ["name"],
            "selectInventory": ["location_lat", "location_lon"],
        })

        def is_router(h):
            n = h["host"].upper()
            if n.startswith(("FTTH", "FTHH", "BACKUP", "BACK_UP", "LTE_")):
                return True
            return any(g.get("name", "").lower().startswith("routers ") for g in h.get("hostgroups", []))
        hosts = [h for h in hosts if is_router(h)]
        if args.only_missing:
            def nocoord(h):
                iv = h.get("inventory") or {}
                return not (str(iv.get("location_lat") or "").strip() and str(iv.get("location_lon") or "").strip())
            hosts = [h for h in hosts if nocoord(h)]
        if args.limit:
            hosts = hosts[:args.limit]
        print(f"Hosts a procesar: {len(hosts)}", flush=True)

        # FASE 1 -- emparejar todos (sin red)
        plan = []  # (host, prov, site)
        matched = 0
        for h in hosts:
            prov = group_province(h.get("hostgroups", []))
            site, _ = match_host(h["host"], prov, sites, inv, weight)
            if site:
                matched += 1
            plan.append((h, prov, site))
        unmatched = len(hosts) - matched
        print(f"Fase 1: emparejados {matched} | sin match {unmatched}", flush=True)

        # ---- modo UPGRADE: subir a nivel CALLE las sedes con calle en GLPI ----
        if args.upgrade:
            geo = Geocoder()
            need = {}
            for h, prov, site in plan:
                if site and str(site["addr"]).strip():
                    need.setdefault(site["id"], (site, prov))
            print(f"UPGRADE: {len(need)} sedes con calle; buscando nivel-calle "
                  f"con {GEO_WORKERS} hilos...", flush=True)
            street = {}

            def up_one(item):
                sid, (site, prov) = item
                bias = PROV_CENTROID.get(site["prov"]) or PROV_CENTROID.get(prov)
                rl, ro, _ = geo.resolve("", site["town"], site["state"] or prov, bias)
                ref = None
                try:
                    ref = (float(rl), float(ro)) if rl and ro else None
                except (TypeError, ValueError):
                    ref = None
                return sid, geo.street_point(site["addr"], site["town"], site["state"] or prov, bias, ref)

            done = 0
            with ThreadPoolExecutor(max_workers=GEO_WORKERS) as ex:
                for sid, pt in ex.map(up_one, list(need.items())):
                    if pt:
                        street[sid] = pt
                    done += 1
                    if done % 200 == 0:
                        print(f"  up {done}/{len(need)}  a_calle={len(street)}", flush=True)
                        geo.save()
            geo.save()
            updates = []
            for h, prov, site in plan:
                if site and site["id"] in street:
                    lat, lon = street[site["id"]]
                    try:
                        updates.append((h["hostid"], f"{float(lat):.6f}", f"{float(lon):.6f}"))
                    except (TypeError, ValueError):
                        pass
            print(f"UPGRADE: {len(street)} sedes ubicadas a nivel calle -> {len(updates)} hosts", flush=True)
            up_ok = up_err = 0
            if args.apply:
                def upd(u):
                    hostid, la, lo = u
                    try:
                        zc._jsonrpc("host.update", {"hostid": hostid, "inventory_mode": "1",
                                    "inventory": {"location_lat": la, "location_lon": lo}})
                        return True
                    except Exception as e:  # noqa: BLE001
                        return str(e)
                with ThreadPoolExecutor(max_workers=UPD_WORKERS) as ex:
                    for r in ex.map(upd, updates):
                        if r is True:
                            up_ok += 1
                        else:
                            up_err += 1
                print(f"UPGRADE ACTUALIZADOS a nivel calle: {up_ok}  (errores {up_err})")
                print(f"geocodificaciones nuevas: {geo.calls}  (caché total: {len(geo.cache)})")
            else:
                print("UPGRADE dry-run. Repite con --upgrade --apply para escribir.")
            return 0

        # sedes -> hosts, para escribir por sede
        site_hosts = defaultdict(list)
        site_info = {}
        for h, prov, site in plan:
            if site:
                site_hosts[site["id"]].append(h["hostid"])
                site_info[site["id"]] = (site, prov)

        geo = Geocoder()
        prec_count = Counter()
        updated = errors = 0
        upd_lock = threading.Lock()

        def flush(ups):
            """Escribe una lista de (hostid, lat_s, lon_s) en paralelo."""
            nonlocal updated, errors
            if not (args.apply and ups):
                return

            def _u(u):
                hid, la, lo = u
                try:
                    zc._jsonrpc("host.update", {"hostid": hid, "inventory_mode": "1",
                                "inventory": {"location_lat": la, "location_lon": lo}})
                    return True
                except Exception as e:  # noqa: BLE001
                    return str(e)
            with ThreadPoolExecutor(max_workers=UPD_WORKERS) as ex:
                for r in ex.map(_u, ups):
                    with upd_lock:
                        if r is True:
                            updated += 1
                        else:
                            errors += 1

        def site_updates(sid, lat, lon):
            out = []
            try:
                la, lo = f"{float(lat):.6f}", f"{float(lon):.6f}"
            except (TypeError, ValueError):
                return out
            for hid in site_hosts[sid]:
                out.append((hid, la, lo))
            return out

        # PASO A -- sin red: GLPI-latlon o lo YA cacheado. Escribe el grueso al momento.
        pending = []
        A = []
        def _glpi_ok(la, lo):
            try:
                return _in_spain(float(la), float(lo))
            except (TypeError, ValueError):
                return False
        for sid, (site, prov) in site_info.items():
            bias = PROV_CENTROID.get(site["prov"]) or PROV_CENTROID.get(prov)
            if site["lat"] and site["lon"] and _glpi_ok(site["lat"], site["lon"]):
                lat, lon, prec = site["lat"], site["lon"], "glpi"
            else:
                lat, lon, prec = geo.resolve(site["addr"], site["town"], site["state"] or prov, bias, cache_only=True)
            if lat and lon:
                prec_count[prec] += len(site_hosts[sid])
                A += site_updates(sid, lat, lon)
            else:
                pending.append(sid)
        print(f"PASO A (caché/GLPI, sin red): sedes resueltas {len(site_info) - len(pending)}, "
              f"hosts a escribir {len(A)}; sedes pendientes de geocodificar {len(pending)}", flush=True)
        flush(A)
        print(f"  PASO A escritos: {updated} (errores {errors})", flush=True)

        # PASO B -- con red: geocodifica pendientes y escribe por lotes (resistente a cortes)
        if pending:
            print(f"PASO B: geocodificando {len(pending)} sedes con {GEO_WORKERS} hilos...", flush=True)

            def geo_one(sid):
                site, prov = site_info[sid]
                bias = PROV_CENTROID.get(site["prov"]) or PROV_CENTROID.get(prov)
                lat, lon, prec = geo.resolve(site["addr"], site["town"], site["state"] or prov, bias)
                return sid, lat, lon, prec

            batch = []
            done = 0
            with ThreadPoolExecutor(max_workers=GEO_WORKERS) as ex:
                for sid, lat, lon, prec in ex.map(geo_one, pending):
                    done += 1
                    if lat and lon:
                        prec_count[prec] += len(site_hosts[sid])
                        batch += site_updates(sid, lat, lon)
                    else:
                        prec_count["sin-coord"] += len(site_hosts[sid])
                    if done % 100 == 0 or done == len(pending):
                        flush(batch); batch = []
                        geo.save()
                        print(f"  PASO B {done}/{len(pending)}  escritos_tot={updated} nuevas_geo={geo.calls}", flush=True)
            geo.save()

        print("\n== RESUMEN ==")
        print(f"  emparejados: {matched} | sin match: {unmatched}")
        print(f"  precisión:   {dict(prec_count)}")
        print(f"  geocodificaciones nuevas: {geo.calls}  (caché total: {len(geo.cache)})")
        if args.apply:
            print(f"  ACTUALIZADOS en Zabbix: {updated}  (errores: {errors})")
        else:
            print("  DRY-RUN. Repite con --apply para escribir en Zabbix.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
