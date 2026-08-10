#!/usr/bin/env python3
"""Pone las macros que faltan (ROUTEROS_USERNAME + ROUTEROS_PASSWORD) a las FTTH
que tienen menos de 3 macros, con la contraseña REAL del router sacada de Passbolt
(vía el sidecar). No toca la plantilla BGP (2ª fase). Idempotente.

Uso (en el contenedor):
  python3 /app/data/fix_ftth_macros.py            # DRY-RUN
  python3 /app/data/fix_ftth_macros.py --apply
"""
import argparse, sys
sys.path.insert(0, "/app"); sys.path.insert(0, "/app/data")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    from app_factory import create_app
    from generator.zabbix_client import ZabbixClient
    from generator.passbolt_credentials import fetch_router_password
    app = create_app()
    with app.app_context():
        c = ZabbixClient.from_environment()
        hs = c._jsonrpc("host.get", {"output": ["hostid", "host", "status"],
                                     "selectMacros": ["macro"],
                                     "selectInterfaces": ["ip"]})
        ftth = [h for h in hs if h["host"].upper().startswith(("FTTH", "FTHH"))]
        target = []
        for h in ftth:
            macros = {m["macro"].upper() for m in h.get("macros", [])}
            if len(macros) < 3:
                target.append((h, macros))
        print(f"FTTH con <3 macros: {len(target)}", flush=True)
        set_ok = nopw = noip = skip = err = 0
        done = 0
        for h, macros in target:
            done += 1
            ips = [i.get("ip") for i in h.get("interfaces", []) if i.get("ip")]
            if not ips:
                noip += 1
                print(f"  SIN IP  {h['host'][:52]}", flush=True); continue
            ip = ips[0]
            need_pw = "{$ROUTEROS_PASSWORD}" not in macros
            need_user = "{$ROUTEROS_USERNAME}" not in macros
            if not (need_pw or need_user):
                skip += 1; continue
            pw = fetch_router_password(ip, username="Ausarta") if need_pw else "x"
            if need_pw and not pw:
                nopw += 1
                print(f"  SIN PASSWORD en Passbolt  {ip:16} {h['host'][:46]}", flush=True); continue
            if not a.apply:
                set_ok += 1
                if done <= 8 or done % 100 == 0:
                    print(f"  [dry] {ip:16} {h['host'][:50]}  (pondría USERNAME+PASSWORD)", flush=True)
                continue
            try:
                if need_user:
                    c._jsonrpc("usermacro.create", {"hostid": h["hostid"], "macro": "{$ROUTEROS_USERNAME}", "value": "Ausarta"})
                if need_pw:
                    c._jsonrpc("usermacro.create", {"hostid": h["hostid"], "macro": "{$ROUTEROS_PASSWORD}", "value": pw, "type": "1"})  # Secret
                set_ok += 1
                if done % 50 == 0:
                    print(f"  ... {done}/{len(target)}  puestas={set_ok} sin_pw={nopw}", flush=True)
            except Exception as e:  # noqa: BLE001
                err += 1
                if err <= 10:
                    print(f"  ERROR {h['host'][:40]}: {str(e)[:50]}", flush=True)
        print(f"\n== {'APLICADO' if a.apply else 'DRY-RUN'}: macros puestas {set_ok} | "
              f"sin password en Passbolt {nopw} | sin IP {noip} | ya OK {skip} | errores {err} ==", flush=True)
        if not a.apply:
            print("Repite con --apply para escribir.")

if __name__ == "__main__":
    main()
