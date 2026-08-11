#!/usr/bin/env python3
"""Alta masiva en Zabbix de las fibras activas en NOP que aún no están.

Lee scripts/alta_masiva_pendientes.csv (cif,cliente,clientName_nop,fiber_ip) y,
para cada cliente, autodetecta todo y crea el host de fibra:
  - IP + versión (v6/v7)      -> NOP (sidecar /routers)
  - proveedor + si tiene backup -> Yeastar (sidecar /services)
  - provincia/sede/localidad/calle -> GLPI
  - contraseña {$ROUTEROS_PASSWORD} -> Passbolt (sidecar /credential)  [solo con --create]
El "quién lo subió" va en la Description. Idempotente: si el host ya existe, lo salta.
El backup NO se crea aquí (su IP privada no está en fuentes automáticas): se anota.

Uso (dentro del contenedor):
  python3 /app/scripts/alta_masiva_zabbix.py                 # DRY-RUN: solo muestra qué haría
  python3 /app/scripts/alta_masiva_zabbix.py --create        # crea de verdad
  python3 /app/scripts/alta_masiva_zabbix.py --create --by "Solana Iñigo"
  python3 /app/scripts/alta_masiva_zabbix.py --solo B20371183 # un CIF concreto
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone

# Permite ejecutar el script por ruta (añade /app al path para importar la app).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CSV_PATH = os.environ.get("ALTA_CSV") or os.path.join(os.path.dirname(__file__), "alta_masiva_pendientes.csv")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "").upper())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]+", "", s)


def _glpi_site(cat, cif, cliente):
    tgt = _norm(cliente)
    for prov in cat or []:
        for c in prov.get("clientes", []):
            same = (cif and c.get("cif", "").upper() == cif.upper()) or (tgt and _norm(c.get("nombre", "")) == tgt)
            if not same:
                continue
            s = (c.get("sedes") or [{}])[0]
            return prov.get("nombre", ""), s.get("nombre", ""), s.get("localidad", ""), s.get("calle", "")
    return "", "", "", ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--create", action="store_true", help="crear de verdad (por defecto dry-run)")
    ap.add_argument("--by", default="alta masiva", help="nombre para la Description (quién lo sube)")
    ap.add_argument("--solo", default="", help="procesar solo este CIF")
    ap.add_argument("--proxyid", default="", help="proxyid; vacío = server")
    args = ap.parse_args()

    from app_factory import create_app
    from web.services.glpi_catalog import load_glpi_catalog
    from generator.zabbix_client import ZabbixClient
    from generator.zabbix_profiles import build_install_plan
    from generator.zabbix_helpers import map_yeastar_provider
    from generator.nop_inventory import fetch_client_routers, fetch_client_services, fetch_backup_ip
    from generator.passbolt_credentials import fetch_router_password

    app = create_app()
    with app.app_context():
        client = ZabbixClient.from_environment()
        if not client:
            print("Zabbix no configurado."); return 2
        cat, _ = load_glpi_catalog()
        with open(CSV_PATH, encoding="utf-8") as _csvf:
            rows = list(csv.DictReader(_csvf))
        if args.solo:
            rows = [r for r in rows if r.get("cif", "").upper() == args.solo.upper()]
        fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        desc = f"Subido a Zabbix por {args.by} el {fecha} (alta masiva draw_automatic)"

        ok = skip = err = backups_pend = 0
        for r in rows:
            cif = r.get("cif", "").strip()
            cliente = r.get("cliente", "").strip()
            try:
                routers = fetch_client_routers(cif, cliente)
                fiber = [x for x in routers if (x.get("type") or "fiber") == "fiber"]
                svc = fetch_client_services(cif, cliente) or {}
                prov_glpi, sede, loc, calle = _glpi_site(cat, cif, cliente)
                proveedor = map_yeastar_provider(svc.get("proveedor", ""))
                ip = ((fiber[0].get("ip") if fiber else None) or r.get("fiber_ip", "")).strip()
                is_v7 = bool(fiber[0].get("is_v7")) if fiber else False
                board = (fiber[0].get("board") if fiber else "") or ""
                is_chateau = "chateau" in board.lower()
                if not (ip and proveedor and prov_glpi):
                    print(f"  SALTO {cliente[:32]:32} faltan datos (ip={ip} prov={proveedor!r} provincia={prov_glpi!r})")
                    skip += 1
                    continue
                # tipo + datos del backup separado (IP del router de túneles)
                prov_backup = backup_ip = backup_tipo = ""
                if is_chateau:
                    tipo = "chateau"
                    prov_backup = map_yeastar_provider(svc.get("backup_proveedor", ""))
                elif svc.get("tiene_backup"):
                    backup_ip = fetch_backup_ip(cliente)
                    if backup_ip:
                        tipo = "fibra_backup"
                        backup_tipo = "KITE"  # Mikrotik SNMP BACKUP por defecto
                    else:
                        tipo = "fibra"           # sin IP no creamos el backup
                        backups_pend += 1
                else:
                    tipo = "fibra"
                def _mkplan(pw):
                    return build_install_plan(tipo=tipo, cliente=cliente, sede=sede or "Sede 1",
                                              proveedor=proveedor, proveedor_backup=prov_backup,
                                              router_ip=ip, is_v7=is_v7, localidad=loc, calle=calle,
                                              backup_ip=backup_ip, backup_tipo=backup_tipo,
                                              router_password=pw)
                plan = _mkplan("")
                router_spec = next((h for h in plan.hosts if h.role == "router"), None)
                router_exists = bool(router_spec and client.find_host_by_name(router_spec.host))
                # Solo se pide la contraseña de Passbolt si hay que crear el router (nuevo).
                if args.create and router_spec and not router_exists:
                    plan = _mkplan(fetch_router_password(ip, username="Ausarta"))
                tag = "v7" if is_v7 else "v6"
                nota = " [CHATEAU]" if is_chateau else (f" +BACKUP {backup_ip}" if backup_ip else "")
                try:
                    from generator.geocode import geocode_es
                    loc_lat, loc_lon = geocode_es(calle, loc, prov_glpi)
                except Exception:  # noqa: BLE001
                    loc_lat, loc_lon = "", ""
                for spec in plan.hosts:
                    if client.find_host_by_name(spec.host):
                        print(f"  YA EXISTE {spec.host[:60]}")
                        skip += 1
                        continue
                    if not args.create:
                        extra = nota if spec.role == "router" else ""
                        print(f"  [dry] {tipo:12} {spec.role:6} {proveedor:8} {tag} {spec.ip:16} {prov_glpi:12} {spec.host[:42]}{extra}")
                        ok += 1
                        continue
                    group = client.resolve_router_group(prov_glpi, spec.group_role)
                    pid = args.proxyid or client.dominant_proxy(str(group.get("groupid", "")))
                    res = client.create_host(host=spec.host, name=spec.name, ip=spec.ip,
                                             groupid=str(group.get("groupid", "")),
                                             template_ids=spec.template_ids, macros=spec.macros,
                                             tags=spec.tags, description=desc, proxyid=pid,
                                             location_lat=loc_lat, location_lon=loc_lon)
                    hid = (res.get("hostids") or [""])[0]
                    print(f"  CREADO {hid} {spec.role:6} proxy={pid or 'server'} {spec.ip:16} {spec.host[:42]}")
                    ok += 1
            except Exception as e:  # noqa: BLE001
                print(f"  ERROR {cliente[:32]}: {e}")
                err += 1

        modo = "CREADOS" if args.create else "a crear (dry-run)"
        print(f"\n== {modo}: {ok} | saltados: {skip} | errores: {err} | con backup pendiente de IP: {backups_pend} ==")
        if not args.create:
            print("Repite con --create para crearlos de verdad.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
