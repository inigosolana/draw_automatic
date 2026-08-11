from __future__ import annotations

import os

from flask import Blueprint, jsonify, render_template, request, url_for
from flask_limiter import Limiter

from app_context import current_technician, login_required, technician_can_use_zabbix
from generator.routeros_version import fetch_router_version, helper_configured
from generator.safe_errors import public_error_message
from generator.zabbix_client import ZabbixClient, ZabbixError
from generator.zabbix_helpers import strip_cidr
from generator.zabbix_profiles import (
    BACKUP_TYPES,
    FIBER_PROVIDERS,
    INSTALL_TYPES,
    LTE_TEMPLATES,
    ZabbixProfileError,
    build_install_plan,
    default_routeros_username,
    needs_version,
    zabbix_questionnaire_defaults,
)
from generator.work_order_zabbix import work_order_to_prefill
from web.services.glpi_catalog import load_glpi_catalog


def _form_from_request(source) -> dict[str, str]:
    defaults = zabbix_questionnaire_defaults()
    return {
        **defaults,
        "tipo": source.get("tipo", "").strip() or defaults["tipo"],
        "provincia": source.get("provincia", "").strip(),
        "cliente": source.get("cliente", "").strip(),
        "sede": source.get("sede", "").strip(),
        "localidad": source.get("localidad", "").strip(),
        "calle": source.get("calle", "").strip(),
        "proveedor": source.get("proveedor", "").strip(),
        "proveedor_backup": source.get("proveedor_backup", "").strip(),
        "router_ip": strip_cidr(source.get("router_ip", "").strip()),
        "backup_ip": strip_cidr(source.get("backup_ip", "").strip()),
        "backup_tipo": source.get("backup_tipo", "").strip(),
        "lte_templateid": source.get("lte_templateid", "").strip(),
        "snmp_community": source.get("snmp_community", "").strip() or defaults["snmp_community"],
    }


def _resolve_is_v7(source, router_ip: str, router_password: str) -> tuple[bool, str, str]:
    """Devuelve (is_v7, nota, error). Prioriza el helper; si no, el campo manual."""
    manual = source.get("routeros_version", "").strip().lower()  # "v6" | "v7" | ""
    if helper_configured() and router_ip and router_password:
        result = fetch_router_version(
            router_ip, default_routeros_username(), router_password
        )
        if result.known:
            note = f"Versión detectada: {result.version} → {'BGP V7' if result.is_v7 else 'BGP'}"
            return result.is_v7, note, ""
        # Helper configurado pero no pudo: caemos al manual si existe.
        if manual in ("v6", "v7"):
            return manual == "v7", f"Versión indicada a mano ({manual}).", ""
        return False, "", (
            "No se pudo detectar la versión del router "
            f"({result.error}). Indica v6/v7 a mano."
        )
    if manual in ("v6", "v7"):
        return manual == "v7", f"Versión indicada a mano ({manual}).", ""
    if helper_configured() and router_ip and not router_password:
        return False, "", (
            "Falta la contraseña del router para detectar la versión "
            "(pégala o indica v6/v7 a mano)."
        )
    return False, "", (
        "Falta la versión de RouterOS: activa el helper o indica v6/v7 a mano."
    )


