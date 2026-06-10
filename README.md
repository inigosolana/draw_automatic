# Ausarta Draw.io

Generador de diagramas `.drawio` para instalaciones de telecomunicaciones.

## Que hace esta version

- Lee JSON o texto natural.
- Lee una libreria `mxlibrary`.
- Busca iconos por nombre y alias.
- Genera un `.drawio` editable con cabecera, topologia, resumen y conexiones.
- Soporte inicial para plantillas `rack` y `multisede`.

## Uso

```bash
python app.py --input examples/cliente_demo.json --library ..\libreria_Ausarta_JUN_2026.xml --output salida.drawio
python app.py --input examples/cliente_demo.txt --library ..\libreria_Ausarta_JUN_2026.xml --output salida_texto.drawio
python app.py --input examples\cliente_multisede.json --library ..\libreria_Ausarta_JUN_2026.xml --output salida_multi.drawio --template multisede
```

## Formato JSON soportado

```json
{
  "cliente": "PESCADOS GINES E HIJOS",
  "cif": "B20684866",
  "sede": "ESNABIDE 18",
  "direccion": "Esnabide 18, Pasaia, Gipuzkoa",
  "internet": {
    "tipo": "FTTH",
    "velocidad": "1Gb"
  },
  "ont": {
    "modelo": "ONT ZTE"
  },
  "router": {
    "modelo": "MikroTik hAP ac2",
    "ip": "192.168.0.1/24"
  },
  "equipos": [
    {
      "tipo": "telefono",
      "modelo": "Fanvil V62",
      "cantidad": 2,
      "extensiones": ["2001", "2002"]
    },
    {
      "tipo": "switch",
      "modelo": "TP-Link 16P",
      "cantidad": 1
    }
  ],
  "sedes": [
    {
      "sede": "Bilbao",
      "direccion": "Bilbao Centro"
    }
  ]
}
```

Campos obligatorios:

- `cliente`
- `sede`
- `direccion`

Campos opcionales:

- `cif`
- `internet.tipo`
- `internet.velocidad`
- `ont.modelo`
- `router.modelo`
- `router.ip`
- `equipos[].tipo`
- `equipos[].modelo`
- `equipos[].cantidad`
- `equipos[].extensiones`
- `sedes[]`

## Formato de texto natural soportado

```text
Cliente: Pescados Gines e Hijos
CIF: B20684866
Sede: Esnabide 18
Direccion: Esnabide 18, Pasaia, Gipuzkoa

Internet: FTTH 1Gb
ONT: ONT ZTE
Router: MikroTik hAP ac2 - 192.168.0.1/24

Equipos:
* 2 Fanvil V62, extensiones 2001 y 2002
* 1 Yealink T31P, extension 2003
* 1 switch TP-Link 16P
* 3 PC
```

Reglas actuales del parser:

- Detecta `Cliente`, `CIF`, `Sede`, `Direccion`, `Internet`, `ONT`, `Router` y `Equipos`.
- En `Internet` intenta separar tipo y velocidad.
- En `Router` intenta detectar IP en formato `x.x.x.x/yy`.
- En `Equipos` detecta cantidad, modelo y extensiones.
- Si no se indica plantilla, intenta inferir `oficina_simple`, `con_switch`, `rack` o `multisede`.

## Tests

Los tests ya no dependen de la libreria real de Ausarta y usan una fixture minima en `tests/fixtures/test_library.xml`.

```bash
python -m unittest
```

## Notas

- Si no encuentra un icono, genera un bloque generico y muestra warning.
- Si la cantidad de un equipo es mayor que el numero de extensiones detectadas, genera un warning informativo.
- La altura de pagina se ajusta automaticamente segun el numero de filas de equipos.
