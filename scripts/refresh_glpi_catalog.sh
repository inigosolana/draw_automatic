#!/bin/sh
# Refresco nocturno del catálogo de clientes/sedes de GLPI.
# Limpia la caché y la reconstruye desde GLPI para que por la mañana el catálogo
# esté al día y la primera carga sea instantánea. NO crea nada en GLPI: solo lee.
set -e
docker exec -i ausarta-drawio python - <<"PY"
from app_factory import create_app
from app_context import get_drawio_stores
from web.services.glpi_catalog import load_glpi_catalog
app = create_app()
with app.app_context():
    get_drawio_stores().catalog.clear("glpi_customer_catalog")
    cat, err = load_glpi_catalog()
    ncli = sum(len(p.get("clientes", [])) for p in cat)
    nsed = sum(len(c.get("sedes", [])) for p in cat for c in p.get("clientes", []))
    print("clientes=%d sedes=%d err=%r" % (ncli, nsed, err))
PY