def _enrich_prefill(prefill: dict, cif: str, cliente: str) -> dict:
    """Autorrellena IP+versión (NOP) y proveedor+backup (Yeastar) sobre el prefill.

    Nunca rompe: si los helpers no están, deja el prefill como estaba.
    """
    from generator.nop_inventory import (
        fetch_backup_ip,
        fetch_client_routers,
        fetch_client_services,
        inventory_configured,
    )
    from generator.zabbix_helpers import map_yeastar_provider

    if not inventory_configured():
        return prefill
    try:
        routers = fetch_client_routers(cif or "", cliente or "")
    except Exception:  # noqa: BLE001
        routers = []
    fiber = [r for r in routers if (r.get("type") or "fiber") == "fiber"]
    backup = [r for r in routers if r.get("type") == "backup"]

    if fiber and not prefill.get("router_ip"):
        prefill["router_ip"] = fiber[0].get("ip", "")
        prefill["routeros_version"] = "v7" if fiber[0].get("is_v7") else "v6"
        prefill["nop_version"] = fiber[0].get("version", "")
        if len(fiber) > 1:
            prefill["router_options"] = [
                {"ip": r.get("ip", ""), "version": r.get("version", ""), "is_v7": r.get("is_v7")}
                for r in fiber
            ]
    if backup and not prefill.get("backup_ip"):
        prefill["backup_ip"] = backup[0].get("ip", "")

    try:
        svc = fetch_client_services(cif or "", cliente or "")
    except Exception:  # noqa: BLE001
        svc = {}
    # CHATEAU: equipo integrado (fibra+backup en uno) -> 1 host, se detecta por el board de NOP.
    is_chateau = bool(fiber) and "chateau" in (fiber[0].get("board") or "").lower()
    if is_chateau and prefill.get("tipo") in ("fibra", "fibra_backup"):
        prefill["tipo"] = "chateau"
    if svc:
        if svc.get("proveedor") and not prefill.get("proveedor"):
            prefill["proveedor"] = map_yeastar_provider(svc["proveedor"])
        if svc.get("tiene_backup"):
            prefill["tiene_backup_detectado"] = True
            if is_chateau:
                # backup integrado en el CHATEAU -> 2º proveedor como segundo tag
                if svc.get("backup_proveedor") and not prefill.get("proveedor_backup"):
                    prefill["proveedor_backup"] = map_yeastar_provider(svc["backup_proveedor"])
            elif prefill.get("tipo") == "fibra":
                prefill["tipo"] = "fibra_backup"
                bip = fetch_backup_ip(cliente)
                if bip and not prefill.get("backup_ip"):
                    prefill["backup_ip"] = bip
                if not prefill.get("backup_tipo"):
                    prefill["backup_tipo"] = "KITE"  # Mikrotik SNMP BACKUP por defecto
    return prefill


def _passbolt_create_allowed() -> bool:
    """Guardar contraseñas en Passbolt SOLO lo puede hacer Iñigo Solana
    (configurable con PASSBOLT_CREATE_USERS, coma-separado)."""
    users = {u.strip().lower() for u in os.environ.get("PASSBOLT_CREATE_USERS", "inigo.solana").split(",") if u.strip()}
    t = current_technician() or {}
    return str(t.get("username") or "").strip().lower() in users


def _router_ip_ok(ip: str) -> bool:
    """Rechaza destinos peligrosos (loopback/link-local/multicast/reservadas/unspecified)
    para evitar SSRF vía el helper de versión / SNMP. Acepta IPs públicas y privadas."""
    import ipaddress
    try:
        a = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return False
    return not (a.is_loopback or a.is_link_local or a.is_multicast
                or a.is_unspecified or a.is_reserved)


def _host_tokens(s: str) -> set:
    import re
    import unicodedata
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s or "").upper()) if not unicodedata.combining(c))
    stop = {"SEDE", "MATRIZ", "PRINCIPAL", "CENTRAL", "OFICINA", "EMPRESA", "SEDE1"}
    return {t for t in re.split(r"[^A-Z0-9]+", s) if len(t) >= 4 and t not in stop}


# Índice IDF de hosts FTTH/BACKUP cacheado a nivel de proceso (evita traer ~3.800
# hosts y reconstruir el índice en cada "cargar datos"). TTL + invalidación al crear.
import threading as _threading
import time as _time

_INDEX_LOCK = _threading.Lock()
_INDEX_CACHE: dict = {"at": 0.0, "routers": [], "inv": None, "weight": None}
_INDEX_TTL = float(os.environ.get("ZABBIX_HOST_INDEX_TTL_S", "600"))


