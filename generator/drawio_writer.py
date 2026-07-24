from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote
from uuid import uuid4

from lxml import etree

from .library_loader import LibraryIndex
from .layout_engine import EdgeSpec, NodeSpec, SWITCH_ANCHOR_KEYS


GENERIC_DEVICE_STYLE = (
    "rounded=1;whiteSpace=wrap;html=1;strokeColor=#6c8ebf;"
    "fillColor=#dae8fc;fontSize=12;"
)
TEXT_STYLE = "text;html=1;resizable=0;autosize=1;align=center;verticalAlign=middle;points=[];fillColor=none;strokeColor=none;rounded=0;"
HEADER_STYLE = "text;html=1;resizable=0;autosize=1;align=right;verticalAlign=middle;points=[];fillColor=none;strokeColor=none;rounded=0;"
EDGE_STYLE = (
    "edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;"
    "html=1;strokeWidth=2;strokeColor=#5b7c99;endArrow=none;endFill=0;"
)
TABLE_STYLE = "text;html=1;strokeColor=#c0c0c0;fillColor=#ffffff;overflow=fill;rounded=0;strokeWidth=3;"
CLOUD_STYLE = "ellipse;shape=cloud;whiteSpace=wrap;html=1;dashed=1;dashPattern=1 1;labelBorderColor=#FF0080;strokeColor=#82b366;fillColor=#d5e8d4;"


@dataclass
class BuildResult:
    xml: str
    warnings: list[str]


class IdFactory:
    def next(self) -> str:
        return f"id-{uuid4().hex[:12]}"


def _serialize_mxfile(mxfile: etree._Element) -> str:
    return etree.tostring(mxfile, encoding="unicode", pretty_print=False)


def _geom(parent: etree._Element, x: int, y: int, width: int, height: int) -> None:
    etree.SubElement(
        parent,
        "mxGeometry",
        {"x": str(x), "y": str(y), "width": str(width), "height": str(height), "as": "geometry"},
    )


def _text_cell(root: etree._Element, cell_id: str, value: str, style: str, x: int, y: int, width: int, height: int) -> None:
    cell = etree.SubElement(root, "mxCell", {"id": cell_id, "value": value, "style": style, "parent": "1", "vertex": "1"})
    _geom(cell, x, y, width, height)


# Firmas base64 de los formatos de imagen habituales en la librería (los
# primeros bytes de cada formato, ya codificados en base64).
_B64_IMAGE_SIGNATURES = (
    "/9j/",      # JPEG (FF D8 FF)
    "iVBOR",     # PNG  (89 50 4E 47)
    "R0lGOD",    # GIF  (47 49 46 38)
    "PHN2Zy",    # SVG  ("<svg")
    "PD94bWw",   # SVG  ("<?xml")
)


def _drawio_image_uri(value: str) -> str:
    # Muchos iconos de la librería vienen como 'data:image/xxx,<base64>' SIN el
    # marcador ';base64'. Sin él, draw.io interpreta el base64 como texto
    # URL-encoded y la imagen sale en negro/vacía (así se veían los switches).
    # Si el payload es claramente base64, insertamos ';base64' para que se vea.
    if value.startswith("data:"):
        head, sep, payload = value.partition(",")
        # Comprobamos ';base64' en la PARTE DEL TIPO (antes de la coma), no en un
        # prefijo fijo: así no se duplica el marcador aunque el tipo lleve params
        # largos (p. ej. 'data:image/svg+xml;charset=utf-16;base64,...').
        if sep and ";base64" not in head and any(
            payload.startswith(sig) for sig in _B64_IMAGE_SIGNATURES
        ):
            value = f"{head};base64,{payload}"
    # El ';' se codifica como %3B (draw.io lo decodifica): así los iconos que
    # arreglamos quedan EXACTAMENTE igual que los que ya venían con ';base64' y
    # se renderizan bien.
    return quote(value, safe=":/,=+")


