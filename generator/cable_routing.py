"""Geometría de enrutado de cables/aristas del diagrama.

Funciones puras de geometría extraídas de layout_engine. Operan sobre NodeSpec
por atributos (duck typing), por lo que este módulo NO importa de layout_engine
y evita un import circular: es layout_engine quien importa de aquí.
"""

from __future__ import annotations

SWITCH_ANCHOR_KEYS = frozenset({"switch", "switch_datos"})
CABLE_CLEARANCE_ABOVE_DEVICE = 40
CABLE_GAP_BELOW_ANCHOR = 40
BUS_LANE_SPACING = 24
ROUTER_SWITCH_LANE_BASE = 18


def _anchor_exit_x(anchor, target) -> float:
    target_center = target.x + target.width / 2
    ratio = (target_center - anchor.x) / anchor.width
    return max(0.06, min(0.94, ratio))


def _anchor_exit_point(anchor, exit_x: float) -> tuple[int, int]:
    return int(anchor.x + exit_x * anchor.width), int(anchor.y + anchor.height)


def _target_entry_point(target) -> tuple[int, int]:
    return int(target.x + target.width / 2), int(target.y)


def _bus_waypoints(anchor, target, *, exit_x: float, bus_y: int) -> tuple[tuple[int, int], ...]:
    exit_x_abs, _ = _anchor_exit_point(anchor, exit_x)
    target_center, _ = _target_entry_point(target)
    if abs(exit_x_abs - target_center) <= 6:
        return ((target_center, bus_y),)
    return ((exit_x_abs, bus_y), (target_center, bus_y))


def _cable_label_offset(
    label: str,
    *,
    anchor_key: str,
    lane_index: int = 0,
    anchor=None,
    target=None,
) -> tuple[int, int]:
    if not label:
        return 0, -14
    if anchor_key in SWITCH_ANCHOR_KEYS and label.startswith("ETH") and not label.endswith("-LAN"):
        return lane_index * 10, -36 - lane_index * 4
    if label.endswith("-LAN") and anchor_key == "router":
        offset_x = 10
        if anchor is not None and target is not None:
            offset_x += int((target.x + target.width / 2) - (anchor.x + anchor.width / 2)) // 4
        return offset_x, -32 - lane_index * 4
    offset_x = 10 if label.endswith("-LAN") and anchor_key == "router" else 0
    offset_y = -30 if label.endswith("-LAN") and anchor_key == "router" else -24
    return offset_x, offset_y - lane_index * 2


def _device_bus_y(anchor, target, row_top_y: int | None = None, *, lane_index: int = 0) -> int:
    if row_top_y is not None:
        return row_top_y - CABLE_CLEARANCE_ABOVE_DEVICE - lane_index * BUS_LANE_SPACING
    midpoint = (anchor.y + anchor.height + target.y) // 2
    base = max(anchor.y + anchor.height + CABLE_GAP_BELOW_ANCHOR, midpoint)
    return base - lane_index * BUS_LANE_SPACING


def _router_switch_waypoints(
    router, switch, *, exit_x: float = 0.5, lane_index: int = 0
) -> tuple[tuple[int, int], ...] | None:
    # El cable debe caer EN VERTICAL desde el punto por donde sale del router
    # (exit_x) y solo entonces girar hacia el switch. Antes caía desde el centro
    # del router aunque saliera por una esquina (exit_x 0.06/0.94), lo que hacía
    # que la línea fuese primero hacia el centro y luego de vuelta: un zigzag.
    exit_abs = int(router.x + exit_x * router.width)
    switch_center = int(switch.x + switch.width / 2)
    joint_y = router.y + router.height + ROUTER_SWITCH_LANE_BASE + lane_index * BUS_LANE_SPACING
    if abs(exit_abs - switch_center) <= 8:
        return ((switch_center, joint_y),)
    return ((exit_abs, joint_y), (switch_center, joint_y))