def _invalidate_router_index() -> None:
    with _INDEX_LOCK:
        _INDEX_CACHE["at"] = 0.0


_PROXY_CACHE: dict = {"at": 0.0, "data": []}
_PROXY_TTL = float(os.environ.get("ZABBIX_PROXY_TTL_S", "600"))


def _cached_proxies(client):
    """Lista de proxies cacheada (cambia rara vez); evita un proxy.get por render."""
    if not client:
        return []
    now = _time.time()
    with _INDEX_LOCK:
        if _PROXY_CACHE["data"] and (now - _PROXY_CACHE["at"]) < _PROXY_TTL:
            return _PROXY_CACHE["data"]
    try:
        data = client.list_proxies()
    except Exception:  # noqa: BLE001
        data = []
    with _INDEX_LOCK:
        _PROXY_CACHE.update(at=now, data=data)
    return data


def _dominant_proxy(client, groupid: str) -> str:
    """Proxy más usado por los hosts de ese grupo (para no fallar de zona)."""
    if not groupid:
        return ""
    try:
        from collections import Counter
        hosts = client._jsonrpc("host.get", {"groupids": groupid, "output": ["proxyid"]})
        c = Counter(str(h.get("proxyid") or "") for h in (hosts or [])
                    if str(h.get("proxyid") or "") not in ("", "0"))
        return c.most_common(1)[0][0] if c else ""
    except Exception:  # noqa: BLE001
        return ""


def _router_index(client):
    """(routers, inv, weight) del índice IDF de hosts FTTH/BACKUP, cacheado."""
    import math
    from collections import defaultdict
    now = _time.time()
    with _INDEX_LOCK:
        if _INDEX_CACHE["inv"] is not None and (now - _INDEX_CACHE["at"]) < _INDEX_TTL:
            return _INDEX_CACHE["routers"], _INDEX_CACHE["inv"], _INDEX_CACHE["weight"]
    hs = client._jsonrpc("host.get", {"output": ["host"]})
    routers = [h["host"] for h in hs
               if h["host"].upper().startswith(("FTTH", "FTHH", "BACKUP", "BACK_UP"))]
    inv = defaultdict(set)
    for i, n in enumerate(routers):
        for t in _host_tokens(n):
            inv[t].add(i)
    N = max(1, len(routers))
    weight = {t: math.log(N / len(s)) for t, s in inv.items()}
    with _INDEX_LOCK:
        _INDEX_CACHE.update(at=now, routers=routers, inv=inv, weight=weight)
    return routers, inv, weight


def _existing_zabbix_hosts(cliente: str) -> dict:
    """Comprueba si el cliente YA tiene host de fibra y/o backup en Zabbix.

    Empareja por el nombre del cliente ponderando la RAREZA de cada token (IDF),
    para no confundir con genéricos ("CONSULTING", "EXPRESS"...). Devuelve
    {'fibra': <host o "">, 'backup': <host o "">}. Nunca rompe.
    """
    from collections import defaultdict

    out = {"fibra": "", "backup": ""}
    try:
        client = ZabbixClient.from_environment()
        if not client or not cliente:
            return out
        ct = _host_tokens(cliente)
        if not ct:
            return out
        routers, inv, weight = _router_index(client)
        namew = defaultdict(float)
        maxw = defaultdict(float)
        for t in ct:
            w = weight.get(t, 0)
            if w <= 0:
                continue
            for i in inv.get(t, ()):
                namew[i] += w
                if w > maxw[i]:
                    maxw[i] = w
        for i in sorted(namew, key=lambda i: -namew[i]):
            if namew[i] < 4.0 or maxw[i] < 3.0:  # exige coincidencia sólida + token distintivo
                break
            up = routers[i].upper()
            if not out["fibra"] and up.startswith(("FTTH", "FTHH")):
                out["fibra"] = routers[i]
            elif not out["backup"] and up.startswith(("BACKUP", "BACK_UP")):
                out["backup"] = routers[i]
    except Exception:  # noqa: BLE001
        pass
    return out


