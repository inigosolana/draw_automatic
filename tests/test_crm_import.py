import json
import unittest
from unittest.mock import patch

from generator.comms_client import CommsError, normalize_work_order_payload
from generator.crm_client import CrmClient
from generator.layout_engine import build_layout
from generator.work_order_json import import_result_from_json_payload


SAMPLE_CRM_PAYLOAD = {
    "work_order_id": "7885",
    "customer": {
        "name": "EMBALAJES ECHEBERRIA SOLUCIONES DE EMBALAJE S.L.U.",
        "tax_id": "B75560581",
    },
    "site": {
        "name": "Sede 1 - PRINCIPAL",
        "address": "Calle Portal De Zurbano, 19, Vitoria-Gasteiz 01013, Alava",
        "glpi_entity_id": 12345,
    },
    "connectivity": {
        "type": "FIBRA + BACK UP",
        "provider": "AIRE",
        "speed": "1 GB",
        "ont_model": "ONT ZTE",
        "router_model": "MikroTik hAP ac2",
        "backup_model": "WAP LTE",
    },
    "terminals": [
        {
            "model": "T-33",
            "extension": "3001",
            "serial_number": "SN001",
            "mac": "00:15:65:11:22:01",
        },
        {
            "model": "SIP-T33G",
            "extension": "3002",
            "serial_number": "SN002",
            "mac": "00:15:65:11:22:02",
        },
    ],
    "products": [
        {"name": "GPON ONT", "quantity": 1},
        {"name": "hAP ac2", "quantity": 1},
    ],
}


RESTAURACION_ALBENZAIRE_CRM_PAYLOAD = {
    "customer": {
        "document": "B19532548",
        "fullname": "RESTAURACION ALBENZAIRE SL",
    },
    "sede": {
        "name": "Sede 1 - PRINCIPAL",
        "address_id": 216792,
        "contact_id": 40319,
        "matriz": True,
        "address": "Calle Nueva, 5, Bajo. Fuensanta, Pinos Puente 18328, Granada",
        "contact": "CONCEPCION DIAZ FERNANDEZ - administracion@albenzaire.com - 629272188",
    },
    "equipments": {
        "16425": {
            "productName": "ZTE - GPON ONT",
            "S/N": "",
            "MAC": "",
            "service_name": "Fibra PRO Max Velocidad",
            "service_tlf": "",
            "service_ext": None,
        },
        "16426": {
            "productName": "MikroTik - hAP ac2 - RBD52G-5HacD2HnD-TC",
            "S/N": "HHJ0ACD6X20",
            "MAC": "",
            "service_name": "Fibra PRO Max Velocidad",
            "service_tlf": "",
            "service_ext": None,
        },
        "16427": {
            "productName": "MikroTik - wAPGR-5HacD2HnD&EC200A-EU wAP  ac LTE6 kit (Nuevo LTE6)",
            "S/N": "HJ30ABAWTJZ",
            "MAC": "",
            "service_name": "Fibra PRO Max Velocidad",
            "service_tlf": "",
            "service_ext": None,
        },
        "16428": {
            "productName": "Grandstream - Grandstream GWN7660 Punto de Acceso Wifi 6, 2×2:2 MU-MIM",
            "S/N": "34A01R0ACF",
            "MAC": "EC74D756B128",
            "service_name": "Antena techo WIFI 6",
            "service_tlf": "",
            "service_ext": "",
        },
        "16429": {
            "productName": "Yealink - Base DECT W70B",
            "S/N": "202017H052426904",
            "MAC": "44DBD2F4120A",
            "service_name": "Puestos VoIP",
            "service_tlf": "",
            "service_ext": "3001",
        },
        "16430": {
            "productName": "Yealink - W71H",
            "S/N": "202028H052403482",
            "MAC": "",
            "service_name": "Puestos VoIP",
            "service_tlf": "",
            "service_ext": "3001",
        },
        "16431": {
            "productName": "Yealink - SIP-T33G",
            "S/N": "201046G110011193",
            "MAC": "44DBD29AA96D",
            "service_name": "Puestos VoIP",
            "service_tlf": "",
            "service_ext": "3002",
        },
        "16432": {
            "productName": "Yealink - SIP-T33G",
            "S/N": "301046H090045964",
            "MAC": "C4FC223C342D",
            "service_name": "Puestos VoIP",
            "service_tlf": "",
            "service_ext": "3002",
        },
    },
}

