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
