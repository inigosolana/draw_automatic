#!/usr/bin/env python3
"""2ª fase: enlaza la plantilla RouterOS BGP (v6=11208 / V7=13463) a las FTTH que
ya tienen contraseña pero no la plantilla BGP. Detecta la versión entrando por API
(usa la password de la macro). De paso cuenta cuántos routers NO tienen la API activa.

  python3 /app/data/link_bgp.py            # DRY-RUN: solo sondea versión/API y cuenta
  python3 /app/data/link_bgp.py --apply    # además enlaza la plantilla BGP
"""
import argparse, sys, threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, "/app"); sys.path.insert(0, "/app/data")

BGP = {"11208", "13463", "15602"}
TPL = {False: "11208", True: "13463"}  # is_v7 -> templateid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    from app_factory import create_app
    from generator.zabbix_client import ZabbixClient
    from generator.passbolt_credentials import fetch_router_password
    from generator.routeros_version import fetch_router_version
    app = create_app()
    with app.app_context():
        import csv
        c = ZabbixClient.from_environment()
        hs = c._jsonrpc("host.get", {"output": ["hostid", "host", "status"], "selectMacros": ["macro", "value"],
                                     "selectParentTemplates": ["templateid"], "selectInterfaces": ["ip"],
                                     "selectHostGroups": ["name"]})
        targets = []
        for h in hs:
            if not h["host"].upper().startswith(("FTTH", "FTHH")):
                continue
            tids = {str(t["templateid"]) for t in h.get("parentTemplates", [])}
            if tids & BGP:
                continue  # ya tiene plantilla BGP
            mac = {m["macro"].upper(): m.get("value", "") for m in h.get("macros", [])}
            pw = mac.get("{$ROUTEROS_PASSWORD}", "")
            ips = [i.get("ip") for i in h.get("interfaces", []) if i.get("ip")]
            if not ips:
                continue
            grp = next((g["name"].replace("Routers ", "") for g in h.get("hostgroups", [])
                        if g.get("name", "").lower().startswith("routers ")), "")
            targets.append((h["hostid"], h["host"], ips[0], pw, grp, h.get("status", "0")))
        print(f"FTTH sin plantilla BGP a sondear: {len(targets)}", flush=True)

        res = Counter()
        vers = Counter()
        lock = threading.Lock()
        done = [0]
        caida = []      # [(host, ip, grupo, estado)]
        sin_pw = []

        def work(t):
            hid, host, ip, pw, grp, status = t
            if not pw:
                pw = fetch_router_password(ip, username="Ausarta") or ""
            if not pw:
                with lock:
                    res["sin_password"] += 1
                    sin_pw.append((host, ip, grp, "ON" if status == "0" else "OFF"))
                return
            v = fetch_router_version(ip, "Ausarta", pw)
            d = getattr(v, "__dict__", v) or {}
            with lock:
                done[0] += 1
                if done[0] % 50 == 0:
                    print(f"  ... {done[0]}/{len(targets)} api_ok={res['api_activa']} api_caida={res['api_caida']}", flush=True)
            if not d.get("ok"):
                with lock:
                    res["api_caida"] += 1
                    caida.append((host, ip, grp, "ON" if status == "0" else "OFF"))
                return
            with lock:
                res["api_activa"] += 1
                vers["v7" if d.get("is_v7") else "v6"] += 1
            if a.apply:
                tid = TPL[bool(d.get("is_v7"))]
                try:
                    c._jsonrpc("host.massadd", {"hosts": [{"hostid": hid}], "templates": [{"templateid": tid}]})
                    with lock: res["plantilla_enlazada"] += 1
                except Exception:  # noqa: BLE001
                    with lock: res["error_enlace"] += 1

        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            list(ex.map(work, targets))

        with open("/app/data/api_caida.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["motivo", "host", "ip", "provincia", "estado"])
            for host, ip, grp, st in sorted(caida):
                w.writerow(["API_CAIDA", host, ip, grp, st])
            for host, ip, grp, st in sorted(sin_pw):
                w.writerow(["SIN_PASSWORD_PASSBOLT", host, ip, grp, st])
        print(f"\n== {'APLICADO' if a.apply else 'DRY-RUN'} ==", flush=True)
        print(f"  API ACTIVA:   {res['api_activa']}")
        print(f"  API NO ACTIVA: {res['api_caida']}   <-- routers a los que hay que activar la API")
        print(f"  sin password: {res['sin_password']}")
        print(f"  versiones detectadas: {dict(vers)}")
        print(f"  lista guardada en /app/data/api_caida.csv")
        if a.apply:
            print(f"  plantilla BGP enlazada: {res['plantilla_enlazada']} (errores {res['error_enlace']})")


if __name__ == "__main__":
    main()
