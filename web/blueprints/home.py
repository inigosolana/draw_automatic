from __future__ import annotations

from flask import Blueprint, render_template

from app_context import login_required, technician_can_use_zabbix


def create_home_blueprint() -> Blueprint:
    bp = Blueprint("home", __name__)

    @bp.get("/")
    @login_required
    def index() -> str:
        return render_template("home.html", zabbix_allowed=technician_can_use_zabbix())

    @bp.get("/zabbix-soon")
    @login_required
    def zabbix_soon() -> str:
        return render_template("zabbix_soon.html")

    @bp.get("/passbolt")
    @login_required
    def passbolt_soon() -> str:
        return render_template("passbolt_soon.html")

    return bp
