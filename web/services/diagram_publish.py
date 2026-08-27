"""Helper compartido para publicar un diagrama en GLPI y registrar la actividad.

Centraliza el patrón duplicado en confirm_glpi y upload_draw:
create_network_diagram(...) + activity.add(...).
"""

from __future__ import annotations

import logging

from generator.diagram_metadata import (
    build_diagram_description,
    fit_diagram_name,
    suffixed_diagram_name,
)
from generator.glpi_client import GlpiError

logger = logging.getLogger(__name__)

# GLPI rechaza el alta con estos dos motivos cuando el problema es SOLO el
# nombre: la columna `name` es varchar(45) con indice UNIQUE global. En ambos
# casos el nombre se reescribe y se reintenta, en vez de perder la subida.
_RENAMEABLE_ERRORS = ("duplicate entry", "data too long")
_MAX_RENAME_ATTEMPTS = 4


def _create_with_rename(client, *, entity_id, name, description, graph_xml) -> tuple[int, str]:
    """Crea el graph reescribiendo el nombre si GLPI lo rechaza por el nombre.

    Devuelve (id, nombre efectivo): el nombre puede no ser el pedido, y quien
    llama necesita el real para registrar la actividad y mostrarlo.
    """
    name = fit_diagram_name(name)
    tried: set[str] = set()
    last_error: GlpiError | None = None
    for attempt in range(_MAX_RENAME_ATTEMPTS):
        try:
            diagram_id = client.create_network_diagram(
                entity_id=entity_id,
                name=name,
                description=description,
                graph_xml=graph_xml,
            )
            return int(diagram_id), name
        except GlpiError as exc:
            message = str(exc).lower()
            if not any(marker in message for marker in _RENAMEABLE_ERRORS):
                raise
            last_error = exc
            tried.add(name.lower())
            name = suffixed_diagram_name(name, tried)
            logger.warning(
                "GLPI ha rechazado el nombre del diagrama (intento %s): %s. "
                "Se reintenta como %r",
                attempt + 1,
                exc,
                name,
            )
    raise GlpiError(
        "GLPI sigue rechazando el nombre del diagrama tras varios reintentos: "
        f"{last_error}"
    )


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
) -> tuple[int, str, str]:
    """Crea el diagrama en GLPI, registra la actividad y devuelve (id, url, nombre).

    El nombre devuelto es el que ha quedado REALMENTE en GLPI: si el pedido no
    cabia en 45 caracteres o ya estaba cogido, se reescribe automaticamente.
    """
    diagram_id, diagram_name = _create_with_rename(
        client,
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
    return diagram_id, client.diagram_url(diagram_id), diagram_name
