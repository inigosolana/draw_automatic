# Ausarta Draw.io

Generador de diagramas `.drawio` para instalaciones de telecomunicaciones.

## Que hace esta version

- Lee JSON o texto natural.
- Lee una libreria `mxlibrary`.
- Busca iconos por nombre y alias.
- Genera un `.drawio` editable con cabecera, topologia, resumen y conexiones.
- Soporte inicial para plantillas `rack` y `multisede`.
- Incluye una interfaz web local para probar el generador desde el navegador.

## Uso por consola

La CLI actual sigue funcionando:

```bash
python app.py --input examples/cliente_demo.json --library libreria_Ausarta_JUN_2026.xml --output salida.drawio
python app.py --input examples/cliente_demo.txt --library libreria_Ausarta_JUN_2026.xml --output salida_texto.drawio
python app.py --input examples\cliente_multisede.json --library libreria_Ausarta_JUN_2026.xml --output salida_multi.drawio --template multisede
```

## Interfaz web local

```bash
pip install -r requirements.txt
python web_app.py
```

Abrir:

```text
http://127.0.0.1:8000
```

Para publicarlo en red o en un servidor:

```bash
set DRAWIO_HOST=0.0.0.0
set DRAWIO_PORT=8000
set GLPI_URL=https://glpi.example/apirest.php
set GLPI_WEB_URL=https://glpi.example
set GLPI_APP_TOKEN=tu_app_token
set GLPI_USER_TOKEN=tu_user_token
python web_app.py
```

La web permite:

- introducir cliente, CIF, sede y direccion;
- indicar internet, ONT, router e IP;
- pegar equipos en texto natural;
- pegar un bloque completo de texto natural;
- indicar la ruta de la libreria `.xml`;
- descargar automaticamente el `.drawio`;
- ver una previsualizacion textual con plantilla inferida, total de equipos y warnings.
- seleccionar provincia, cliente y sede desde GLPI;
- revisar el `.drawio` antes de confirmar su publicacion en GLPI;
- subir diagramas antiguos desde la pestana `Subir draw antiguo`;
- consultar por sede los diagramas que ya existen en GLPI;
- iniciar sesion con las mismas credenciales de GLPI sin guardar la contrasena;
- registrar el tecnico que publica cada diagrama;
- previsualizar el diagrama y avisar de duplicados antes de publicarlo;
- guardar por sede la direccion exacta corregida por el tecnico cuando GLPI solo aporta ciudad y codigo postal;
- aprender iconos etiquetados de draws antiguos sin reemplazar la libreria oficial.

Las credenciales GLPI solo se leen desde variables de entorno. No deben incluirse en el repositorio.

## Produccion con Portainer

El repositorio incluye `Dockerfile`, `docker-compose.yml`, `.env.example` y una guia
completa en `PORTAINER.md`. La aplicacion se ejecuta con Gunicorn, conserva las
descargas pendientes en un volumen y expone `/health` para monitorizacion.

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

Los tests usan una fixture minima en `tests/fixtures/test_library.xml`.

```bash
python -m unittest
```

## Notas

- Si no encuentra un icono, genera un bloque generico y muestra warning.
- Si la cantidad de un equipo es mayor que el numero de extensiones detectadas, genera un warning informativo.
- La altura de pagina se ajusta automaticamente segun el numero de filas de equipos.
