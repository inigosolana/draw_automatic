"""Compare GLPI province entities with the app catalog."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from generator.glpi_client import GlpiClient, build_customer_catalog

ROOT = Path(__file__).resolve().parents[1]
CACHE_DB = ROOT / "data" / "catalog.sqlite3"


def glpi_provinces(entities: list[dict]) -> list[str]:
    by_parent: dict[int, list[dict]] = {}
    for entity in entities:
        parent_id = entity.get("entities_id")
        if isinstance(parent_id, int):
            by_parent.setdefault(parent_id, []).append(entity)

    roots = [
        entity
        for entity in entities
        if entity.get("entities_id") in (None, 0) and int(entity.get("level", 0) or 0) <= 1
    ]
    root_ids = {entity["id"] for entity in roots if isinstance(entity.get("id"), int)}
    return sorted(
        entity.get("name", "")
        for entity in entities
        if entity.get("entities_id") in root_ids
    )


def app_provinces_from_entities(entities: list[dict]) -> list[str]:
    return [item["nombre"] for item in build_customer_catalog(entities)]


def cached_app_provinces() -> list[str]:
    if not CACHE_DB.exists():
        return []
    with sqlite3.connect(CACHE_DB) as connection:
        row = connection.execute(
            "SELECT payload FROM catalog_cache WHERE cache_key = ? ORDER BY updated_at DESC LIMIT 1",
            ("glpi_customer_catalog",),
        ).fetchone()
    if not row:
        return []
    catalog = json.loads(row[0])
    return [item.get("nombre", "") for item in catalog]


def main() -> None:
    client = GlpiClient.from_environment()
    if client is None:
        cached = cached_app_provinces()
        print("GLPI no configurado en este entorno (.env / variables de entorno).")
        if cached:
            print("\nProvincias en la ultima cache de la app:")
            for name in cached:
                print(f"- {name}")
        else:
            print("Tampoco hay cache local de catalogo.")
        print(
            "\nPara comparar en vivo, ejecuta con GLPI_URL, GLPI_APP_TOKEN y GLPI_USER_TOKEN definidos."
        )
        return

    entities = client.list_entities()
    glpi_list = glpi_provinces(entities)
    app_list = app_provinces_from_entities(entities)

    glpi_set = set(glpi_list)
    app_set = set(app_list)
    only_glpi = sorted(glpi_set - app_set)
    only_app = sorted(app_set - glpi_set)

    print(f"GLPI: {len(glpi_list)} provincias")
    for name in glpi_list:
        print(f"- {name}")

    print(f"\nApp: {len(app_list)} provincias")
    for name in app_list:
        print(f"- {name}")

    if only_glpi:
        print(f"\nSolo en GLPI ({len(only_glpi)}):")
        for name in only_glpi:
            print(f"- {name}")
    if only_app:
        print(f"\nSolo en app ({len(only_app)}):")
        for name in only_app:
            print(f"- {name}")
    if not only_glpi and not only_app and glpi_list == app_list:
        print("\nCoinciden: la app muestra las mismas provincias que GLPI con clientes.")


if __name__ == "__main__":
    main()
