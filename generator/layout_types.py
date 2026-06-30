"""Tipos compartidos del motor de layout.

Se extraen a su propio módulo para que tanto `layout_engine` como
`placement_engine` (y `drawio_writer`) puedan importarlos sin ciclos.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NodeSpec:
    key: str
    kind: str
    label: str
    x: int
    y: int
    width: int
    height: int
    model: str | None = None
    meta: dict | None = None
    icon_model: str | None = None


@dataclass
class EdgeSpec:
    source: str
    target: str
    label: str | None = None
    exit_x: float = 1.0
    exit_y: float = 0.5
    entry_x: float = 0.5
    entry_y: float = 0.5
    waypoints: tuple[tuple[int, int], ...] | None = None
    label_offset_x: int = 0
    label_offset_y: int = -14
