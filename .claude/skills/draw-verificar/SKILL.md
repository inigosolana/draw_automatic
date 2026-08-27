---
name: draw-verificar
description: Ejecuta la batería de verificación de draw_automatic (pytest, pyflakes, ESLint 9 y los arneses jsdom que corren el frontend real sin login). Úsala SIEMPRE antes de dar por terminado un cambio en este proyecto, antes de commitear o desplegar, cuando el usuario diga "comprueba que funciona", "pásale los tests", "verifica", y también cuando haya que añadir cobertura a un arreglo o cuando falle un golden hash del layout. Incluye los gotchas que rompen la ejecución: `python` no existe (hay que usar `.venv/bin/python`) y hay un import "sin usar" que NO se debe borrar.
---

# Verificar un cambio en draw_automatic

La regla que más tiempo ahorra en este proyecto: **verificar justo después de cada cambio,
no al final**. Y al informar, distinguir con claridad lo que se ha comprobado de lo que se
supone. Un "debería funcionar" sin ejecutar nada no vale.

## Los comandos

```bash
cd /home/ubuntu/draw_automatic
.venv/bin/python -m pytest -q                  # suite completa (~360 tests, ~22 s)
.venv/bin/python -m pyflakes generator/ web/   # nombres no definidos en producción
.venv/bin/python -m pytest tests/test_frontend_eslint.py tests/test_frontend_creation_form.py -q
```

`python` y `python3 -m pytest` **no funcionan**: el intérprete del sistema no tiene pytest.
Usar siempre `.venv/bin/python`. Los tests de frontend se saltan solos si faltan Node o
jsdom (`npm install` en `tests/frontend/`), así que un "1 skipped" ahí significa "no se ha
comprobado", no "está bien".

## El import que parece sobrar y no sobra

pyflakes avisa siempre de esto:

```
generator/comms_client.py:12:1: '.work_order_json.normalize_work_order_payload' imported but unused
```

Es un **re-export** que usan `tests/test_offer_import.py` y `tests/test_crm_import.py`.
Borrarlo rompe la suite. Es el único aviso esperado: cualquier otro sí hay que atenderlo.
Antes de limpiar cualquier import "sin usar" en este repo, comprobar con grep que no sea un
re-export.

## Los arneses jsdom

En `tests/frontend/` hay arneses que **renderizan el HTML real** de la página y ejecutan
los JS de verdad en jsdom, sin necesidad de login. Es la única forma de verificar el
frontend de este proyecto, y caza cosas que la lectura del código no ve — por ejemplo que
un `<select>` pierde su valor cuando se reconstruyen sus `<option>`.

- `creation_form_harness.js` — formulario de creación (`/draw`)
- `upload_form_harness.js` — subida a GLPI
- `zabbix_form_harness.js` — Zabbix (**no tocar** esa integración)

Cada arnés imprime `RESULTADO: N OK, M FALLOS` y devuelve código de salida distinto de 0 si
algo falla. Los `check(...)` solo se imprimen cuando fallan, así que para ver el recuento
hay que mirar la línea final. Al añadir cobertura, se añade un bloque `check(...)` al
arnés correspondiente.

## Escribir la prueba de un arreglo

Que un test pase después de arreglar algo no demuestra que pruebe el arreglo. Merece la
pena confirmar que **falla sin él**: revertir el cambio un momento, ver el test en rojo, y
restaurarlo. Es rápido y evita tests decorativos.

```bash
cp generator/fichero.py /tmp/f.bak
# revertir el arreglo (sed/edición mínima)
.venv/bin/python -m pytest tests/test_x.py -q   # debe FALLAR
cp /tmp/f.bak generator/fichero.py
.venv/bin/python -m pytest tests/test_x.py -q   # debe PASAR
```

## Golden hashes del layout

`tests/test_layout_golden.py` congela el resultado del motor de dibujado (excluyendo
`node.meta`). Si cambia, el motor mueve nodos o cables. Un golden roto es una señal, no un
estorbo: si el cambio no pretendía tocar diagramas existentes, hay un efecto colateral que
merece entenderse antes de actualizar el hash.

## Análisis estático del frontend

ESLint 9 con configuración plana (`eslint.config.mjs`) y `no-undef` como error. Existe
porque un "variable no definida" en un IIFE colgó la subida a GLPI en producción. Recordar
el gotcha del proyecto: **cada IIFE tiene su propio scope**, así que un segundo bloque que
necesite la configuración de la página debe releerla de su
`<script type="application/json">`, no referenciar variables del primero.

## Antes de decir "está terminado"

Comprobar de verdad: suite en verde, pyflakes sin avisos nuevos, arneses jsdom con 0
fallos, y —si el cambio afecta al runtime— el comportamiento reproducido contra el
contenedor desplegado. Si algo se ha quedado sin verificar, decirlo explícitamente en vez
de dejarlo implícito.
