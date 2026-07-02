import unittest

from generator.layout_engine import (
    NodeSpec,
    _bus_waypoints,
    _device_bus_y,
    _router_switch_waypoints,
)


class EdgeRoutingTests(unittest.TestCase):
    def test_router_switch_uses_joint_when_not_aligned(self) -> None:
        router = NodeSpec("router", "device", "", 470, 120, 150, 150)
        switch = NodeSpec("switch", "device", "", 500, 360, 150, 150)
        waypoints = _router_switch_waypoints(router, switch)
        self.assertIsNotNone(waypoints)
        self.assertEqual(len(waypoints), 2)

    def test_router_switch_drops_straight_from_exit_no_center_jog(self) -> None:
        # Regresión: el cable debe caer en vertical desde el punto de salida
        # (exit_x), no desde el centro del router. Si el primer waypoint usara el
        # centro, la línea iría al centro y volvería (zigzag).
        router = NodeSpec("router", "device", "", 470, 120, 150, 150)
        # switch a la izquierda del router; se sale por la esquina izquierda.
        switch = NodeSpec("switch", "device", "", 231, 360, 150, 150)
        exit_x = 0.06
        waypoints = _router_switch_waypoints(router, switch, exit_x=exit_x)
        self.assertEqual(len(waypoints), 2)
        exit_abs = int(router.x + exit_x * router.width)
        switch_center = int(switch.x + switch.width / 2)
        # Primer punto: justo debajo del punto de salida (no el centro del router).
        self.assertEqual(waypoints[0][0], exit_abs)
        self.assertNotEqual(waypoints[0][0], int(router.x + router.width / 2))
        # Segundo punto: alineado con el centro del switch, a la misma altura.
        self.assertEqual(waypoints[1][0], switch_center)
        self.assertEqual(waypoints[0][1], waypoints[1][1])

    def test_device_bus_routes_below_anchor_and_above_target(self) -> None:
        anchor = NodeSpec("switch", "device", "", 470, 360, 150, 150)
        target = NodeSpec("team_1", "device", "", 240, 615, 150, 150)
        bus_y = _device_bus_y(anchor, target, row_top_y=615, lane_index=0)
        self.assertLess(bus_y, 615)
        self.assertGreater(bus_y, anchor.y + anchor.height)
        waypoints = _bus_waypoints(anchor, target, exit_x=0.5, bus_y=bus_y)
        self.assertEqual(len(waypoints), 2)
        self.assertEqual(waypoints[-1][1], bus_y)


if __name__ == "__main__":
    unittest.main()
