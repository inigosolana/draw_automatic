#!/usr/bin/env python3
"""Export sedes without a GLPI diagram to Excel."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from generator.catalog_cache import CatalogCache
from generator.glpi_client import GlpiClient, GlpiError, build_customer_catalog
from generator.site_directory import SiteDirectory, apply_saved_addresses
from web.services.export import MISSING_SITES_EXPORT_FILENAME, missing_sites_to_xlsx
from web.services.stats import build_missing_sites_rows, covered_entity_ids_from_diagrams


def load_catalog() -> tuple[list[dict], str]:
    catalog_cache = CatalogCache(
        os.environ.get("DRAWIO_CATALOG_DB", ROOT / "data" / "catalog.sqlite3"),
        ttl_seconds=int(os.environ.get("DRAWIO_CATALOG_TTL", "300")),
    )
    site_directory = SiteDirectory(
        os.environ.get("DRAWIO_SITE_DB", ROOT / "data" / "sites.sqlite3")
    )
    cached = catalog_cache.get("glpi_customer_catalog")
    if cached is not None:
        return apply_saved_addresses(cached, site_directory.all()), ""

    client = GlpiClient.from_environment()
    if not client:
        return [], "GLPI no esta configurado."
    try:
        catalog = build_customer_catalog(client.list_entities())
        catalog_cache.set("glpi_customer_catalog", catalog)
        return apply_saved_addresses(catalog, site_directory.all()), ""
    except GlpiError as exc:
        return [], str(exc)


def main() -> int:
    output = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else ROOT / MISSING_SITES_EXPORT_FILENAME
    )

    catalog, catalog_error = load_catalog()
    if not catalog:
        print(f"No se pudo cargar el catalogo GLPI: {catalog_error}", file=sys.stderr)
        return 1

    client = GlpiClient.from_environment()
    if not client:
        print("GLPI no esta configurado (revisa GLPI_URL, GLPI_APP_TOKEN, GLPI_USER_TOKEN).", file=sys.stderr)
        return 1

    try:
        covered = covered_entity_ids_from_diagrams(client.list_network_diagrams())
    except GlpiError as exc:
        print(f"Error al consultar diagramas GLPI: {exc}", file=sys.stderr)
        return 1

    rows = build_missing_sites_rows(catalog, covered)
    output.write_bytes(missing_sites_to_xlsx(rows))
    print(f"Exportadas {len(rows)} sedes sin diagrama -> {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
