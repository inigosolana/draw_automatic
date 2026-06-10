# Ausarta Draw.io

Generador de diagramas `.drawio` para instalaciones de telecomunicaciones.

## Que hace esta version

- Lee JSON o texto natural
- Lee la libreria `mxlibrary` de Ausarta
- Busca iconos por nombre y alias
- Genera un `.drawio` editable con:
  - cabecera de cliente
  - `INET -> ONT -> Router -> Switch -> Equipos`
  - bloque de resumen
  - conexiones con `source` y `target`
- Soporta plantillas:
  - `oficina_simple`
  - `con_switch`
  - `rack`
  - `multisede`

## Estructura

```text
ausarta_drawio/
├── app.py
├── generator/
│   ├── aliases.py
│   ├── cli.py
│   ├── drawio_writer.py
│   ├── layout_engine.py
│   ├── library_loader.py
│   └── parser.py
├── examples/
│   └── cliente_demo.json
├── tests/
│   └── test_basic.py
└── README.md
```

## Uso

```bash
python app.py --input examples/cliente_demo.json --library ..\libreria_Ausarta_JUN_2026.xml --output salida.drawio
python app.py --input examples/cliente_demo.txt --library ..\libreria_Ausarta_JUN_2026.xml --output salida_texto.drawio
python app.py --input examples\cliente_multisede.json --library ..\libreria_Ausarta_JUN_2026.xml --output salida_multi.drawio --template multisede
```

Desde esta carpeta:

```bash
cd ausarta_drawio
python app.py --input examples/cliente_demo.json --library ..\libreria_Ausarta_JUN_2026.xml --output salida.drawio
```

## Notas

- La libreria real mezcla imagenes `data:` y URLs.
- Los ejemplos reales usan tanto XML directo como diagramas comprimidos.
- Esta primera version genera XML directo para simplificar la compatibilidad.
- Si no encuentra un icono, crea un bloque generico y muestra warning.

## Siguientes mejoras naturales

- mejorar posicion exacta de etiquetas de puertos
- ampliar deteccion de equipos desde texto natural
- clonar aun mas estilos de ejemplos comprimidos