RESTAURACION_ALBENZAIRE_CRM_API_RESPONSE = {
    "status": "OK",
    "result": RESTAURACION_ALBENZAIRE_CRM_PAYLOAD,
}


DECT_HANDSET_MODELS = frozenset({"W71H", "W72H", "W53H", "W73H"})


def _layout_data_from_import_result(result):
    equipos = [{"tipo": "switch", "modelo": "TP-Link 8P", "cantidad": 1}]
    for terminal in result.terminals:
        item = {
            "tipo": "terminal_dect" if terminal.get("model") in DECT_HANDSET_MODELS else "telefono",
            "modelo": terminal.get("model", ""),
            "cantidad": 1,
            "propiedad": terminal.get("ownership", "propio"),
        }
        if terminal.get("extension"):
            item["extension"] = terminal["extension"]
        if terminal.get("dect_base"):
            item["dect_base"] = terminal["dect_base"]
        equipos.append(item)
    return {
        "cliente": result.cliente,
        "sede": result.sede or "Sede Principal",
        "direccion": result.direccion,
        "template": "con_switch",
        "internet": {
            "tipo": result.internet_tipo or "SOLO FIBRA",
            "velocidad": result.internet_velocidad or "600 MB",
        },
        "ont": {"modelo": result.ont_modelo or "ONT ZTE"},
        "router": {"modelo": result.router_modelo or "MikroTik hAP ac2"},
        "equipos": equipos,
    }


