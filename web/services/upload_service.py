"""Lógica de subida de diagramas a GLPI, extraída de la vista upload_draw.

Mantiene la vista delgada y permite envolver todas las llamadas GLPI de la
subida en una sola sesión (batch_session).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from defusedxml import ElementTree as DefusedET
from defusedxml.common import DefusedXmlException

from app_context import security_logger
from generator.address_formatter import addresses_equivalent
from generator.diagram_metadata import format_activity_timestamp, unique_diagram_name
from generator.glpi_client import GlpiError
from generator.knowledge_base import learn_from_drawio
from generator.pdf_drawio import PdfDrawioError, extract_drawio_from_pdf
from generator.safe_errors import public_error_message
from web.services.diagram_publish import publish_diagram
from web.services.stats import find_catalog_sede, glpi_street

_VALID_EXTENSIONS = (".drawio", ".xml", ".pdf")


def sync_entity_address(
    client,
    stores,
    *,
    entity_id: int,
    address: str,
    glpi_customers: list,
    technician_label: str,
) -> list[str]:
    """Guarda la calle corregida localmente y, si difiere de GLPI, la actualiza.

    Devuelve una lista de avisos (no fatales).
    """
    warnings: list[str] = []
    stores.sites.set(entity_id, address, technician_label)
    catalog_sede = find_catalog_sede(glpi_customers, entity_id)
    glpi_original = glpi_street(catalog_sede) if catalog_sede else ""
    if glpi_original and not addresses_equivalent(address, glpi_original):
        try:
            client.update_entity_address(entity_id, address)
            stores.catalog.clear("glpi_customer_catalog")
            stores.catalog.clear("admin_coverage")
        except GlpiError as exc:
            warnings.append(
                "La calle se guardo localmente, pero no se pudo actualizar en GLPI: "
                + public_error_message(str(exc), context="actualizacion de direccion GLPI")
            )
    return warnings


def publish_uploaded_files(
    client,
    stores,
    files,
    *,
    entity_id: int,
    client_name: str,
    site_name: str,
    technician: dict,
    technician_name: str,
    client_ip: str,
) -> tuple[list[dict], list[str]]:
    """Procesa cada archivo (.drawio/.xml/.pdf) y lo publica en GLPI.

    Devuelve (resultados, errores).
    """
    results: list[dict] = []
    errors: list[str] = []
    existing_diagrams = client.list_network_diagrams(entity_id)
    for uploaded_file in files:
        if not uploaded_file or not uploaded_file.filename:
            continue
        if not uploaded_file.filename.lower().endswith(_VALID_EXTENSIONS):
            errors.append(
                f"{uploaded_file.filename}: extension no valida (.drawio, .xml o .pdf)."
            )
            security_logger.warning(
                f"Upload attempt with invalid file type: {uploaded_file.filename}, "
                f"user={technician_name}, IP={client_ip}"
            )
            continue
        try:
            raw = uploaded_file.read()
            if uploaded_file.filename.lower().endswith(".pdf"):
                xml = extract_drawio_from_pdf(raw)
            else:
                xml = raw.decode("utf-8-sig")
            root = DefusedET.fromstring(xml)
            if root.tag != "mxfile":
                raise ValueError("El documento no contiene un mxfile de Draw.io.")
            diagram_name = unique_diagram_name(
                Path(uploaded_file.filename).stem, existing_diagrams
            )
            diagram_id, url = publish_diagram(
                client,
                stores,
                entity_id=entity_id,
                diagram_name=diagram_name,
                client_name=client_name,
                site_name=site_name,
                technician=technician,
                source="Draw subido",
                graph_xml=xml,
                filename=uploaded_file.filename,
            )
            learned_models = learn_from_drawio(xml, uploaded_file.filename)
            results.append(
                {
                    "id": diagram_id,
                    "url": url,
                    "filename": uploaded_file.filename,
                    "name": diagram_name,
                    "cliente": client_name,
                    "sede": site_name,
                    "technician": technician.get("name") or technician.get("username") or "",
                    "created_label": format_activity_timestamp(datetime.now().timestamp()),
                    "learned_models": learned_models,
                }
            )
            existing_diagrams.append({"id": diagram_id, "name": diagram_name})
            security_logger.info(
                f"File uploaded successfully: diagram_id={diagram_id}, "
                f"file={uploaded_file.filename}, user={technician_name}, IP={client_ip}"
            )
        except (
            UnicodeDecodeError,
            DefusedET.ParseError,
            DefusedXmlException,
            PdfDrawioError,
            ValueError,
            GlpiError,
        ) as exc:
            errors.append(
                f"{uploaded_file.filename}: {public_error_message(str(exc), context='subida del diagrama')}"
            )
            security_logger.warning(
                f"Upload failed: {exc}, file={uploaded_file.filename}, "
                f"user={technician_name}, IP={client_ip}"
            )
    return results, errors
