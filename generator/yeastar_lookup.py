"""Consulta al backend Yeastar Unificado para resolver, a partir de la MAC de un
terminal, su EXTENSIÓN (auto-provisión Yeastar/nubes de fabricante) y su IP
(tabla ARP + DHCP del router del cliente, por CIF).

Se usa al importar una oferta: para los terminales que llegan SIN extensión o SIN
IP, se rellenan como sugerencia editable (el técnico revisa antes de generar).

Config por entorno (no bloquea si falta): YEASTAR_LOOKUP_URL, YEASTAR_LOOKUP_TOKEN.
"""

from __future__ import annotations

import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _norm_mac(value: str) -> str:
    """MAC a solo hex mayúsculas (sin separadores) para cruzar entre fuentes."""
    return "".join(c for c in str(value or "").upper() if c in "0123456789ABCDEF")


class YeastarLookup:
    def __init__(self, url: str, token: str, *, timeout: float = 20.0) -> None:
        self.url = url.split("?")[0].rstrip("/") if url.endswith("/") else url.split("?")[0]
        self.token = token
        self.timeout = timeout

    @classmethod
    def from_environment(cls) -> "YeastarLookup | None":
        url = os.environ.get("YEASTAR_LOOKUP_URL", "").strip()
        token = os.environ.get("YEASTAR_LOOKUP_TOKEN", "").strip()
        if not url or not token:
            return None
        return cls(url, token)

    def registrar_backup(self, cif: str, backup: dict, cliente: str = "") -> bool:
        """Registra en Yeastar Unificado un backup 4G detectado en el draw (para
        que su conectividad cuente «Fibra + Router 4G», origen draw). No bloquea."""
        if not cif or not (backup or {}).get("mac"):
            return False
        payload = json.dumps({
            "cif": cif,
            "mac": backup.get("mac", ""),
            "board": backup.get("board", ""),
            "model": _backup_model_from_neighbor(backup),
            "cliente": cliente or "",
            "token": self.token,
        }).encode("utf-8")
        req = Request(
            f"{self.url}-backup",
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                json.loads(resp.read().decode("utf-8"))
            return True
        except Exception:  # noqa: BLE001 - registro best-effort
            return False

    def por_cif(self, cif: str) -> tuple[dict[str, dict], dict, dict, dict]:
        """Devuelve (por_mac, info_arp, backup, por_sn).
        por_mac[MAC_hex] = {ext, ip, model, sn, ...}; por_sn[S/N] = {mac, ext, ip, model}.
        backup = dispositivo detectado en ETH2 del router (WAP LTE / 4G) o {}."""
        query = urlencode({"cif": cif or "", "token": self.token})
        req = Request(f"{self.url}?{query}", headers={"Accept": "application/json"})
        with urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        por_mac_raw = data.get("porMac") or {}
        por_mac = {_norm_mac(k): v for k, v in por_mac_raw.items() if _norm_mac(k)}
        por_sn = {str(k).strip(): v for k, v in (data.get("porSn") or {}).items() if str(k).strip()}
        return por_mac, (data.get("arp") or {}), (data.get("backup") or {}), por_sn


def enrich_terminals_from_yeastar(result) -> list[str]:
    """Rellena extensión/IP que falten en los terminales de `result` cruzando por
    MAC con Yeastar/router. Devuelve avisos de lo autocompletado (para mostrarlos).
    No bloquea: si no hay config o falla la consulta, devuelve un aviso y sigue."""
    terminals = getattr(result, "terminals", None) or []
    lookup = YeastarLookup.from_environment()
    if not lookup or not terminals:
        return []
    try:
        por_mac, _arp, backup, por_sn = lookup.por_cif(getattr(result, "cif", "") or "")
    except Exception as exc:  # noqa: BLE001 - no bloquear la importación
        return [f"No se pudo consultar Yeastar/router para autocompletar extensión/IP: {exc}"]

    avisos: list[str] = []
    # Backup 4G / WAP LTE detectado en ETH2 del router que NO venía en la oferta.
    backup_avisos = _apply_router_backup(result, backup)
    avisos.extend(backup_avisos)
    if backup_avisos:  # se ha aplicado un backup nuevo: registrarlo en Yeastar.
        try:
            lookup.registrar_backup(
                getattr(result, "cif", "") or "", backup, getattr(result, "cliente", "") or ""
            )
        except Exception:  # noqa: BLE001 - registro best-effort, no bloquea
            pass

    # En vez de un aviso gigante listando todo (los valores ya se ven en la
    # tabla), damos: un RESUMEN corto de cuántos se autocompletaron, y avisos
    # individuales SOLO para lo que el técnico debe mirar (MAC hallada por nº de
    # serie, y discrepancias de extensión nube≠provisión).
    n_auto = 0
    por_serie: list[str] = []
    discrepancias: list[str] = []
    for t in terminals:
        mac = _norm_mac(t.get("mac", ""))
        info = None
        por_sn_hit = None
        if mac:
            info = por_mac.get(mac)
        else:
            # SIN MAC en la oferta: casar por NÚMERO DE SERIE contra la nube
            # (Yealink/Grandstream traen sn; Fanvil no).
            serial = str(t.get("serial") or "").strip()
            if serial and serial in por_sn:
                por_sn_hit = por_sn[serial]
                nueva_mac = _format_mac(por_sn_hit.get("mac", ""))
                if nueva_mac:
                    t["mac"] = nueva_mac
                    info = {"ext": por_sn_hit.get("ext"), "ip": por_sn_hit.get("ip"), "en_nube": True}
        if not info:
            continue
        modelo = t.get("model") or "terminal"
        rellenado = False
        if not str(t.get("extension") or "").strip() and info.get("ext"):
            t["extension"] = str(info["ext"])
            rellenado = True
            ext_nube = str(info.get("ext_nube") or "")
            ext_autop = str(info.get("ext_autop") or "")
            if ext_nube and ext_autop and ext_nube != ext_autop:
                discrepancias.append(
                    f"⚠️ {modelo} (EXT): la nube dice {ext_nube} y la provisión {ext_autop}. Verifica cuál es."
                )
        if not str(t.get("ip") or "").strip() and info.get("ip"):
            t["ip"] = str(info["ip"])
            rellenado = True
        if rellenado:
            n_auto += 1
        if por_sn_hit and t.get("mac"):
            por_serie.append(
                f"🔎 {modelo}: MAC {t.get('mac')} encontrada por nº de serie en la nube"
                + (f" (EXT {info.get('ext')})" if info.get("ext") else "")
            )

    if n_auto:
        avisos.append(
            f"✅ Extensión e IP autocompletadas en {n_auto} teléfono(s) "
            "(nube + router). Revísalas en la tabla de Telefonía."
        )
    avisos.extend(por_serie)
    avisos.extend(discrepancias)
    return avisos


def _format_mac(hex_mac: str) -> str:
    """12 hex -> 'AA:BB:CC:DD:EE:FF'. Cadena vacía si no son 12 hex."""
    h = _norm_mac(hex_mac)
    if len(h) != 12:
        return ""
    return ":".join(h[i : i + 2] for i in range(0, 12, 2))


def _backup_model_from_neighbor(backup: dict) -> str:
    """Nombre de modelo a mostrar para el backup detectado en ETH2."""
    plat = str(backup.get("platform") or "").lower()
    board = str(backup.get("board") or "").lower()
    if "teltonika" in plat or "rut" in board:
        return "TELTONIKA"
    if "mikrotik" in plat or "wap" in board or "ltap" in board or "lte" in board:
        return "WAP LTE"
    return "WAP LTE"


def _apply_router_backup(result, backup: dict) -> list[str]:
    """Si el router tiene un backup 4G en ETH2 (WAP LTE/Teltonika) que NO viene en
    la oferta, rellena la conectividad (tipo 'FIBRA + BACK UP' + modelo backup),
    guarda su MAC para dibujarla, y avisa. No pisa un backup que ya venga."""
    mac = str((backup or {}).get("mac") or "").strip()
    if not mac:
        return []
    ya_tiene = str(getattr(result, "backup_modelo", "") or "").strip()
    if ya_tiene:
        return []  # la oferta ya trae backup: no tocamos
    modelo = _backup_model_from_neighbor(backup)
    result.backup_modelo = modelo
    tipo_up = str(getattr(result, "internet_tipo", "") or "").upper()
    # Fibra + 4G de backup. No tocar si ya es un tipo 4G puro.
    if "BACK UP" not in tipo_up and "4G" not in tipo_up:
        result.internet_tipo = "FIBRA + BACK UP"
    # MAC para el dibujo (la lee el layout en internet.backup_mac).
    setattr(result, "backup_mac", mac)
    board = str(backup.get("board") or "").strip()
    return [
        f"⚠ Detectado un backup 4G en el ETH2 del router que NO venía en la oferta: "
        f"{modelo} (MAC {mac}{', ' + board if board else ''}). Se ha añadido al diagrama "
        "y a la conectividad como «Fibra + Router 4G». Revísalo."
    ]
