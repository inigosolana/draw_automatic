from __future__ import annotations

import re
from datetime import datetime, timedelta

from flask import Blueprint, Response, redirect, render_template, request, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from app_context import (
    ADMIN_USERS,
    current_technician,
    get_drawio_stores,
    login_required,
    security_logger,
)
from web.services.glpi_catalog import load_glpi_catalog
from generator.diagram_metadata import enrich_activity_rows
from generator.glpi_client import GlpiClient, GlpiError
from generator.safe_errors import public_error_message
from generator.utils import MADRID_TZ, technician_is_admin
from web.services.stats import build_admin_chart_periods, build_coverage_data


def _admin_access_denied(technician: dict | None) -> Response | None:
    if not technician_is_admin(technician, ADMIN_USERS):
        tech_name = ((technician or {}).get("name") or (technician or {}).get("username") or "").strip().lower()
        security_logger.warning(
            f"Acceso denegado a admin: user={tech_name}, IP={get_remote_address()}"
        )
        return Response("Acceso restringido.", status=403, mimetype="text/plain; charset=utf-8")
    return None


def create_admin_blueprint(limiter: Limiter) -> Blueprint:
    bp = Blueprint("admin", __name__)

    @bp.get("/admin")
    @login_required
    def admin_dashboard() -> str:
        drawio_stores = get_drawio_stores()
        technician = current_technician()
        denied = _admin_access_denied(technician)
        if denied:
            return denied

        now = datetime.now(MADRID_TZ)
        all_rows = drawio_stores.activity.list_all() if hasattr(drawio_stores.activity, "list_all") else []
        today: list = []
        week: list = []
        month: list = []
        week_start = now - timedelta(days=7)
        month_start = now - timedelta(days=30)
        for r in all_rows:
            ts = r.get("created_at")
            if not isinstance(ts, (int, float)):
                continue
            created = datetime.fromtimestamp(ts, MADRID_TZ)
            if created.date() == now.date():
                today.append(r)
            if created >= week_start:
                week.append(r)
            if created >= month_start:
                month.append(r)
        chart_periods = build_admin_chart_periods(all_rows, now)

        coverage_data = None
        try:
            glpi_client = GlpiClient.from_environment()
            if glpi_client:
                cached = drawio_stores.catalog.get("admin_coverage")
                if cached is not None:
                    coverage_data = cached
                else:
                    # Una sola sesión GLPI para catálogo + cobertura.
                    with glpi_client.batch_session():
                        catalog_for_coverage, _ = load_glpi_catalog(glpi_client)
                        if catalog_for_coverage:
                            coverage_data = build_coverage_data(catalog_for_coverage, glpi_client, all_rows)
                            if coverage_data and not coverage_data.get("error"):
                                drawio_stores.catalog.set("admin_coverage", coverage_data)
        except Exception as exc:  # noqa: BLE001 - la cobertura es opcional; no debe tumbar /admin
            security_logger.warning(f"No se pudo calcular la cobertura del admin: {exc}")

        recent_events = drawio_stores.seclog.recent(limit=200)
        warn_count = 0
        for ev in recent_events:
            ts = ev.get("ts")
            ev["ts_label"] = (
                datetime.fromtimestamp(ts, MADRID_TZ).strftime("%d/%m/%Y %H:%M:%S")
                if isinstance(ts, (int, float))
                else ""
            )
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
            now_label=now.strftime("%d/%m/%Y %H:%M %Z"),
            coverage_data=coverage_data,
        )

    @bp.get("/admin/diagrams")
    @login_required
    def admin_diagrams() -> str:
        drawio_stores = get_drawio_stores()
        technician = current_technician()
        denied = _admin_access_denied(technician)
        if denied:
            return denied

        client = GlpiClient.from_environment()
        rows = enrich_activity_rows(drawio_stores.activity.list_all(), client)

        # Provincia por sede (entity_id) desde el catálogo, para poder filtrar por ella.
        entity_province: dict[int, str] = {}
        catalog, _ = load_glpi_catalog()
        for province in catalog or []:
            for customer in province.get("clientes", []):
                for site in customer.get("sedes", []):
                    sid_str = str(site.get("id") or "").strip()
                    if sid_str.isdigit():
                        entity_province[int(sid_str)] = province.get("nombre", "")
        for row in rows:
            eid = row.get("entity_id")
            eid_str = str(eid).strip() if eid is not None else ""
            row["province"] = entity_province.get(int(eid_str), "") if eid_str.isdigit() else ""

        # Los filtros (provincia/cliente/sede/técnico) los construye el frontend
        # a partir de los data-* de cada diagrama, en cascada y buscables.
        deleted_id = request.args.get("deleted", "").strip()
        delete_error = request.args.get("error", "").strip()
        return render_template(
            "admin_diagrams.html",
            diagrams=rows,
            technician=technician,
            deleted_id=deleted_id if deleted_id.isdigit() else "",
            delete_error=delete_error,
        )

    @bp.post("/admin/diagrams/delete")
    @login_required
    @limiter.limit("30 per hour")
    def admin_delete_diagram() -> Response:
        drawio_stores = get_drawio_stores()
        technician = current_technician()
        denied = _admin_access_denied(technician)
        if denied:
            return denied

        diagram_id_raw = request.form.get("diagram_id", "").strip()
        if not diagram_id_raw.isdigit():
            return redirect(url_for("admin.admin_diagrams", error="ID de diagrama no valido."))

        diagram_id = int(diagram_id_raw)
        client = GlpiClient.from_environment()
        if not client:
            return redirect(url_for("admin.admin_diagrams", error="GLPI no esta configurado."))

        tech_name = (technician.get("name") or technician.get("username") or "").strip()
        try:
            client.delete_network_diagram(diagram_id)
            removed_rows = drawio_stores.activity.delete_by_diagram_id(diagram_id)
            drawio_stores.catalog.clear("admin_coverage")
            security_logger.info(
                "Admin deleted diagram: diagram_id=%s admin=%s activity_rows=%s IP=%s",
                diagram_id,
                tech_name,
                removed_rows,
                get_remote_address(),
            )
        except GlpiError as exc:
            security_logger.warning(
                "Admin diagram delete failed: diagram_id=%s admin=%s error=%s IP=%s",
                diagram_id,
                tech_name,
                exc,
                get_remote_address(),
            )
            return redirect(
                url_for(
                    "admin.admin_diagrams",
                    error=public_error_message(str(exc), context="eliminacion del diagrama"),
                )
            )

        return redirect(url_for("admin.admin_diagrams", deleted=diagram_id))

    return bp
