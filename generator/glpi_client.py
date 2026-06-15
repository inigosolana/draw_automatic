from __future__ import annotations

import json
import os
import re
from base64 import b64encode
from contextlib import contextmanager
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class GlpiError(RuntimeError):
    pass


class GlpiClient:
    def __init__(self, url: str, app_token: str, user_token: str, timeout: int = 15) -> None:
        self.url = url.rstrip("/")
        self.app_token = app_token
        self.user_token = user_token
        self.timeout = timeout

    @classmethod
    def from_environment(cls) -> GlpiClient | None:
        url = os.environ.get("GLPI_URL", "").strip()
        app_token = os.environ.get("GLPI_APP_TOKEN", "").strip()
        user_token = os.environ.get("GLPI_USER_TOKEN", "").strip()
        if not all((url, app_token, user_token)):
            return None
        return cls(url, app_token, user_token)

    def _request(
        self,
        path: str,
        headers: dict[str, str],
        method: str = "GET",
        payload: dict | None = None,
    ) -> object:
        request_headers = dict(headers)
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.url}/{path.lstrip('/')}",
            headers=request_headers,
            data=body,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GlpiError(f"GLPI ha rechazado la operacion ({exc.code}): {detail}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise GlpiError(f"No se ha podido consultar GLPI: {exc}") from exc

    def authenticate_user(self, username: str, password: str) -> dict:
        credentials = b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        auth_headers = {
            "App-Token": self.app_token,
            "Authorization": f"Basic {credentials}",
        }
        payload = self._request("initSession", auth_headers)
        session_token = payload.get("session_token") if isinstance(payload, dict) else None
        if not session_token:
            raise GlpiError("GLPI no ha aceptado las credenciales.")
        headers = {"App-Token": self.app_token, "Session-Token": session_token}
        try:
            full_session = self._request("getFullSession", headers)
            session_data = full_session.get("session", full_session) if isinstance(full_session, dict) else {}
            return {
                "id": session_data.get("glpiID"),
                "username": session_data.get("glpiname") or username,
                "name": session_data.get("glpifriendlyname") or session_data.get("glpirealname") or username,
            }
        finally:
            try:
                self._request("killSession", headers)
            except GlpiError:
                pass

    @contextmanager
    def session(self):
        auth_headers = {
            "App-Token": self.app_token,
            "Authorization": f"user_token {self.user_token}",
        }
        payload = self._request("initSession", auth_headers)
        session_token = payload.get("session_token") if isinstance(payload, dict) else None
        if not session_token:
            raise GlpiError("GLPI no ha devuelto un token de sesion.")
        headers = {"App-Token": self.app_token, "Session-Token": session_token}
        try:
            yield headers
        finally:
            try:
                self._request("killSession", headers)
            except GlpiError:
                pass

    def list_entities(self) -> list[dict]:
        with self.session() as headers:
            entities: list[dict] = []
            page_size = 1000
            start = 0
            while True:
                payload = self._request(
                    f"Entity?range={start}-{start + page_size - 1}&with_inheritance=true",
                    headers,
                )
                page = payload.get("value", []) if isinstance(payload, dict) else payload
                if not isinstance(page, list):
                    break
                entities.extend(page)
                if len(page) < page_size:
                    break
                start += page_size
        return entities

    def list_network_diagrams(self, entity_id: int | None = None) -> list[dict]:
        with self.session() as headers:
            diagrams: list[dict] = []
            page_size = 1000
            start = 0
            while True:
                payload = self._request(
                    f"PluginArchimapGraph?range={start}-{start + page_size - 1}",
                    headers,
                )
                page = payload.get("value", []) if isinstance(payload, dict) else payload
                if not isinstance(page, list):
                    break
                diagrams.extend(page)
                if len(page) < page_size:
                    break
                start += page_size
        if entity_id is not None:
            diagrams = [
                diagram
                for diagram in diagrams
                if str(diagram.get("entities_id", "")).isdigit()
                and int(diagram["entities_id"]) == int(entity_id)
            ]
        return diagrams

    def create_network_diagram(
        self,
        entity_id: int,
        name: str,
        description: str,
        graph_xml: str,
    ) -> int:
        diagram = {
            "entities_id": int(entity_id),
            "is_recursive": 0,
            "name": name[:45],
            "shortdescription": description[:100],
            "plugin_archimap_graphtypes_id": 1,
            "plugin_archimap_graphstates_id": 1,
            "graph": quote(graph_xml, safe=""),
            "is_helpdesk_visible": 1,
        }
        with self.session() as headers:
            response = self._request(
                "PluginArchimapGraph",
                headers,
                method="POST",
                payload={"input": diagram},
            )
            diagram_id = response.get("id") if isinstance(response, dict) else None
            if not diagram_id:
                raise GlpiError(f"GLPI no ha devuelto el ID del diagrama creado: {response}")
            self.link_diagram_to_entity(diagram_id, entity_id, headers=headers)
        return int(diagram_id)

    def link_diagram_to_entity(
        self,
        diagram_id: int,
        entity_id: int,
        headers: dict[str, str] | None = None,
    ) -> int:
        relation = {
            "plugin_archimap_graphs_id": int(diagram_id),
            "items_id": int(entity_id),
            "itemtype": "Entity",
        }
        if headers is None:
            with self.session() as session_headers:
                return self.link_diagram_to_entity(diagram_id, entity_id, headers=session_headers)
        else:
            response = self._request(
                "PluginArchimapGraph_Item",
                headers,
                method="POST",
                payload={"input": relation},
            )
        relation_id = response.get("id") if isinstance(response, dict) else None
        if not relation_id:
            raise GlpiError(f"GLPI no ha podido asociar el diagrama a la sede: {response}")
        return int(relation_id)

    def diagram_url(self, diagram_id: int) -> str:
        web_url = os.environ.get("GLPI_WEB_URL", "").strip().rstrip("/")
        if not web_url:
            web_url = self.url.removesuffix("/apirest.php")
        return f"{web_url}/marketplace/archimap/front/graph.form.php?id={int(diagram_id)}"


def format_address(entity: dict) -> str:
    parts = [
        entity.get("address"),
        entity.get("postcode"),
        entity.get("town"),
        entity.get("state"),
        entity.get("country"),
    ]
    return ", ".join(str(part).strip() for part in parts if part and str(part).strip())


def _split_cif_and_name(entity: dict) -> tuple[str, str]:
    name = str(entity.get("name", "")).strip()
    registered_cif = str(entity.get("registration_number") or "").strip()
    match = re.match(r"^([A-Z]\d{7}[A-Z0-9]|\d{8}[A-Z])\s*[-–]\s*(.+)$", name, re.IGNORECASE)
    if match:
        return registered_cif or match.group(1).upper(), match.group(2).strip()
    return registered_cif, name


def build_customer_catalog(entities: list[dict]) -> list[dict]:
    by_parent: dict[int, list[dict]] = {}
    by_id: dict[int, dict] = {}
    for entity in entities:
        if isinstance(entity.get("id"), int):
            by_id[entity["id"]] = entity
        parent_id = entity.get("entities_id")
        if isinstance(parent_id, int):
            by_parent.setdefault(parent_id, []).append(entity)

    roots = [entity for entity in entities if entity.get("entities_id") in (None, 0) and int(entity.get("level", 0) or 0) <= 1]
    root_ids = {entity["id"] for entity in roots if isinstance(entity.get("id"), int)}
    provinces = [
        entity
        for entity in entities
        if entity.get("entities_id") in root_ids and by_parent.get(entity.get("id"))
    ]

    catalog: list[dict] = []
    for province in sorted(provinces, key=lambda item: item.get("name", "").lower()):
        customers = []
        for customer in sorted(by_parent.get(province["id"], []), key=lambda item: item.get("name", "").lower()):
            cif, customer_name = _split_cif_and_name(customer)
            children = sorted(by_parent.get(customer["id"], []), key=lambda item: item.get("name", "").lower())
            sites = [
                {
                    "id": site.get("id"),
                    "nombre": site.get("name", ""),
                    "direccion": format_address(site) or format_address(customer),
                }
                for site in children
            ]
            if not sites:
                sites = [
                    {
                        "id": customer.get("id"),
                        "nombre": "Sede Principal",
                        "direccion": format_address(customer),
                    }
                ]
            customers.append(
                {
                    "id": customer.get("id"),
                    "nombre": customer_name,
                    "cif": cif,
                    "direccion": format_address(customer),
                    "sedes": sites,
                }
            )
        catalog.append(
            {
                "id": province.get("id"),
                "nombre": province.get("name", ""),
                "clientes": customers,
            }
        )
    return catalog