def build_drawio(nodes: list[NodeSpec], edges: list[EdgeSpec], library: LibraryIndex, warnings: list[str] | None = None) -> BuildResult:
    warnings = list(warnings or [])
    ids = IdFactory()
    node_ids: dict[str, str] = {}
    page_height = max(827, max((node.y + node.height for node in nodes), default=0) + 120)

    mxfile = etree.Element(
        "mxfile",
        {
            "host": "app.diagrams.net",
            "modified": "2026-06-10T00:00:00.000Z",
            "agent": "OpenAI Codex",
            "version": "24.7.17",
            "type": "device",
        },
    )
    diagram = etree.SubElement(mxfile, "diagram", {"id": "ausarta-diagram", "name": "Pagina-1"})
    model = etree.SubElement(
        diagram,
        "mxGraphModel",
        {
            "dx": "1434",
            "dy": "758",
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": "1169",
            "pageHeight": str(page_height),
            "math": "0",
            "shadow": "0",
        },
    )
    root = etree.SubElement(model, "root")
    etree.SubElement(root, "mxCell", {"id": "0"})
    etree.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    deferred_edges: list[etree._Element] = []
    deferred_vertices: list[etree._Element] = []
    deferred_labels: list[etree._Element] = []

    for node in nodes:
        cell_id = ids.next()
        node_ids[node.key] = cell_id
        if node.kind == "header":
            _text_cell(root, cell_id, node.label, HEADER_STYLE, node.x, node.y, node.width, node.height)
            continue
        if node.kind in {"text", "plain_text"}:
            _text_cell(root, cell_id, node.label, TEXT_STYLE, node.x, node.y, node.width, node.height)
            continue
        if node.kind == "table":
            _text_cell(root, cell_id, node.label, TABLE_STYLE, node.x, node.y, node.width, node.height)
            continue
        if node.kind == "cloud":
            cell = etree.SubElement(root, "mxCell", {"id": cell_id, "value": "", "style": CLOUD_STYLE, "parent": "1", "vertex": "1"})
            _geom(cell, node.x, node.y, node.width, node.height)
            label_id = ids.next()
            _text_cell(root, label_id, f"<font><b>{node.label}</b></font>", TEXT_STYLE, node.x + 25, node.y + 25, 70, 25)
            continue
        if node.kind == "floor":
            # Contenedor de piso/planta: rectángulo de fondo semitransparente, un
            # color distinto por piso, con la etiqueta grande y en negrita arriba.
            # Se añade directo al root (no diferido) para quedar DETRÁS de los equipos.
            # Paleta de colores claros (fill, borde, texto) por piso:
            _FLOOR_PALETTE = [
                ("#dae8fc", "#6c8ebf", "#1a3c6b"),  # azul
                ("#d5e8d4", "#82b366", "#2d5a2d"),  # verde
                ("#fff2cc", "#d6b656", "#7a5c00"),  # amarillo
                ("#ffe6cc", "#d79b00", "#8a4b00"),  # naranja
                ("#e1d5e7", "#9673a6", "#5b3a6b"),  # morado
                ("#f8cecc", "#b85450", "#7a2320"),  # rojo
                ("#d0f0f0", "#3a9b9b", "#164f4f"),  # turquesa
                ("#f5f0d0", "#a39b56", "#5c5320"),  # oliva
            ]
            idx = int((node.meta or {}).get("color_idx", 0)) % len(_FLOOR_PALETTE)
            fill, stroke, font = _FLOOR_PALETTE[idx]
            style = (
                f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};"
                "dashed=1;verticalAlign=top;align=left;spacingLeft=12;spacingTop=8;"
                # fillOpacity solo hace transparente el RELLENO: el borde y el texto
                # (grande, en negrita) quedan nítidos y bien visibles.
                f"fontStyle=1;fontColor={font};fontSize=22;fillOpacity=35;strokeWidth=2;"
            )
            cell = etree.SubElement(root, "mxCell", {"id": cell_id, "value": node.label, "style": style, "parent": "1", "vertex": "1"})
            _geom(cell, node.x, node.y, node.width, node.height)
            continue

        if node.meta and node.meta.get("tipo") == "expansor":
            # Módulo de expansión: caja pequeña gris con la etiqueta dentro (no hay
            # icono propio en la librería). Se dibuja pegado a la derecha del
            # teléfono, con un "+" entre medias (añadido como nodo de texto aparte).
            style = (
                "rounded=1;whiteSpace=wrap;html=1;fillColor=#f0f0f0;strokeColor=#7f7f7f;"
                "verticalAlign=middle;align=center;fontSize=10;fontStyle=1;"
            )
            cell = etree.SubElement(root, "mxCell", {"id": cell_id, "value": node.label, "style": style, "parent": "1", "vertex": "1"})
            _geom(cell, node.x, node.y, node.width, node.height)
            continue

        is_switch = node.key in SWITCH_ANCHOR_KEYS or bool(node.meta and node.meta.get("tipo") == "switch")
        item = library.find(node.icon_model or node.model or "")
        if not item and node.icon_model and node.model and node.icon_model != node.model:
            item = library.find(node.model)
        if not item and is_switch:
            # Switch sin foto propia (p. ej. los PoE TL-SG1005P/1008P): usar el
            # icono genérico de switch en vez de dejar una caja vacía.
            item = library.find("Switch")
        if item:
            aspect = "1" if getattr(item, "aspect", "fixed") == "fixed" else "0"
            # Las fotos de switch son apaisadas; preservando el aspecto
            # (imageAspect=1) no se deforman al meterlas en la caja. El resto de
            # iconos (teléfonos, etc.) siguen rellenando la caja como antes.
            image_aspect = "1" if is_switch else "0"
            style = (
                "shape=image;verticalLabelPosition=bottom;verticalAlign=top;"
                f"aspect={aspect};imageAspect={image_aspect};image={_drawio_image_uri(item.data)}"
            )
        else:
            style = GENERIC_DEVICE_STYLE
            warnings.append(f"No se ha encontrado icono para: {node.model}")
        cell = etree.Element("mxCell", {"id": cell_id, "value": "", "style": style, "parent": "1", "vertex": "1"})
        _geom(cell, node.x, node.y, node.width, node.height)
        deferred_vertices.append(cell)

        label_id = ids.next()
        label_style = TEXT_STYLE
        if node.meta and node.meta.get("propiedad"):
            color = "#008000" if node.meta["propiedad"] == "propio" else "#d00000"
            label_style += f"fontColor={color};fontStyle=1;"
        label_lines = max(1, node.label.count("<br>") + 1)
        label_height = max(42, label_lines * 18 + 10)
        label_above = node.key in SWITCH_ANCHOR_KEYS or bool(node.meta and node.meta.get("label_above"))
        label_offset_y = -label_height - 10 if label_above else node.height + 16
        # La etiqueta cuelga del icono (parent = icono, geometría relativa a él)
        # para que al mover el icono en draw.io la etiqueta (nombre/SN/MAC) se
        # mueva con él en vez de quedarse quieta.
        label_cell = etree.Element("mxCell", {
            "id": label_id,
            "value": node.label,
            "style": label_style,
            "parent": cell_id,
            "vertex": "1",
        })
        _geom(label_cell, -12, label_offset_y, node.width + 24, label_height)
        deferred_labels.append(label_cell)

    for edge_spec in edges:
        edge_id = ids.next()
        style = EDGE_STYLE.replace(
            "rounded=1",
            "rounded=0" if edge_spec.label and edge_spec.label.startswith("ETH") else "rounded=1",
        )
        if edge_spec.label == "DECT":
            style += "dashed=1;dashPattern=8 8;strokeColor=#6c8ebf;"
        elif edge_spec.label and "ETH" in edge_spec.label:
            style += "verticalLabelPosition=top;verticalAlign=bottom;"
        style += (
            f"exitX={edge_spec.exit_x};exitY={edge_spec.exit_y};exitDx=0;exitDy=0;exitPerimeter=1;"
            f"entryX={edge_spec.entry_x};entryY={edge_spec.entry_y};entryDx=0;entryDy=0;entryPerimeter=1;"
        )
        edge = etree.Element(
            "mxCell",
            {
                "id": edge_id,
                "style": style,
                "parent": "1",
                "source": node_ids[edge_spec.source],
                "target": node_ids[edge_spec.target],
                "edge": "1",
                "value": edge_spec.label or "",
            },
        )
        geometry = etree.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})
        if edge_spec.waypoints:
            points = etree.SubElement(geometry, "Array", {"as": "points"})
            for waypoint_x, waypoint_y in edge_spec.waypoints:
                etree.SubElement(points, "mxPoint", {"x": str(waypoint_x), "y": str(waypoint_y)})
        if edge_spec.label:
            etree.SubElement(
                geometry,
                "mxPoint",
                {
                    "x": str(edge_spec.label_offset_x),
                    "y": str(edge_spec.label_offset_y),
                    "as": "offset",
                },
            )
        deferred_edges.append(edge)

    for cell in deferred_edges:
        root.append(cell)
    for cell in deferred_vertices:
        root.append(cell)
    for cell in deferred_labels:
        root.append(cell)

    xml = _serialize_mxfile(mxfile)
    return BuildResult(xml=xml, warnings=warnings)
