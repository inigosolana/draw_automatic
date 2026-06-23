from __future__ import annotations

import re
from datetime import datetime, timedelta

from flask import Blueprint, Response, render_template
from flask_limiter.util import get_remote_address

import web_app
from web.services.stats import build_admin_chart_periods, build_coverage_data
from web_app import (
    ADMIN_USERS,
    current_technician,
    get_drawio_stores,
    load_glpi_catalog,
    login_required,
    security_logger,
)
from generator.utils import technician_is_admin


def create_admin_blueprint() -> Blueprint:
    bp = Blueprint("admin", __name__)

    @bp.get("/admin")
    @login_required
    def admin_dashboard() -> str:
        drawio_stores = get_drawio_stores()
        technician = current_technician()
        if not technician_is_admin(technician, ADMIN_USERS):
            tech_name = (
                technician.get("name") or technician.get("username") or ""
            ).strip().lower()
            security_logger.warning(
                f"Acceso denegado a /admin: user={tech_name}, IP={get_remote_address()}"
            )
            return Response("Acceso restringido.", status=403, mimetype="text/plain; charset=utf-8")

        now = datetime.utcnow()
        all_rows = drawio_stores.activity.list_all() if hasattr(drawio_stores.activity, "list_all") else []
        today = [r for r in all_rows if datetime.utcfromtimestamp(r["created_at"]).date() == now.date()]
        week = [r for r in all_rows if datetime.utcfromtimestamp(r["created_at"]) >= now - timedelta(days=7)]
        month = [r for r in all_rows if datetime.utcfromtimestamp(r["created_at"]) >= now - timedelta(days=30)]
        chart_periods = build_admin_chart_periods(all_rows, now)

        coverage_data = None
        try:
            glpi_client = web_app.GlpiClient.from_environment()
            if glpi_client:
                catalog_for_coverage, _ = load_glpi_catalog()
                if catalog_for_coverage:
                    cached = drawio_stores.catalog.get("admin_coverage")
                    if cached is not None:
                        coverage_data = cached
                    else:
                        coverage_data = build_coverage_data(catalog_for_coverage, glpi_client, all_rows)
                        drawio_stores.catalog.set("admin_coverage", coverage_data)
        except Exception:
            pass

        recent_events = drawio_stores.seclog.recent(limit=200)
        warn_count = 0
        for ev in recent_events:
            ev["ts_label"] = datetime.fromtimestamp(ev["ts"]).strftime("%d/%m/%Y %H:%M:%S")
            clean = re.sub(
                r'^\[[\d\-: ,]+\]\s*(WARNING|INFO|ERROR|CRITICAL)\s*\[SECURITY\]\s*',
                "",
                ev.get("message", ""),
            )
            ev["message_clean"] = clean or ev.get("message", "")
            if ev.get("level") in ("WARNING", "ERROR", "CRITICAL"):
                warn_count += 1
        return render_template(
            "admin.html",
            total_today=len(today),
            total_week=len(week),
            total_month=len(month),
            total_all=len(all_rows),
            recent_events=recent_events,
            technician=technician,
            warn_count=warn_count,
            chart_periods=chart_periods,
            now_label=now.strftime("%d/%m/%Y %H:%M") + " UTC",
            coverage_data=coverage_data,
        )

    return bp
