from __future__ import annotations

from flask import Blueprint, jsonify, redirect, request, url_for
from flask_limiter import Limiter

from app_context import login_required
from generator.safe_errors import public_error_message
from generator.zabbix_client import ZabbixClient, ZabbixError
from generator.zabbix_helpers import strip_cidr
from generator.zabbix_profiles import (
    ZabbixProfileError,
    build_install_plan,
    zabbix_questionnaire_defaults,
)


def _form_from_request_args() -> dict[str, str]:
    defaults = zabbix_questionnaire_defaults()
    return {
        **defaults,
        "provincia": request.args.get("provincia", "").strip(),
        "cliente": request.args.get("cliente", "").strip(),
        "sede": request.args.get("sede", "").strip(),
        "internet_tipo": request.args.get("internet_tipo", "").strip(),
        "internet_proveedor": request.args.get("internet_proveedor", "").strip(),
        "router_modelo": request.args.get("router_modelo", "").strip(),
        "backup_modelo": request.args.get("backup_modelo", "").strip(),
        "router_ip": strip_cidr(request.args.get("router_ip", "").strip() or request.args.get("ip", "").strip()),
        "backup_ip": strip_cidr(request.args.get("backup_ip", "").strip()),
        "snmp_community": request.args.get("snmp_community", "").strip() or defaults["snmp_community"],
    }


def _plan_payload(form_data: dict[str, str]) -> dict:
    plan = build_install_plan(
        cliente=form_data.get("cliente", ""),
        sede=form_data.get("sede", ""),
        internet_tipo=form_data.get("internet_tipo", ""),
        internet_proveedor=form_data.get("internet_proveedor", ""),
        router_modelo=form_data.get("router_modelo", ""),
        backup_modelo=form_data.get("backup_modelo", ""),
        router_ip=form_data.get("router_ip", ""),
        backup_ip=form_data.get("backup_ip", ""),
    )
    return {
        "summary": plan.summary,
        "host_count": len(plan.hosts),
        "hosts": [
            {
                "role": host.role,
                "host": host.host,
                "name": host.name,
                "ip": host.ip,
                "template_label": host.template_label,
            }
            for host in plan.hosts
        ],
    }


def create_zabbix_blueprint(limiter: Limiter) -> Blueprint:
    bp = Blueprint("zabbix", __name__)

    @bp.get("/zabbix/api/group")
    @login_required
    @limiter.limit("120 per hour")
    def lookup_group():
        provincia = request.args.get("provincia", "").strip()
        if not provincia:
            return jsonify({"error": "Indica una provincia."}), 400
        client = ZabbixClient.from_environment()
        if not client:
            return jsonify({"error": "Zabbix no esta configurado."}), 503
        try:
            group = client.resolve_host_group_for_province(provincia)
        except ZabbixError as exc:
            return jsonify({"error": public_error_message(str(exc), context="grupo Zabbix")}), 404
        return jsonify(
            {
                "groupid": str(group.get("groupid", "")),
                "name": str(group.get("name", "")),
            }
        )

    @bp.get("/zabbix/api/plan")
    @login_required
    @limiter.limit("120 per hour")
    def preview_plan():
        form_data = _form_from_request_args()
        try:
            return jsonify(_plan_payload(form_data))
        except ZabbixProfileError as exc:
            return jsonify({"error": str(exc)}), 400

    @bp.route("/zabbix", methods=["GET", "POST"])
    @login_required
    @limiter.limit("20 per hour")
    def create_host() -> str:
        return redirect(url_for("home.zabbix_soon"))

    return bp