def create_zabbix_blueprint(limiter: Limiter) -> Blueprint:
    bp = Blueprint("zabbix", __name__)

    def _render(form_data, *, success=None, errors=None):
        client = ZabbixClient.from_environment()
        glpi_customers, glpi_error = load_glpi_catalog()
        proxies = _cached_proxies(client)
        return render_template(
            "zabbix_create_host.html",
            configured=client is not None,
            helper_configured=helper_configured(),
            form_data=form_data,
            glpi_customers=glpi_customers,
            glpi_error=glpi_error,
            fiber_providers=FIBER_PROVIDERS,
            backup_types=BACKUP_TYPES,
            install_types=INSTALL_TYPES,
            lte_templates=LTE_TEMPLATES,
            proxies=proxies,
            passbolt_allowed=_passbolt_create_allowed(),
            technician=current_technician(),
            success=success,
            errors=errors or [],
            group_lookup_url=url_for("zabbix.lookup_group"),
            version_lookup_url=url_for("zabbix.lookup_version"),
            ot_lookup_url=url_for("zabbix.from_ot"),
            client_lookup_url=url_for("zabbix.from_client"),
        )

    @bp.get("/zabbix/api/group")
    @login_required
    @limiter.limit("120 per hour")
    def lookup_group():
        if not technician_can_use_zabbix():
            return jsonify({"error": "No tienes permiso para el alta en Zabbix."}), 403
        provincia = request.args.get("provincia", "").strip()
        role = request.args.get("role", "Fibra").strip() or "Fibra"
        if not provincia:
            return jsonify({"error": "Indica una provincia."}), 400
        client = ZabbixClient.from_environment()
        if not client:
            return jsonify({"error": "Zabbix no esta configurado."}), 503
        try:
            group = client.resolve_router_group(provincia, role)
        except ZabbixError as exc:
            return jsonify({"error": public_error_message(str(exc), context="grupo Zabbix")}), 404
        return jsonify({"groupid": str(group.get("groupid", "")), "name": str(group.get("name", ""))})

    @bp.get("/zabbix/api/from-ot")
    @login_required
    @limiter.limit("120 per hour")
    def from_ot():
        if not technician_can_use_zabbix():
            return jsonify({"error": "No tienes permiso para el alta en Zabbix."}), 403
        ot = request.args.get("ot", "").strip()
        if not ot:
            return jsonify({"error": "Indica el número de OT."}), 400
        from generator.import_errors import CommsError
        from generator.work_order_import import import_work_order_by_id
        try:
            result = import_work_order_by_id(ot)
        except CommsError as exc:
            return jsonify({"error": public_error_message(str(exc), context="OT")}), 404
        except Exception as exc:  # noqa: BLE001 - degradar con mensaje seguro
            return jsonify({"error": public_error_message(str(exc), context="OT")}), 502
        glpi_customers, _ = load_glpi_catalog()
        prefill = work_order_to_prefill(result, glpi_customers=glpi_customers)
        prefill = _enrich_prefill(prefill, getattr(result, "cif", "") or "", prefill.get("cliente", ""))
        prefill["existentes"] = _existing_zabbix_hosts(prefill.get("cliente", ""))
        return jsonify(prefill)

    @bp.get("/zabbix/api/from-client")
    @login_required
    @limiter.limit("120 per hour")
    def from_client():
        if not technician_can_use_zabbix():
            return jsonify({"error": "No tienes permiso para el alta en Zabbix."}), 403
        cliente = request.args.get("cliente", "").strip()
        sede = request.args.get("sede", "").strip()
        cif = request.args.get("cif", "").strip()
        if not cliente and not cif:
            return jsonify({"error": "Indica cliente o CIF."}), 400
        import types
        glpi_customers, _ = load_glpi_catalog()
        fake = types.SimpleNamespace(
            work_order_id="", cliente=cliente, cif=cif, sede=sede, direccion="",
            internet_tipo="SOLO FIBRA", internet_proveedor="", router_modelo="",
            backup_modelo="", router_ip="", warnings=[],
        )
        prefill = work_order_to_prefill(fake, glpi_customers=glpi_customers)
        prefill = _enrich_prefill(prefill, cif, cliente or prefill.get("cliente", ""))
        prefill["existentes"] = _existing_zabbix_hosts(cliente or prefill.get("cliente", ""))
        return jsonify(prefill)

    @bp.post("/zabbix/api/version")
    @login_required
    @limiter.limit("120 per hour")
    def lookup_version():
        if not technician_can_use_zabbix():
            return jsonify({"ok": False, "error": "No tienes permiso para el alta en Zabbix."}), 403
        payload = request.get_json(silent=True) or {}
        ip = strip_cidr(str(payload.get("router_ip", "")).strip())
        password = str(payload.get("router_password", ""))
        if not helper_configured():
            return jsonify({"ok": False, "error": "Helper de versión no configurado."}), 503
        if not ip or not password:
            return jsonify({"ok": False, "error": "Faltan IP y contraseña del router."}), 400
        if not _router_ip_ok(ip):
            return jsonify({"ok": False, "error": "IP de router no válida o no permitida."}), 400
        result = fetch_router_version(ip, default_routeros_username(), password)
        return jsonify(
            {
                "ok": result.ok,
                "version": result.version,
                "is_v7": result.is_v7,
                "board": result.board,
                "template": ("Template RouterOS BGP V7" if result.is_v7 else "Template RouterOS BGP")
                if result.known else "",
                "error": result.error,
            }
        )

    @bp.route("/zabbix", methods=["GET", "POST"])
    @login_required
    @limiter.limit("40 per hour")
    def create_host():
        if not technician_can_use_zabbix():
            tech = current_technician()
            return (
                render_template(
                    "zabbix_create_host.html",
                    configured=False,
                    helper_configured=False,
                    form_data=zabbix_questionnaire_defaults(),
                    glpi_customers=[],
                    glpi_error="",
                    fiber_providers=FIBER_PROVIDERS,
                    backup_types=BACKUP_TYPES,
                    install_types=INSTALL_TYPES,
                    lte_templates=LTE_TEMPLATES,
                    proxies=[],
                    technician=tech,
                    success=None,
                    not_authorized=True,
                    errors=[
                        "El alta en Zabbix está restringida. Pídesela a Iñigo Solana, "
                        "Alberto Ferez o Marcos Medina."
                    ],
                    group_lookup_url="",
                    version_lookup_url="",
                ),
                403,
            )
        if request.method == "GET":
            return _render(_form_from_request(request.args))

        form_data = _form_from_request(request.form)
        router_password = request.form.get("router_password", "")
        # Contraseña que TECLEA el técnico (antes de cualquier auto-fetch) — es la que
        # se guardaría en Passbolt si marca la casilla.
        typed_password = router_password.strip()
        save_passbolt = request.form.get("guardar_passbolt", "") == "on"
        errors: list[str] = []

        client = ZabbixClient.from_environment()
        if not client:
            return _render(form_data, errors=["Zabbix no está configurado en el servidor."])
        tipo = form_data["tipo"]
        if not form_data["provincia"]:
            errors.append("Selecciona la provincia.")
        if not form_data["cliente"] or not form_data["sede"]:
            errors.append("Indica cliente y sede.")
        if not form_data["router_ip"]:
            errors.append("Indica la IP del equipo.")
        elif not _router_ip_ok(form_data["router_ip"]):
            errors.append("La IP del equipo no es válida o no está permitida.")
        if form_data["backup_ip"].strip() and not _router_ip_ok(form_data["backup_ip"]):
            errors.append("La IP del backup no es válida o no está permitida.")
        if errors:
            return _render(form_data, errors=errors)

        # Fibra + backup: si el cliente tiene backup pero falta la IP de túnel, NO
        # bloqueamos el alta; se crea la fibra y se avisa de que el backup queda
        # pendiente de su IP (así nunca se pierde la fibra por no tener la del backup).
        backup_pending_note = ""
        if tipo == "fibra_backup" and not form_data["backup_ip"].strip():
            tipo = "fibra"
            form_data["tipo"] = "fibra"
            backup_pending_note = ("Aviso: el cliente tiene backup pero falta su IP de túnel; "
                                   "se ha creado solo la fibra. Añade el backup cuando tengas la IP.")

        # Contraseña del router: si el técnico no la pegó y hay helper Passbolt,
        # se obtiene automáticamente por la IP (solo tipos con RouterOS/BGP).
        password_note = ""
        if needs_version(tipo) and not router_password:
            from generator.passbolt_credentials import fetch_router_password, helper_configured
            if helper_configured():
                from flask import current_app
                _t = current_technician()
                _who = str(_t.get("username") or _t.get("name") or "?")
                # Aviso de propiedad: la IP debería estar entre los routers del cliente en NOP.
                _owned = True
                try:
                    from generator.nop_inventory import fetch_client_routers
                    _rs = fetch_client_routers("", form_data["cliente"]) or []
                    _ips = {str(r.get("ip") or "").strip() for r in _rs}
                    if _ips and form_data["router_ip"] not in _ips:
                        _owned = False
                except Exception:  # noqa: BLE001
                    pass
                # AUDITORÍA: toda resolución de credencial queda registrada (quién/IP/cliente).
                current_app.logger.info(
                    "[AUDIT] passbolt-fetch tecnico=%s ip=%s cliente=%s owned=%s",
                    _who, form_data["router_ip"], form_data["cliente"], _owned)
                auto = fetch_router_password(
                    form_data["router_ip"], username=default_routeros_username()
                )
                if auto:
                    router_password = auto
                    password_note = "Contraseña obtenida de Passbolt." + (
                        "" if _owned else " (AVISO: la IP no figura entre los routers del cliente en NOP)")

        # La versión RouterOS solo se necesita en los tipos con BGP (fibra/chateau/dual).
        is_v7, version_note = False, ""
        if needs_version(tipo):
            is_v7, version_note, version_error = _resolve_is_v7(
                request.form, form_data["router_ip"], router_password
            )
            if version_error:
                return _render(form_data, errors=[version_error])

        lte_label = next((lbl for lbl, tid in LTE_TEMPLATES if tid == form_data["lte_templateid"]), "")
        try:
            plan = build_install_plan(
                tipo=tipo,
                cliente=form_data["cliente"],
                sede=form_data["sede"],
                proveedor=form_data["proveedor"],
                proveedor_backup=form_data["proveedor_backup"],
                router_ip=form_data["router_ip"],
                is_v7=is_v7,
                localidad=form_data["localidad"],
                calle=form_data["calle"],
                backup_ip=form_data["backup_ip"],
                backup_tipo=form_data["backup_tipo"],
                lte_templateid=form_data["lte_templateid"],
                lte_label=lte_label,
                router_password=router_password,
                snmp_community=form_data["snmp_community"],
            )
        except ZabbixProfileError as exc:
            return _render(form_data, errors=[str(exc)])

        # Quién sube el host: nombre GLPI del técnico logueado, en la Description.
        from datetime import datetime, timezone

        tech = current_technician()
        subido_por = str(tech.get("name") or tech.get("username") or "").strip()
        fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        description = f"Subido a Zabbix por {subido_por} el {fecha} (herramienta draw_automatic)" if subido_por else ""

        # Coordenadas reales de la sede (para el geomapa): se geocodifica la dirección
        # de GLPI una vez y se comparte entre el router y su backup de la misma sede.
        from generator.geocode import geocode_es
        try:
            loc_lat, loc_lon = geocode_es(form_data["calle"], form_data["localidad"], form_data["provincia"])
        except Exception:  # noqa: BLE001
            loc_lat, loc_lon = "", ""

        created = []
        manual_proxy = request.form.get("proxyid", "").strip()
        _grp_memo: dict = {}  # role -> (group, gid, pid) para no repetir resolve/host.get por spec
        try:
            for spec in plan.hosts:
                if client.find_host_by_name(spec.host):
                    errors.append(f"Ya existe un host «{spec.host}» en Zabbix; se omite.")
                    continue
                if spec.group_role in _grp_memo:
                    group, gid, pid = _grp_memo[spec.group_role]
                else:
                    group = client.resolve_router_group(form_data["provincia"], spec.group_role)
                    gid = str(group.get("groupid", ""))
                    # Proxy: el elegido a mano, o el dominante de la zona (evita proxy erróneo).
                    pid = manual_proxy or _dominant_proxy(client, gid)
                    _grp_memo[spec.group_role] = (group, gid, pid)
                result = client.create_host(
                    host=spec.host,
                    name=spec.name,
                    ip=spec.ip,
                    groupid=gid,
                    template_ids=spec.template_ids,
                    macros=spec.macros,
                    tags=spec.tags,
                    description=description,
                    proxyid=pid,
                    location_lat=loc_lat,
                    location_lon=loc_lon,
                )
                hostids = result.get("hostids") if isinstance(result, dict) else None
                created.append(
                    {
                        "name": spec.name,
                        "hostid": (hostids or [""])[0],
                        "ip": spec.ip,
                        "template_label": " + ".join(spec.template_labels),
                        "group_name": group.get("name", ""),
                    }
                )
        except ZabbixError as exc:
            errors.append(public_error_message(str(exc), context="alta en Zabbix"))
        if created:
            _invalidate_router_index()  # los nuevos hosts deben verse en la próxima búsqueda

        # Guardar la contraseña TECLEADA en Passbolt (opt-in, no bloqueante: si falla,
        # el host ya está creado y solo se avisa).
        passbolt_note = ""
        if created and save_passbolt and typed_password and _passbolt_create_allowed():
            from flask import current_app
            _t = current_technician()
            # AUDITORÍA (sin contraseña): quién guarda credencial, para qué cliente/IP.
            current_app.logger.info(
                "[AUDIT] passbolt-create tecnico=%s ip=%s cliente=%s",
                str(_t.get("username") or "?"), form_data["router_ip"], form_data["cliente"])
            try:
                from generator.passbolt_credentials import create_router_credential
                r = create_router_credential(
                    cliente=form_data["cliente"], cif=request.form.get("cif", "").strip(),
                    ip=form_data["router_ip"], username=default_routeros_username(),
                    password=typed_password,
                )
                if r.get("ok"):
                    passbolt_note = "Contraseña guardada en Passbolt."
                    if r.get("warn"):  # creado pero no compartido/movido a la carpeta
                        passbolt_note += " AVISO: " + public_error_message(str(r.get("warn")), context="Passbolt")
                else:
                    # Error saneado (nunca refleja el secreto).
                    passbolt_note = "AVISO: no se pudo guardar en Passbolt (" + public_error_message(
                        str(r.get("error", "")), context="Passbolt") + ")."
            except Exception as exc:  # noqa: BLE001
                passbolt_note = "AVISO: no se pudo guardar en Passbolt (" + public_error_message(
                    str(exc), context="Passbolt") + ")."

        prefix = " ".join(x for x in [version_note, password_note, backup_pending_note, passbolt_note] if x)
        prefix = f"{prefix}. " if prefix else ""
        if created and not errors:
            success = {"summary": f"{prefix}Creados {len(created)} host(s).", "hosts": created}
            return _render(form_data, success=success)
        if created:
            success = {"summary": f"{prefix}Creados {len(created)} host(s) con avisos.", "hosts": created}
            return _render(form_data, success=success, errors=errors)
        return _render(form_data, errors=errors or ["No se creó ningún host."])

    return bp
