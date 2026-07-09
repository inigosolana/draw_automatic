"""Helper compartido para publicar un diagrama en GLPI y registrar la actividad.

Centraliza el patrón duplicado en confirm_glpi y upload_draw:
create_network_diagram(...) + activity.add(...).
"""

from __future__ import annotations

import logging

from generator.diagram_metadata import build_diagram_description

logger = logging.getLogger(__name__)


def publish_diagram(
    client,
    stores,
    *,
    entity_id: int,
    diagram_name: str,
    client_name: str,
    site_name: str,
    technician: dict,
    source: str,
    graph_xml: str,
    filename: str = "",
) -> tuple[int, str]:
    """Crea el diagrama en GLPI, registra la actividad y devuelve (id, url)."""
    diagram_id = client.create_network_diagram(
        entity_id=entity_id,
        name=diagram_name,
        description=build_diagram_description(
            client_name=client_name,
            site_name=site_name,
            technician=technician,
            source=source,
            filename=filename,
        ),
        graph_xml=graph_xml,
    )
    stores.activity.add(
        diagram_id=diagram_id,
        entity_id=entity_id,
        diagram_name=diagram_name,
        client_name=client_name,
        site_name=site_name,
        technician=technician,
        source=source,
    )
    # La sede pasa a estar cubierta: invalida la cobertura cacheada del admin
    # (igual que hace el borrado), si no seguiría apareciendo como "sin diagrama".
    try:
        stores.catalog.clear("admin_coverage")
    except Exception:  # noqa: BLE001 - invalidar caché nunca debe romper la publicación
        logger.warning(
            "No se pudo invalidar la caché 'admin_coverage' tras publicar el diagrama %s",
            diagram_id,
            exc_info=True,
        )
    return diagram_id, client.diagram_url(diagram_id)
