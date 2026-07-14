"""Tests de caracterización (golden master) de build_layout.

Congelan la salida exacta de build_layout para escenarios representativos.
Su propósito es servir de red de seguridad al refactorizar/partir
layout_engine: si la geometría o las etiquetas cambian, el hash cambia y el
test falla. Si un cambio en el dibujado es INTENCIONADO, hay que regenerar el
hash esperado (a propósito), no editarlo a la ligera.
"""

import hashlib
import json
import unittest
from pathlib import Path

from generator.layout_engine import build_layout
from generator.parser import load_input

ROOT = Path(__file__).resolve().parents[1]

CON_SWITCH = {
    "cliente": "Demo",
    "sede": "Central",
    "direccion": "Bilbao",
    "template": "con_switch",
    "internet": {"tipo": "SOLO FIBRA", "velocidad": "600 MB"},
    "ont": {"modelo": "ONT ZTE"},
    "router": {"modelo": "MikroTik hAP ac2"},
    "equipos": [
        {"tipo": "switch", "modelo": "switch TP-LINK-5_PORTS", "cantidad": 1},
        {"tipo": "switch", "modelo": "switch TP-LINK-5_PORTS", "cantidad": 1},
        {"tipo": "wifi", "modelo": "Grandstream AP", "cantidad": 1},
    ],
}


def _canonical(data: dict) -> tuple[int, int, str]:
    nodes, edges = build_layout(data)
    node_repr = [
        [n.key, n.kind, n.x, n.y, n.width, n.height, n.label, n.model, n.icon_model]
        for n in nodes
    ]
    edge_repr = [
        [
            e.source,
            e.target,
            e.label,
            e.exit_x,
            e.exit_y,
            e.entry_x,
            e.entry_y,
            list(e.waypoints) if e.waypoints else None,
            e.label_offset_x,
            e.label_offset_y,
        ]
        for e in edges
    ]
    blob = json.dumps({"nodes": node_repr, "edges": edge_repr}, default=str, ensure_ascii=False)
    return len(nodes), len(edges), hashlib.sha256(blob.encode()).hexdigest()


class LayoutGoldenTests(unittest.TestCase):
    def test_con_switch_layout_is_stable(self) -> None:
        self.assertEqual(
            _canonical(CON_SWITCH),
            # Actualizado al arreglar el zigzag de los cables router→switch en
            # doble switch: ahora caen en vertical desde el punto de salida.
            (9, 5, "b595313f52e414f11fb4dc257bdbca8820892bc71574a8dc8250d83349292b26"),
        )

    def test_office_example_layout_is_stable(self) -> None:
        self.assertEqual(
            _canonical(load_input(ROOT / "examples" / "cliente_demo.json")),
            # Actualizado al corregir el solapamiento de la etiqueta del cable
            # router->dispositivo vertical (ETHn-LAN) con la etiqueta de IP del
            # router: el offset pasa de (10,-30) a (28,25) para bajarla y
            # desplazarla lateralmente y no pisar la IP.
            (13, 9, "3c1bfa8c5997732659e50927607800a9e87f7e0338c0f04a084b0e1581c38742"),
        )

    def test_multisite_example_layout_is_stable(self) -> None:
        self.assertEqual(
            _canonical(load_input(ROOT / "examples" / "cliente_multisede.json")),
            (7, 3, "3007d5a69983936405c60b7bab6bc40715a1fafb35d88798c1c2d1b99cefda54"),
        )


if __name__ == "__main__":
    unittest.main()
