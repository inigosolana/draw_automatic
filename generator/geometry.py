from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

SUMMARY_X = 900
DEVICE_WIDTH = 150
DEVICE_HEIGHT = 150
SLOT_SPACING = 285
MIN_SLOT_SPACING = 265
MIN_LEFT_MARGIN = 60
CANVAS_RIGHT = SUMMARY_X - 20
# Borde derecho de la página para las filas de dispositivos que quedan POR DEBAJO
# de la tabla resumen (esquina superior derecha, y<=270). Esas filas pueden
# repartirse a lo ancho de toda la página, no solo hasta la tabla. Coincide con el
# borde derecho de la tabla resumen para un dibujo equilibrado.
PAGE_RIGHT = 1280
SUMMARY_BOTTOM = 300
DEVICE_ROW_GAP = 175
# Separación horizontal mínima entre teléfonos repartidos a lo ancho. Subida a
# 235 para que los terminales queden MÁS separados (menos por fila, más aire
# entre ellos) y se lean con claridad.
TELEPHONY_ZONE_MIN_SPACING = 235


class _AnchorNode(Protocol):
    x: int
    width: int


@dataclass
class _RowLayoutHint:
    zone_left: int | None = None
    zone_right: int | None = None
    constrain_to_anchor: bool = False


def canvas_bounds() -> tuple[int, int]:
    return MIN_LEFT_MARGIN, CANVAS_RIGHT


def dual_switch_zone_limits(switch_key: str) -> tuple[int, int]:
    canvas_left, canvas_right = canvas_bounds()
    mid = canvas_left + (canvas_right - canvas_left) // 2
    if switch_key == "switch":
        return canvas_left, mid - 16
    return mid + 16, canvas_right


def compact_row_spacing(slots_in_row: int, available: int) -> int | None:
    if slots_in_row <= 1:
        return 0
    spacing = (available - DEVICE_WIDTH) // (slots_in_row - 1)
    if spacing < TELEPHONY_ZONE_MIN_SPACING:
        return None
    return min(SLOT_SPACING, spacing)


def max_slots_for_zone(
    total_slots: int,
    left: int,
    right: int,
    *,
    force_horizontal: bool,
) -> tuple[int, int]:
    available = max(DEVICE_WIDTH, right - left)
    if total_slots <= 0:
        return 1, 0
    if force_horizontal:
        spacing = compact_row_spacing(total_slots, available)
        if spacing is not None:
            return total_slots, spacing
    for slots_in_row in range(total_slots, 0, -1):
        spacing = compact_row_spacing(slots_in_row, available)
        if spacing is not None:
            return slots_in_row, spacing
    return 1, 0


def row_layout(total_slots: int, max_right: int = CANVAS_RIGHT) -> tuple[int, int]:
    available = max_right - MIN_LEFT_MARGIN
    if total_slots <= 0:
        return MIN_LEFT_MARGIN, MIN_SLOT_SPACING
    if total_slots == 1:
        return MIN_LEFT_MARGIN + (available - DEVICE_WIDTH) // 2, MIN_SLOT_SPACING
    spacing = max(MIN_SLOT_SPACING, min(SLOT_SPACING, (available - DEVICE_WIDTH) // (total_slots - 1)))
    row_width = (total_slots - 1) * spacing + DEVICE_WIDTH
    start_x = MIN_LEFT_MARGIN + (available - row_width) // 2
    return start_x, spacing


def anchor_row_limits(anchor_node: _AnchorNode) -> tuple[int, int]:
    left = max(MIN_LEFT_MARGIN, anchor_node.x - 24)
    right = min(CANVAS_RIGHT, anchor_node.x + anchor_node.width + 24)
    return left, right


def device_row_layout(
    total_slots: int,
    anchor: _AnchorNode,
    layout: _RowLayoutHint | None = None,
    max_right: int = CANVAS_RIGHT,
) -> tuple[int, int]:
    zone_left: int | None = None
    zone_right: int | None = None
    constrain_to_anchor = False
    if layout is not None:
        zone_left = layout.zone_left
        zone_right = layout.zone_right
        constrain_to_anchor = layout.constrain_to_anchor
    if zone_left is not None and zone_right is not None:
        left, right = zone_left, zone_right
        available = max(DEVICE_WIDTH, right - left)
        if total_slots <= 1:
            return left + (available - DEVICE_WIDTH) // 2, 0
        spacing = compact_row_spacing(total_slots, available) or MIN_SLOT_SPACING
        row_width = (total_slots - 1) * spacing + DEVICE_WIDTH
        start_x = left + max(0, (available - row_width) // 2)
        return start_x, spacing
    if constrain_to_anchor:
        left, right = anchor_row_limits(anchor)
        available = max(DEVICE_WIDTH, right - left)
        if total_slots <= 1:
            return left + (available - DEVICE_WIDTH) // 2, 0
        spacing = max(
            MIN_SLOT_SPACING,
            min(SLOT_SPACING, (available - DEVICE_WIDTH) // (total_slots - 1)),
        )
        row_width = (total_slots - 1) * spacing + DEVICE_WIDTH
        start_x = left + max(0, (available - row_width) // 2)
        return start_x, spacing
    _, spacing = row_layout(total_slots, max_right)
    row_width = (total_slots - 1) * spacing + DEVICE_WIDTH
    centered_start = anchor.x + (anchor.width - row_width) // 2
    start_x = max(MIN_LEFT_MARGIN, min(centered_start, max_right - row_width))
    return start_x, spacing


def max_slots_per_row(total_slots: int, *, max_right: int = CANVAS_RIGHT) -> tuple[int, int]:
    for slots_in_row in range(total_slots, 0, -1):
        _, spacing = row_layout(slots_in_row, max_right)
        row_width = (slots_in_row - 1) * spacing + DEVICE_WIDTH
        if row_width <= max_right - MIN_LEFT_MARGIN:
            return slots_in_row, spacing
    return 1, 0
