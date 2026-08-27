---
name: draw-auditar-ot
description: Audita una orden de trabajo (OT) del CRM en draw_automatic comparando el payload crudo con lo que produce el importador, para encontrar equipos mal clasificados o perdidos. Úsala SIEMPRE que el usuario dé un número de OT y diga que "da algún fallo", "revísala", "audítala", "sale mal el draw", "faltan teléfonos", "las bases están mal", o que un equipo aparece vacío o duplicado en el diagrama. También al investigar avisos del tipo "Producto de conectividad no mapeado".
---

# Auditar una orden de trabajo

El valor de esta auditoría está en **comparar dos cosas**: lo que el CRM manda y lo que la
app entiende. Casi todos los fallos viven en esa diferencia, y mirar solo el resultado
final lleva a conclusiones equivocadas.

## Paso 1 — El payload crudo del CRM

```bash
docker exec -i -e PYTHONPATH=/app ausarta-drawio python - <<'EOF'
import json
from generator.crm_client import CrmClient
raw = CrmClient.from_environment().fetch_work_order("9342")   # <- nº de OT
eq = raw["result"]["equipments"]
print("EQUIPOS EN LA OT:", len(eq))
for k, v in eq.items():
    print(f"  {k}: {v['productName']:<50} SN={v['S/N']:<18} MAC={v['MAC']:<13} ext={v['service_ext']}")
EOF
```

Contar los equipos a mano por categoría (ONT, router, backup, bases DECT, inalámbricos,
teléfonos). Ese recuento es la verdad contra la que se compara todo lo demás.

## Paso 2 — Lo que produce el importador

```bash
docker exec -i -e PYTHONPATH=/app ausarta-drawio python - <<'EOF'
from collections import Counter
from generator.work_order_import import import_work_order_by_id
d = import_work_order_by_id("9342")
d = d if isinstance(d, dict) else getattr(d, "__dict__", d)
t = d.get("terminals") or []
for k, v in d.items():
    if k != "terminals":
        print(f"{k}: {v}")
print("terminales:", len(t), "| por modelo:", dict(Counter(x.get("model") for x in t)))
print("por base:", dict(Counter(x.get("dect_base") for x in t)))
for x in t:
    print(f"  {x.get('model'):<8} ext={x.get('extension'):<6} sn={x.get('serial'):<18} base={x.get('dect_base')!r}")
EOF
```

## Qué mirar, y con qué criterio

**Campos de conectividad vacíos.** `router_modelo`, `ont_modelo` o `backup_modelo` en
blanco con un equipo de esa clase en el CRM es un fallo de detección, en
`generator/equipment_detection.py`. Ojo con el orden: `_detect_backup_model` gana a
`_detect_router_model`, y el importador quita el prefijo del fabricante
(`"MikroTik - X"` → `"X"`) **antes** de detectar, así que las reglas que dependen de la
palabra "mikrotik" no disparan por esa vía. Un modelo mal detectado es peor que uno vacío:
comprobar siempre qué devuelve la detección con el nombre tal cual llega y con el prefijo
puesto.

**`warnings`.** "Producto de conectividad no mapeado automáticamente" señala exactamente el
producto que nadie ha sabido clasificar.

**Bases DECT e inalámbricos.** Cada base física tiene su propio S/N y MAC. Con **varias
bases del mismo modelo**, cada unidad lleva su clave (`W70B-1`, `W70B-2`) y los
inalámbricos se reparten a partes iguales, porque el CRM **no dice** cuál cuelga de cuál.
Con una sola base no se numera nada. Si el reparto sale concentrado en una sola clave
habiendo dos bases, es el bug de agrupar por modelo en vez de por unidad.

**Extensiones repetidas o vacías.** Antes de declararlo fallo, comprobar el paso 1: es
muy habitual que el CRM mande la misma `service_ext` en todos los puestos VoIP. Eso es
dato de origen, no un error de la app.

## Paso 3 — El diagrama, si el fallo es visual

Que los datos importados sean correctos no garantiza que el dibujo lo sea. Para "cuelga de
la base equivocada" o "sale una caja vacía", hay que construir el layout:

```bash
docker exec -i -e PYTHONPATH=/app ausarta-drawio python - <<'EOF'
from generator.layout_engine import build_layout
from generator.parser import parse_equipment_line

equipos = []
for i, sn in enumerate(("B1", "B2")):
    e = parse_equipment_line("1 Yealink W70B"); e["serial_number"] = sn
    e["dect_base"] = f"W70B-{i+1}"; equipos.append(e)
for i in range(9):
    e = parse_equipment_line("1 Yealink W71H"); e["serial_number"] = f"a{i}"
    e["dect_base"] = "W70B-1" if i < 5 else "W70B-2"; equipos.append(e)

data = {"cliente": "X", "sede": "Sede 1", "direccion": "Calle 1",
        "equipos": equipos, "internet": {"tipo": "FIBRA + BACK UP", "proveedor": "AIRE"}}
nodes, edges = build_layout(data)
bases = [n for n in nodes if (n.meta or {}).get("dect_role") == "base"]
hs = {n.key for n in nodes if (n.meta or {}).get("dect_role") == "handset"}
print("bases:", [(b.key, b.model) for b in bases], "| handsets:", len(hs))
reparto = {}
for e in edges:
    if e.target in hs:
        reparto[e.source] = reparto.get(e.source, 0) + 1
print("handsets por base:", reparto)
EOF
```

Una base sin ningún inalámbrico colgando, o más nodos base que bases físicas, indica que
las claves de agrupación no emparejan (`_dect_registry_key` frente a
`physical_base_registry_key`, en `generator/dect_layout.py`).

## Paso 4 — El camino real del formulario

El usuario no llama al importador: rellena el formulario y pulsa Generar. Ese camino pasa
por `generator/web_adapter.py`, que empareja **por posición** cada línea de equipo con su
línea de detalle (`modelo | ext | serial | mac | ip | propiedad | dect_base | puerto | piso | expansor`).
Ahí ha habido fallos de desalineación que metían el número de serie en el equipo
equivocado. Si la sospecha es "los datos salen cambiados de sitio", reproducirlo con
`form_to_data(form)` y mirar equipo por equipo, en vez de fiarse del importador.

## Cómo informar

Separar lo que es fallo de la app de lo que es dato de origen del CRM, y decir de cada
hallazgo si está verificado o es sospecha. Cuando un fallo dependa de una decisión de
producto (por ejemplo cómo repartir inalámbricos cuando el CRM no lo dice), preguntar en
vez de elegir por el usuario. Y avisar de los fallos preexistentes que aparezcan de paso:
en esta auditoría suelen salir, y a menudo son más graves que el que motivó la revisión.
