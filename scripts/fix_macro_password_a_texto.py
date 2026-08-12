#!/usr/bin/env python3
"""Pasa {$ROUTEROS_PASSWORD} de macro SECRETA (type=1) a TEXTO (type=0) con la
contrasena REAL del router sacada de Passbolt (via el sidecar).

Por que hace falta re-escribir el valor y no solo cambiar el tipo: Zabbix nunca
devuelve el valor de una macro secreta por API, asi que la unica forma de dejarla
en texto con la contrasena correcta es volver a pedirla a Passbolt por IP.

Seguro por diseno:
  - Si Passbolt no tiene la contrasena de esa IP, NO se toca el host (se lista).
  - Nunca imprime contrasenas.
  - Idempotente: los que ya estan en texto se ignoran.

Uso (en el contenedor):
  python3 /app/data/fix_macro_password_a_texto.py                  # DRY-RUN completo
  python3 /app/data/fix_macro_password_a_texto.py --limit 10 --apply
  python3 /app/data/fix_macro_password_a_texto.py --apply          # todo
  python3 /app/data/fix_macro_password_a_texto.py --hostids 15719,15720 --apply
"""
import argparse
import csv
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/data")

MACRO = "{$ROUTEROS_PASSWORD}"
REPORT = "/app/data/macros_sin_password_passbolt.csv"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="escribe de verdad (si no, dry-run)")
    ap.add_argument("--limit", type=int, default=0, help="procesa como maximo N hosts")
    ap.add_argument("--hostids", default="", help="lista de hostids separada por comas")
    ap.add_argument("--only-enabled", action="store_true", help="solo hosts habilitados")
    a = ap.parse_args()

    from app_factory import create_app
    from generator.zabbix_client import ZabbixClient
    from generator.passbolt_credentials import fetch_router_password, helper_configured

    app = create_app()
    with app.app_context():
        if not helper_configured():
            print("ABORTA: el sidecar de Passbolt no esta configurado (PASSBOLT_HELPER_URL).")
            return 2
        c = ZabbixClient.from_environment()
        hosts = c._jsonrpc("host.get", {
            "output": ["hostid", "host", "name", "status"],
            "selectMacros": ["hostmacroid", "macro", "type"],
            "selectInterfaces": ["ip"],
        })
        wanted = {h.strip() for h in a.hostids.split(",") if h.strip()}

        target = []
        for h in hosts:
            if wanted and h["hostid"] not in wanted:
                continue
            if a.only_enabled and str(h.get("status")) != "0":
                continue
            for m in h.get("macros", []):
                if m["macro"] == MACRO and str(m.get("type")) == "1":
                    target.append((h, m))
                    break
        target.sort(key=lambda t: int(t[0]["hostid"]))
        print(f"hosts con {MACRO} SECRETA: {len(target)}", flush=True)
        if a.limit:
            target = target[: a.limit]
            print(f"limitado a {len(target)}", flush=True)

        ok = nopw = noip = err = 0
        pendientes = []
        for i, (h, m) in enumerate(target, 1):
            ips = [x.get("ip") for x in h.get("interfaces", []) if x.get("ip")]
            if not ips:
                noip += 1
                pendientes.append((h["hostid"], h["host"], "", "sin interfaz IP"))
                continue
            ip = ips[0]
            try:
                pw = fetch_router_password(ip, username="Ausarta")
            except Exception as e:  # noqa: BLE001
                pw = ""
                print(f"  helper ERROR {ip}: {str(e)[:60]}", flush=True)
            if not pw:
                nopw += 1
                pendientes.append((h["hostid"], h["host"], ip, "sin password en Passbolt"))
                continue
            if not a.apply:
                ok += 1
                if i <= 8 or i % 100 == 0:
                    print(f"  [dry] {ip:16} {h['host'][:60]}  (pasaria a TEXTO)", flush=True)
                continue
            try:
                c._jsonrpc("usermacro.update", {
                    "hostmacroid": m["hostmacroid"], "value": pw, "type": "0",
                })
                ok += 1
                if i % 25 == 0 or i == len(target):
                    print(f"  ... {i}/{len(target)}  a_texto={ok} sin_pw={nopw} err={err}", flush=True)
            except Exception as e:  # noqa: BLE001
                err += 1
                pendientes.append((h["hostid"], h["host"], ip, f"error API: {str(e)[:60]}"))
                if err <= 10:
                    print(f"  ERROR {h['host'][:40]}: {str(e)[:60]}", flush=True)

        if pendientes:
            with open(REPORT, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["hostid", "host", "ip", "motivo"])
                w.writerows(pendientes)
            print(f"pendientes -> {REPORT}", flush=True)

        modo = "APLICADO" if a.apply else "DRY-RUN"
        print(f"\n== {modo}: a texto {ok} | sin password en Passbolt {nopw} | "
              f"sin IP {noip} | errores {err} ==", flush=True)
        if not a.apply:
            print("Repite con --apply para escribir.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
