---
name: draw-glpi
description: Consulta GLPI/Archimap en solo lectura desde el contenedor de draw_automatic, y explica los límites reales del plugin (la columna `name` de los diagramas es varchar(45) con índice UNIQUE GLOBAL). Úsala SIEMPRE que haya que comprobar si un diagrama está subido, buscar diagramas de un cliente o sede, contar la cobertura, diagnosticar un error de subida a GLPI (ERROR_GLPI_ADD, Duplicate entry, Data too long), o responder a "¿está en GLPI?" / "no me deja subirlo" / "me da error al publicar". También cuando haya que decidir cómo nombrar un diagrama.
---

# Consultar GLPI (Archimap) desde draw_automatic

Las credenciales GLPI viven **solo** en variables de entorno del contenedor, así que las
consultas se hacen desde dentro. El patrón que funciona (no toca disco, usa el código ya
desplegado):

```bash
docker exec -i -e PYTHONPATH=/app ausarta-drawio python - <<'EOF'
from generator.glpi_client import GlpiClient
client = GlpiClient.from_environment()   # None si faltan credenciales
diagramas = client.list_network_diagrams()
print("total:", len(diagramas))
for d in diagramas:
    if "GOIZTIRI" in str(d.get("name") or "").upper():
        print(d.get("id"), d.get("entities_id"), repr(d.get("name")))
EOF
```

Sin `PYTHONPATH=/app` falla con `ModuleNotFoundError`. `GlpiClient()` a pelo pide
`url`/`app_token`/`user_token`: usar siempre `from_environment()`.

Escribir el script con la tool Write y pasarlo por stdin (`python - < fichero.py`) evita
el infierno de quoting de los heredocs con comillas y regex por ssh.

## Reglas de uso (no negociables)

Leer GLPI es libre. Lo demás, no:

- **No crear clientes ni sedes.** Usar los que ya existen en el catálogo.
- **No publicar/subir diagramas sin un "sí" explícito del usuario en cada caso.** Generar
  y previsualizar está bien.
- **No meter credenciales en el repo** ni en scripts. Solo variables de entorno.

Si hace falta escribir en GLPI para diagnosticar algo (por ejemplo probar un límite de
columna), pedirlo antes, hacerlo con un registro de prueba identificable (`ZZTEST_...`) y
borrarlo en un `finally`. Después, confirmar que no quedan restos comparando el total de
diagramas antes y después.

## Límites reales del plugin Archimap (verificados contra el servidor)

| campo | límite | comprobado |
|---|---|---|
| `name` | **45** caracteres | 45 acepta, 46 → `Data too long for column 'name'` |
| `shortdescription` | **100** caracteres | 100 acepta, 101 → `Data too long` |

Y lo más importante: `name` tiene **índice UNIQUE GLOBAL** (`name_UNIQUE`), no por sede ni
por cliente. Dos sedes del mismo cliente **no pueden compartir nombre**. De ahí vienen los
dos errores clásicos:

- `ERROR_GLPI_ADD Duplicate entry '<nombre>' for key 'glpi_plugin_archimap_graphs.name_UNIQUE'`
- `ERROR_GLPI_ADD Data too long for column 'name' at row 1`

Ambos llegan al usuario como "no me deja subirlo". Antes de teorizar, mirar los logs:

```bash
docker logs --since 2h ausarta-drawio 2>&1 | grep -iE "upload|Duplicate|too long|Traceback" | tail -30
```

Los avisos `[SECURITY] Upload failed: ...` traen el motivo exacto de GLPI y el nombre del
fichero, que es el 90 % del diagnóstico.

## Nombres de diagrama

Nunca truncar un nombre por el carácter 45: se pierde el `Sede N` del final y todas las
sedes de un cliente de nombre largo colisionan. Usar los helpers de
`generator/diagram_metadata.py`, que comprimen conservando sede, vía y portal:

- `fit_diagram_name(nombre, max_len=GLPI_NAME_MAX)` — comprime por partes.
- `unique_diagram_name(nombre, diagramas_existentes)` — comprime y esquiva duplicados.
- `suffixed_diagram_name(base, tomados)` — añade sufijo de fecha-hora.

Para comprobar la unicidad hay que comparar contra **todos** los diagramas, no solo los de
la sede, porque el UNIQUE es global. No cuesta una llamada extra:
`list_network_diagrams(entity_id)` ya se los trae todos y filtra en Python.

La publicación (`web/services/diagram_publish.py`) reescribe el nombre y reintenta sola
ante `Duplicate entry` o `Data too long`, igual que el guardado de nueva versión
(`GlpiClient.save_network_diagram_version`). Si se añade otro camino que cree diagramas,
darle el mismo tratamiento o volverá el fallo.

## Gotcha de rendimiento

`list_network_diagrams()` usa la **search API** pidiendo solo campos ligeros, a propósito:
`getAllItems` devuelve el blob `graph` (~1 MB por diagrama) y revienta la memoria PHP de
GLPI con un HTTP 500. Si aparece un 500 al listar o subir, sospechar de que alguien haya
vuelto a pedir el campo `graph`.
