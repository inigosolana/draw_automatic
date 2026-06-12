from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote
import xml.etree.ElementTree as ET

from .library_loader import LibraryIndex
from .layout_engine import EdgeSpec, NodeSpec


GENERIC_DEVICE_STYLE = (
    "rounded=1;whiteSpace=wrap;html=1;strokeColor=#6c8ebf;"
    "fillColor=#dae8fc;fontSize=12;"
)
TEXT_STYLE = "text;html=1;resizable=0;autosize=1;align=center;verticalAlign=middle;points=[];fillColor=none;strokeColor=none;rounded=0;"
HEADER_STYLE = "text;html=1;resizable=0;autosize=1;align=right;verticalAlign=middle;points=[];fillColor=none;strokeColor=none;rounded=0;"
EDGE_STYLE = (
    "edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;"
    "html=1;strokeWidth=2;endArrow=none;endFill=0;"
)
TABLE_STYLE = "text;html=1;strokeColor=#c0c0c0;fillColor=#ffffff;overflow=fill;rounded=0;strokeWidth=3;"
CLOUD_STYLE = "ellipse;shape=cloud;whiteSpace=wrap;html=1;dashed=1;dashPattern=1 1;labelBorderColor=#FF0080;strokeColor=#82b366;fillColor=#d5e8d4;"


@dataclass
class BuildResult:
    xml: str
    warnings: list[str]


class IdFactory:
    def __init__(self) -> None:
        self.value = 2

    def next(self) -> str:
        current = f"id-{self.value}"
        self.value += 1
        return current


def _geom(parent: ET.Element, x: int, y: int, width: int, height: int) -> None:
    ET.SubElement(parent, "mxGeometry", {"x": str(x), "y": str(y), "width": str(width), "height": str(height), "as": "geometry"})


def _text_cell(root: ET.Element, cell_id: str, value: str, style: str, x: int, y: int, width: int, height: int) -> None:
    cell = ET.SubElement(root, "mxCell", {"id": cell_id, "value": value, "style": style, "parent": "1", "vertex": "1"})
    _geom(cell, x, y, width, height)


def _drawio_image_uri(value: str) -> str:
    return quote(value, safe=":/,=+")


def build_drawio(nodes: list[NodeSpec], edges: list[EdgeSpec], library: LibraryIndex, warnings: list[str] | None = None) -> BuildResult:
    warnings = list(warnings or [])
    ids = IdFactory()
    node_ids: dict[str, str] = {}
    page_height = max(827, max((node.y + node.height for node in nodes), default=0) + 120)

    mxfile = ET.Element(
        "mxfile",
        {
            "host": "app.diagrams.net",
            "modified": "2026-06-10T00:00:00.000Z",
            "agent": "OpenAI Codex",
            "version": "24.7.17",
            "type": "device",
        },
    )
    diagram = ET.SubElement(mxfile, "diagram", {"id": "ausarta-diagram", "name": "Pagina-1"})
    model = ET.SubElement(
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
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

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
            cell = ET.SubElement(root, "mxCell", {"id": cell_id, "value": "", "style": CLOUD_STYLE, "parent": "1", "vertex": "1"})
            _geom(cell, node.x, node.y, node.width, node.height)
            label_id = ids.next()
            _text_cell(root, label_id, f"<font><b>{node.label}</b></font>", TEXT_STYLE, node.x + 25, node.y + 25, 70, 25)
            continue

        item = library.find(node.model or "")
        if item:
            style = (
                "shape=image;verticalLabelPosition=bottom;verticalAlign=top;"
                f"imageAspect=0;image={_drawio_image_uri(item.data)}"
            )
        else:
            style = GENERIC_DEVICE_STYLE
            warnings.append(f"No se ha encontrado icono para: {node.model}")
        cell = ET.SubElement(root, "mxCell", {"id": cell_id, "value": "", "style": style, "parent": "1", "vertex": "1"})
        _geom(cell, node.x, node.y, node.width, node.height)

        label_id = ids.next()
        label_style = TEXT_STYLE
        if node.meta and node.meta.get("propiedad"):
            color = "#008000" if node.meta["propiedad"] == "propio" else "#d00000"
            label_style += f"fontColor={color};fontStyle=1;"
        _text_cell(
            root,
            label_id,
            node.label,
            label_style,
            node.x - 10,
            node.y + node.height + 10,
            node.width + 20,
            40,
        )

    for edge_spec in edges:
        edge_id = ids.next()
        style = EDGE_STYLE.replace("rounded=1", "rounded=0" if edge_spec.label and edge_spec.label.startswith("ETH1") else "rounded=1")
        style += (
            f"exitX={edge_spec.exit_x};exitY={edge_spec.exit_y};exitDx=0;exitDy=0;exitPerimeter=0;"
            f"entryX={edge_spec.entry_x};entryY={edge_spec.entry_y};entryDx=0;entryDy=0;"
        )
        edge = ET.SubElement(
            root,
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
        geometry = ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})
        if edge_spec.label:
            ET.SubElement(geometry, "mxPoint", {"x": "0", "y": "-14", "as": "offset"})

    xml = ET.tostring(mxfile, encoding="unicode")
    return BuildResult(xml=xml, warnings=warnings)
