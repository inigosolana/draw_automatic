import io
import unittest
from unittest.mock import patch

from web.services import upload_service


class FakeUpload:
    """Imita un werkzeug FileStorage para los tests."""

    def __init__(self, filename: str, data: bytes) -> None:
        self.filename = filename
        self._stream = io.BytesIO(data)

    def read(self) -> bytes:
        return self._stream.read()


class FakeCatalogStore:
    def __init__(self) -> None:
        self.cleared: list[str] = []

    def clear(self, key: str) -> None:
        self.cleared.append(key)


class FakeSitesStore:
    def __init__(self) -> None:
        self.saved: list[tuple] = []

    def set(self, entity_id, address, who) -> None:
        self.saved.append((entity_id, address, who))


class FakeStores:
    def __init__(self) -> None:
        self.catalog = FakeCatalogStore()
        self.sites = FakeSitesStore()


class FakeClient:
    def __init__(self, existing=None) -> None:
        self._existing = existing or []
        self.updated_addresses: list[tuple] = []

    def list_network_diagrams(self, entity_id):
        return list(self._existing)

    def update_entity_address(self, entity_id, address):
        self.updated_addresses.append((entity_id, address))


MXFILE = "<mxfile><diagram>x</diagram></mxfile>"


class PublishUploadedFilesTests(unittest.TestCase):
    def _publish_ok(self, *args, **kwargs):
        return 4242, "https://glpi.test/diagram/4242"

    def test_valid_drawio_is_published(self) -> None:
        client = FakeClient()
        stores = FakeStores()
        files = [FakeUpload("cliente_sede.drawio", MXFILE.encode("utf-8"))]
        with patch.object(upload_service, "publish_diagram", self._publish_ok), patch.object(
            upload_service, "learn_from_drawio", return_value=[]
        ):
            results, errors = upload_service.publish_uploaded_files(
                client,
                stores,
                files,
                entity_id=7,
                client_name="Cliente",
                site_name="Sede",
                technician={"name": "Ana", "username": "ana"},
                technician_name="ana",
                client_ip="127.0.0.1",
            )
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], 4242)
        self.assertEqual(results[0]["technician"], "Ana")

    def test_invalid_extension_is_rejected(self) -> None:
        client = FakeClient()
        stores = FakeStores()
        files = [FakeUpload("malicioso.exe", b"nope")]
        with patch.object(upload_service, "publish_diagram", self._publish_ok), patch.object(
            upload_service, "learn_from_drawio", return_value=[]
        ):
            results, errors = upload_service.publish_uploaded_files(
                client,
                stores,
                files,
                entity_id=7,
                client_name="Cliente",
                site_name="Sede",
                technician={"name": "Ana"},
                technician_name="ana",
                client_ip="127.0.0.1",
            )
        self.assertEqual(results, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("extension no valida", errors[0])

    def test_non_mxfile_xml_is_rejected(self) -> None:
        client = FakeClient()
        stores = FakeStores()
        files = [FakeUpload("raro.xml", b"<otracosa/>")]
        with patch.object(upload_service, "publish_diagram", self._publish_ok), patch.object(
            upload_service, "learn_from_drawio", return_value=[]
        ):
            results, errors = upload_service.publish_uploaded_files(
                client,
                stores,
                files,
                entity_id=7,
                client_name="Cliente",
                site_name="Sede",
                technician={"name": "Ana"},
                technician_name="ana",
                client_ip="127.0.0.1",
            )
        self.assertEqual(results, [])
        self.assertEqual(len(errors), 1)

    def test_blank_file_is_skipped(self) -> None:
        client = FakeClient()
        stores = FakeStores()
        files = [FakeUpload("", b"")]
        with patch.object(upload_service, "publish_diagram", self._publish_ok), patch.object(
            upload_service, "learn_from_drawio", return_value=[]
        ):
            results, errors = upload_service.publish_uploaded_files(
                client,
                stores,
                files,
                entity_id=7,
                client_name="Cliente",
                site_name="Sede",
                technician={"name": "Ana"},
                technician_name="ana",
                client_ip="127.0.0.1",
            )
        self.assertEqual(results, [])
        self.assertEqual(errors, [])


class SyncEntityAddressTests(unittest.TestCase):
    def test_updates_glpi_when_address_differs(self) -> None:
        client = FakeClient()
        stores = FakeStores()
        catalog = [
            {
                "provincia": "Bizkaia",
                "clientes": [
                    {
                        "id": 1,
                        "nombre": "Cliente",
                        "sedes": [{"id": 7, "direccion": "Calle Vieja, 1"}],
                    }
                ],
            }
        ]
        warnings = upload_service.sync_entity_address(
            client,
            stores,
            entity_id=7,
            address="Calle Nueva, 5",
            glpi_customers=catalog,
            technician_label="ana",
        )
        self.assertEqual(warnings, [])
        self.assertEqual(stores.sites.saved, [(7, "Calle Nueva, 5", "ana")])
        self.assertEqual(client.updated_addresses, [(7, "Calle Nueva, 5")])
        self.assertIn("glpi_customer_catalog", stores.catalog.cleared)

    def test_no_glpi_update_when_equivalent(self) -> None:
        client = FakeClient()
        stores = FakeStores()
        catalog = [
            {
                "provincia": "Bizkaia",
                "clientes": [
                    {
                        "id": 1,
                        "nombre": "Cliente",
                        "sedes": [{"id": 7, "direccion": "Calle Nueva, 5"}],
                    }
                ],
            }
        ]
        warnings = upload_service.sync_entity_address(
            client,
            stores,
            entity_id=7,
            address="Calle Nueva, 5",
            glpi_customers=catalog,
            technician_label="ana",
        )
        self.assertEqual(warnings, [])
        self.assertEqual(client.updated_addresses, [])


if __name__ == "__main__":
    unittest.main()
