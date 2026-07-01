from __future__ import annotations

from flask import current_app, url_for
from flask_limiter.util import get_remote_address

from app_context import current_technician, get_drawio_stores, security_logger
from generator.diagram_activity import DiagramActivity
from generator.diagram_metadata import enrich_diagram_row
from generator.glpi_client import GlpiClient, GlpiError, build_customer_catalog
from generator.safe_errors import public_error_message
from generator.site_directory import apply_saved_addresses


def relevant_entity_ids(entity_id: int, catalog: list[dict]) -> set[int]:
    """La sede + su entidad cliente (padre). En GLPI muchos diagramas se asocian
    al cliente y no a la sede; para consultarlos y para detectar duplicados hay
    que mirar ambas entidades."""
    ids = {int(entity_id)}
    for province in catalog or []:
        for customer in province.get("clientes", []):
            if any(str(s.get("id")) == str(entity_id) for s in customer.get("sedes", [])):
                if str(customer.get("id") or "").isdigit():
                    ids.add(int(customer["id"]))
    return ids


def glpi_diagram_rows(client: GlpiClient, entity_id, activity: DiagramActivity) -> list[dict]:
    """Diagramas de una sede. `entity_id` puede ser un id o un conjunto de ids
    (p. ej. la sede + su entidad cliente padre): en GLPI un diagrama puede estar
    asociado al cliente y no a la sede concreta, y aun así hay que mostrarlo."""
    if isinstance(entity_id, int):
        entity_ids = {entity_id}
    else:
        entity_ids = {int(e) for e in entity_id if str(e).isdigit()}
    activity_map: dict[int, dict] = {}
    for eid in entity_ids:
        activity_map.update(activity.map_for_entity(eid))
    rows: list[dict] = []
    for diagram in client.list_network_diagrams(None):
        diagram_id = diagram.get("id")
        if not str(diagram_id or "").isdigit():
            continue
        ent = diagram.get("entities_id")
        if not (str(ent or "").isdigit() and int(ent) in entity_ids):
            continue
        row = {
            "id": int(diagram_id),
            "name": diagram.get("name") or f"Diagrama #{diagram_id}",
            "description": diagram.get("shortdescription", ""),
            "state": diagram.get("plugin_archimap_graphstates_id", ""),
            "url": client.diagram_url(int(diagram_id)),
        }
        rows.append(enrich_diagram_row(row, activity_map))
    rows.sort(
        key=lambda item: activity_map.get(item["id"], {}).get("created_at", 0),
        reverse=True,
    )
    return rows


def load_glpi_catalog(client: GlpiClient | None = None) -> tuple[list[dict], str]:
    """Catálogo de clientes/sedes de GLPI (cacheado).

    Si la ruta ya tiene un cliente con `batch_session()` abierto puede pasarlo
    en `client` para reutilizar esa sesión en lugar de abrir otra.
    """
    drawio_stores = get_drawio_stores()
    cached = drawio_stores.catalog.get("glpi_customer_catalog")
    if cached is not None:
        return apply_saved_addresses(cached, drawio_stores.sites.all()), ""
    if client is None:
        client = GlpiClient.from_environment()
    if not client:
        return [], "GLPI no esta configurado."
    try:
        catalog = build_customer_catalog(client.list_entities())
        drawio_stores.catalog.set("glpi_customer_catalog", catalog)
        return apply_saved_addresses(catalog, drawio_stores.sites.all()), ""
    except GlpiError as exc:
        security_logger.warning(f"GLPI catalog load failed: {exc} (IP: {get_remote_address()})")
        return [], public_error_message(str(exc), context="carga del catalogo GLPI")


def comms_configured() -> bool:
    from generator.comms_client import CommsClient

    return CommsClient.from_environment() is not None


def crm_configured() -> bool:
    from generator.crm_client import crm_configured as _crm_configured

    return _crm_configured()


def index_context(**extra):
    glpi_customers, glpi_error = load_glpi_catalog()
    device_catalog = current_app.config["DEVICE_CATALOG"]
    context = {
        "device_catalog": device_catalog,
        "glpi_customers": glpi_customers,
        "glpi_error": glpi_error,
        "comms_configured": comms_configured(),
        "crm_configured": crm_configured(),
        "technician": current_technician(),
        "page_config": {
            "glpiCustomers": glpi_customers or [],
            "deviceCatalog": device_catalog,
            "importWorkOrderUrl": url_for("glpi_import.import_work_order"),
            "createSiteUrl": url_for("glpi_import.create_glpi_site"),
            "homeUrl": url_for("home.index"),
            "crmConfigured": crm_configured(),
            "templatesUrl": url_for("glpi_import.templates_collection"),
            "suggestionsUrl": url_for("glpi_import.connectivity_suggestions"),
        },
    }
    context.update(extra)
    return context