class CrmImportTests(unittest.TestCase):
    def test_import_result_from_structured_crm_payload(self) -> None:
        result = import_result_from_json_payload(SAMPLE_CRM_PAYLOAD)

        self.assertEqual(result.work_order_id, "7885")
        self.assertEqual(result.cliente, "EMBALAJES ECHEBERRIA SOLUCIONES DE EMBALAJE S.L.U.")
        self.assertEqual(result.cif, "B75560581")
        self.assertEqual(result.internet_proveedor, "AIRE")
        self.assertEqual(result.internet_velocidad, "1 GB")
        self.assertEqual(result.internet_tipo, "FIBRA + BACK UP")
        self.assertEqual(result.router_modelo, "MikroTik hAP ac2")
        self.assertEqual(result.backup_modelo, "WAP LTE")
        self.assertEqual(result.glpi_entity_id, "12345")
        self.assertEqual(len(result.terminals), 2)
        self.assertEqual(result.terminals[0]["extension"], "3001")
        self.assertEqual(result.terminals[0]["serial"], "SN001")
        self.assertEqual(result.terminals[0]["mac"], "00:15:65:11:22:01")
        self.assertEqual(result.terminals[1]["model"], "T-33")

    def test_normalize_work_order_payload_keeps_structured_connectivity(self) -> None:
        normalized = normalize_work_order_payload(SAMPLE_CRM_PAYLOAD)
        self.assertEqual(normalized["connectivity_structured"]["provider"], "AIRE")
        self.assertEqual(normalized["glpi_entity_id"], "12345")
        self.assertEqual(len(normalized["terminals"]), 2)

    @patch("generator.crm_client.urlopen")
    def test_crm_client_fetches_by_work_order_id(self, urlopen_mock) -> None:
        response = urlopen_mock.return_value.__enter__.return_value
        response.read.return_value = json.dumps(SAMPLE_CRM_PAYLOAD).encode("utf-8")

        client = CrmClient(
            "https://crm.example.test",
            api_token="secret-token",
            work_order_path="/api/work-orders/{work_order_id}",
        )
        result = client.import_work_order("OT00007885")

        self.assertEqual(result.work_order_id, "7885")
        self.assertEqual(result.internet_proveedor, "AIRE")
        request = urlopen_mock.call_args.args[0]
        self.assertEqual(request.full_url, "https://crm.example.test/api/work-orders/7885")
        self.assertIn("Bearer secret-token", request.headers.get("Authorization", ""))

    def test_import_result_requires_products_or_terminals(self) -> None:
        with self.assertRaises(CommsError):
            import_result_from_json_payload({"customer": {"name": "Demo"}})

    def test_import_result_requires_cliente_cif_sede_direccion(self) -> None:
        payload = {
            "customer": {"document": "B19532548"},
            "sede": {"name": "Sede 1"},
            "equipments": {
                "1": {
                    "productName": "Yealink - SIP-T33G",
                    "S/N": "SN001",
                    "MAC": "44DBD29AA96D",
                    "service_ext": "3001",
                }
            },
        }
        with self.assertRaisesRegex(CommsError, "cliente \\(customer.fullname\\)"):
            import_result_from_json_payload(payload)
        with self.assertRaisesRegex(CommsError, "direccion \\(sede.address\\)"):
            import_result_from_json_payload(
                {
                    **payload,
                    "customer": {"document": "B19532548", "fullname": "Cliente Demo"},
                }
            )

    def test_import_result_requires_mac_on_crm_terminals(self) -> None:
        payload = {
            **SAMPLE_CRM_PAYLOAD,
            "terminals": [
                {
                    "model": "T-33",
                    "extension": "3001",
                    "serial_number": "SN001",
                }
            ],
        }
        with self.assertRaisesRegex(CommsError, "MAC"):
            import_result_from_json_payload(payload)

    def test_import_result_requires_serial_on_crm_terminals(self) -> None:
        payload = {
            **SAMPLE_CRM_PAYLOAD,
            "terminals": [
                {
                    "model": "T-33",
                    "extension": "3001",
                    "mac": "00:15:65:11:22:01",
                }
            ],
        }
        with self.assertRaisesRegex(CommsError, "serie"):
            import_result_from_json_payload(payload)

    def test_import_result_from_crm_equipments_payload(self) -> None:
        result = import_result_from_json_payload(RESTAURACION_ALBENZAIRE_CRM_PAYLOAD, work_order_id="9012")

        self.assertEqual(result.work_order_id, "9012")
        self.assertEqual(result.cliente, "RESTAURACION ALBENZAIRE SL")
        self.assertEqual(result.cif, "B19532548")
        self.assertEqual(result.sede, "Sede 1 - PRINCIPAL")
        self.assertEqual(
            result.direccion,
            "Calle Nueva, 5, Bajo",
        )
        self.assertEqual(result.internet_proveedor, "AIRE")
        self.assertEqual(result.internet_tipo, "FIBRA + BACK UP")
        self.assertEqual(result.internet_velocidad, "1 GB")
        self.assertEqual(result.ont_modelo, "ONT ZTE")
        self.assertEqual(result.router_modelo, "MikroTik hAP ac2")
        self.assertEqual(result.backup_modelo, "WAP LTE")
        self.assertEqual(len(result.terminals), 3)
        self.assertEqual(result.terminals[0]["model"], "W71H")
        self.assertEqual(result.terminals[0]["extension"], "3001")
        self.assertEqual(result.terminals[0]["dect_base"], "W70B")
        self.assertEqual(result.terminals[1]["model"], "T-33")
        self.assertEqual(result.terminals[1]["mac"], "44:DB:D2:9A:A9:6D")
        self.assertEqual(result.terminals[2]["serial"], "301046H090045964")
        self.assertTrue(any(device["tipo"] == "wifi" for device in result.devices_json))
        wifi_devices = [device for device in result.devices_json if device["tipo"] == "wifi"]
        self.assertEqual(len(wifi_devices), 1)
        self.assertEqual(wifi_devices[0]["modelo"], "Grandstream AP")

    def test_import_unwraps_status_result_envelope(self) -> None:
        result = import_result_from_json_payload(
            RESTAURACION_ALBENZAIRE_CRM_API_RESPONSE,
            work_order_id="9012",
        )
        self.assertEqual(result.cliente, "RESTAURACION ALBENZAIRE SL")
        self.assertEqual(result.sede, "Sede 1 - PRINCIPAL")
        self.assertEqual(len(result.terminals), 3)

    @patch("generator.crm_client.urlopen")
    def test_crm_client_unwraps_status_result_response(self, urlopen_mock) -> None:
        response = urlopen_mock.return_value.__enter__.return_value
        response.read.return_value = json.dumps(RESTAURACION_ALBENZAIRE_CRM_API_RESPONSE).encode("utf-8")

        client = CrmClient("https://crm.example.test", api_token="secret-token")
        result = client.import_work_order("9012")

        self.assertEqual(result.sede, "Sede 1 - PRINCIPAL")
        self.assertEqual(result.terminals[0]["dect_base"], "W70B")

    def test_sede_ignores_crm_metadata_fields(self) -> None:
        normalized = normalize_work_order_payload(RESTAURACION_ALBENZAIRE_CRM_PAYLOAD)
        self.assertEqual(normalized["sede"], "Sede 1 - PRINCIPAL")
        self.assertEqual(
            normalized["direccion"],
            "Calle Nueva, 5, Bajo",
        )
        self.assertNotIn("address_id", normalized)
        self.assertNotIn("contact", normalized)

    def test_single_dect_base_links_all_wireless_handsets(self) -> None:
        payload = {
            "customer": {"document": "B19532548", "fullname": "RESTAURACION ALBENZAIRE SL"},
            "sede": {"name": "Local Fuensanta - Bajo", "address": "Calle Nueva, 5"},
            "equipments": {
                "1": {
                    "productName": "Yealink - W71H",
                    "S/N": "202028H052403482",
                    "MAC": "",
                    "service_name": "Puestos VoIP",
                    "service_ext": "3001",
                },
                "2": {
                    "productName": "Yealink - W71H",
                    "S/N": "202028H052403483",
                    "MAC": "",
                    "service_name": "Puestos VoIP",
                    "service_ext": "3004",
                },
                "3": {
                    "productName": "Yealink - Base DECT W70B",
                    "S/N": "202017H052426904",
                    "MAC": "44DBD2F4120A",
                    "service_name": "Puestos VoIP",
                    "service_ext": "",
                },
            },
        }
        result = import_result_from_json_payload(payload)
        handsets = [terminal for terminal in result.terminals if terminal["model"] == "W71H"]
        self.assertEqual(len(handsets), 2)
        self.assertEqual({terminal["dect_base"] for terminal in handsets}, {"W70B"})

    def test_crm_import_dect_handsets_draw_dect_links_not_eth(self) -> None:
        result = import_result_from_json_payload(RESTAURACION_ALBENZAIRE_CRM_PAYLOAD, work_order_id="9012")
        nodes, edges = build_layout(_layout_data_from_import_result(result))
        handset_nodes = [node for node in nodes if node.model == "W71H"]
        self.assertEqual(len(handset_nodes), 1)
        handset_key = handset_nodes[0].key
        self.assertTrue(any(edge.target == handset_key and edge.label == "DECT" for edge in edges))
        self.assertFalse(
            any(
                edge.target == handset_key and edge.label and "ETH" in edge.label.upper()
                for edge in edges
            )
        )
        base_nodes = [node for node in nodes if node.meta and node.meta.get("dect_role") == "base"]
        self.assertEqual(len(base_nodes), 1)
        self.assertEqual(base_nodes[0].model, "W70B")
        base_key = base_nodes[0].key
        self.assertTrue(
            any(edge.source == base_key and edge.target == handset_key and edge.label == "DECT" for edge in edges)
        )


if __name__ == "__main__":
    unittest.main()
