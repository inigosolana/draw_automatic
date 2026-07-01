from __future__ import annotations

import json
import os
import re
import ssl
import time
from base64 import b64encode
from contextlib import contextmanager
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote
from urllib.request import Request, urlopen

from .address_formatter import to_glpi_ascii
from .diagram_metadata import build_diagram_description, diagram_base_name, versioned_diagram_name


class GlpiError(RuntimeError):
    pass


class GlpiEndpoints:
    """Centralized GLPI REST and Archimap web paths."""

    INIT_SESSION = "initSession"
    KILL_SESSION = "killSession"
    GET_FULL_SESSION = "getFullSession"
    ENTITY = "Entity"
    PLUGIN_ARCHIMAP_GRAPH = "PluginArchimapGraph"
    PLUGIN_ARCHIMAP_GRAPH_ITEM = "PluginArchimapGraph_Item"
    ARCHIMAP_GRAPH_FORM = "/marketplace/archimap/front/graph.form.php"

    @classmethod
    def entity_page(cls, start: int, page_size: int) -> str:
        end = start + page_size - 1
        return f"{cls.ENTITY}?range={start}-{end}&with_inheritance=true"

    # Search fields for PluginArchimapGraph (from listSearchOptions). Using the
    # search API avoids pulling the heavy `graph` blob that makes getAllItems
    # return multi-MB rows and crash GLPI (HTTP 500) on large ranges.
    ARCHIMAP_SEARCH_FIELDS = {
        "id": 72,
        "name": 1,
        "shortdescription": 2,
        "plugin_archimap_graphstates_id": 6,
        "entities_id": 81,
        # Campo 80 = nombre completo de la entidad REAL del diagrama (la sede).
        # El 81 devuelve la entidad PADRE, no la propia; usamos el 80 + el mapa
        # completename->id para conocer la sede exacta.
        "entity_completename": 80,
    }

    @classmethod
    def archimap_search_page(
        cls, start: int, page_size: int, entity_id: int | None = None
    ) -> str:
        end = start + page_size - 1
        parts = [f"range={start}-{end}"]
        for index, field in enumerate(cls.ARCHIMAP_SEARCH_FIELDS.values()):
            parts.append(f"forcedisplay[{index}]={field}")
        if entity_id is not None:
            parts.append(f"criteria[0][field]={cls.ARCHIMAP_SEARCH_FIELDS['entities_id']}")
            parts.append("criteria[0][searchtype]=equals")
            parts.append(f"criteria[0][value]={int(entity_id)}")
        return f"search/{cls.PLUGIN_ARCHIMAP_GRAPH}?" + "&".join(parts)

    @classmethod
    def archimap_entities_page(cls, start: int, page_size: int) -> str:
        """Pagina pidiendo el nombre completo de la entidad (cobertura ligera).

        Usamos el campo 80 (nombre completo de la entidad REAL = la sede) y no el
        81 (que devuelve la entidad padre), para que la cobertura sea por sede.
        """
        end = start + page_size - 1
        field = cls.ARCHIMAP_SEARCH_FIELDS["entity_completename"]
        return f"search/{cls.PLUGIN_ARCHIMAP_GRAPH}?range={start}-{end}&forcedisplay[0]={field}"


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _unverified_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


# Cache (compartida entre instancias/peticiones) del mapa completename->id de
# entidades GLPI, para no re-listar todas las entidades en cada consulta.
_ENTITY_CN_CACHE: dict[str, tuple[float, dict[str, int]]] = {}
_ENTITY_CN_TTL = 300


class GlpiClient:
    def __init__(
        self,
        url: str,
        app_token: str,
        user_token: str,
        timeout: int = 15,
        *,
        verify_ssl: bool = True,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.app_token = app_token
        self.user_token = user_token
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        if not self.verify_ssl:
            import logging

            logging.getLogger("security").warning(
                "GLPI_VERIFY_SSL=0 — verificacion TLS desactivada. "
                "No uses esta opcion en produccion."
            )
        self._ssl_context = ssl_context
        # Cuando batch_session() esta activo, todas las operaciones reutilizan
        # esta sesion en vez de hacer initSession/killSession en cada llamada.
        self._active_headers: dict[str, str] | None = None
        # Cache completename->id de entidades (para resolver la entidad REAL de
        # cada diagrama: la search API devuelve el nombre completo, no el id).
        self._entity_cn_map: dict[str, int] | None = None

    def entity_id_by_completename(self) -> dict[str, int]:
        if self._entity_cn_map is not None:
            return self._entity_cn_map
        # Cache entre peticiones (no solo por instancia): listar todas las
        # entidades es caro y cambia poco. TTL de 5 min.
        now = time.time()
        cached = _ENTITY_CN_CACHE.get(self.url)
        if cached and cached[0] > now:
            self._entity_cn_map = cached[1]
            return cached[1]
        mapping: dict[str, int] = {}
        for entity in self.list_entities():
            cn = str(entity.get("completename") or "").strip()
            if cn and str(entity.get("id") or "").isdigit():
                mapping[cn] = int(entity["id"])
        _ENTITY_CN_CACHE[self.url] = (now + _ENTITY_CN_TTL, mapping)
        self._entity_cn_map = mapping
        return mapping

    @classmethod
    def from_environment(cls) -> GlpiClient | None:
        url = os.environ.get("GLPI_URL", "").strip()
        app_token = os.environ.get("GLPI_APP_TOKEN", "").strip()
        user_token = os.environ.get("GLPI_USER_TOKEN", "").strip()
        if not all((url, app_token, user_token)):
            return None
        verify_ssl = _env_bool("GLPI_VERIFY_SSL", default=True)
        ssl_context = None
        ca_bundle = os.environ.get("GLPI_CA_BUNDLE", "").strip()
        if verify_ssl and ca_bundle:
            # Verificar contra un CA propio (cert autofirmado) sin desactivar TLS.
            ssl_context = ssl.create_default_context(cafile=ca_bundle)
        return cls(
            url, app_token, user_token, verify_ssl=verify_ssl, ssl_context=ssl_context
        )

    def _urlopen_context(self) -> ssl.SSLContext | None:
        if self._ssl_context is not None:
            return self._ssl_context
        if not self.verify_ssl:
            return _unverified_ssl_context()
        return None

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
            with urlopen(request, timeout=self.timeout, context=self._urlopen_context()) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            # GLPI devuelve el motivo en el cuerpo (normalmente ["ERROR_X","mensaje"]).
            # Lo capturamos para saber QUÉ ha rechazado y poder explicarlo.
            reason = ""
            try:
                raw = exc.read().decode("utf-8", "replace")
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    reason = " ".join(str(p) for p in parsed if p)
                elif isinstance(parsed, dict):
                    reason = str(parsed.get("message") or parsed.get("0") or "")
                else:
                    reason = str(parsed)
                reason = " ".join(reason.split())[:200]
            except (ValueError, OSError):
                reason = ""
            if reason:
                raise GlpiError(
                    f"GLPI ha rechazado la operacion (codigo {exc.code}): {reason}"
                ) from exc
            raise GlpiError(f"GLPI ha rechazado la operacion (codigo {exc.code}).") from exc
        except URLError as exc:
            raise GlpiError("No se ha podido conectar con GLPI.") from exc
        except (TimeoutError, json.JSONDecodeError) as exc:
            raise GlpiError("No se ha podido consultar GLPI.") from exc

    def authenticate_user(self, username: str, password: str) -> dict:
        credentials = b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        auth_headers = {
            "App-Token": self.app_token,
            "Authorization": f"Basic {credentials}",
        }
        payload = self._request(GlpiEndpoints.INIT_SESSION, auth_headers)
        session_token = payload.get("session_token") if isinstance(payload, dict) else None
        if not session_token:
            raise GlpiError("No se ha podido iniciar sesion.")
        headers = {"App-Token": self.app_token, "Session-Token": session_token}
        try:
            full_session = self._request(GlpiEndpoints.GET_FULL_SESSION, headers)
            session_data = full_session.get("session", full_session) if isinstance(full_session, dict) else {}
            return {
                "id": session_data.get("glpiID"),
                "username": session_data.get("glpiname") or username,
                "name": session_data.get("glpifriendlyname") or session_data.get("glpirealname") or username,
            }
        finally:
            try:
                self._request(GlpiEndpoints.KILL_SESSION, headers)
            except GlpiError as exc:
                import logging
                logging.getLogger("security").warning(f"No se pudo cerrar la sesion GLPI de usuario: {exc}")

    @contextmanager
    def session(self):
        auth_headers = {
            "App-Token": self.app_token,
            "Authorization": f"user_token {self.user_token}",
        }
        payload = self._request(GlpiEndpoints.INIT_SESSION, auth_headers)
        session_token = payload.get("session_token") if isinstance(payload, dict) else None
        if not session_token:
            raise GlpiError("No se ha podido iniciar sesion de servicio.")
        headers = {"App-Token": self.app_token, "Session-Token": session_token}
        try:
            yield headers
        finally:
            try:
                self._request(GlpiEndpoints.KILL_SESSION, headers)
            except GlpiError as exc:
                import logging
                logging.getLogger("security").warning(f"No se pudo cerrar la sesion GLPI de servicio: {exc}")

    @contextmanager
    def _session_or_active(self):
        """Reutiliza la sesion abierta por batch_session() si la hay; si no,
        abre (y cierra) una propia. Mantiene el comportamiento anterior."""
        if self._active_headers is not None:
            yield self._active_headers
        else:
            with self.session() as headers:
                yield headers

    @contextmanager
    def batch_session(self):
        """Abre UNA sesion GLPI para varias operaciones del mismo request,
        evitando un par initSession/killSession por cada llamada.

            with client.batch_session():
                client.list_network_diagrams(entity_id)
                client.create_network_diagram(...)
        """
        if self._active_headers is not None:
            # Ya hay una sesion batch activa: anidar no abre otra.
            yield self
            return
        with self.session() as headers:
            self._active_headers = headers
            try:
                yield self
            finally:
                self._active_headers = None

    def list_entities(self) -> list[dict]:
        with self._session_or_active() as headers:
            entities: list[dict] = []
            page_size = 1000
            start = 0
            while True:
                payload = self._request(GlpiEndpoints.entity_page(start, page_size), headers)
                page = payload.get("value", []) if isinstance(payload, dict) else payload
                if not isinstance(page, list):
                    break
                entities.extend(page)
                if len(page) < page_size:
                    break
                start += page_size
        return entities

    def list_network_diagrams(self, entity_id: int | None = None) -> list[dict]:
        """List network diagrams via the GLPI search API.

        We deliberately avoid the getAllItems endpoint: it returns the full
        `graph` XML for every diagram (~1 MB each), so a page of 50+ diagrams
        overflows GLPI's PHP memory and the server answers HTTP 500. The search
        API lets us request only the lightweight columns we need.

        El filtro por entidad se hace en Python tras recibir: el criteria
        server-side sobre el campo de entidad del plugin Archimap NO filtra de
        forma fiable, y al ser pocos diagramas (decenas) traerlos todos sin el
        blob `graph` es barato y correcto.
        """
        fields = GlpiEndpoints.ARCHIMAP_SEARCH_FIELDS
        diagrams: list[dict] = []
        with self._session_or_active() as headers:
            page_size = 200
            start = 0
            total: int | None = None
            while True:
                payload = self._request(
                    GlpiEndpoints.archimap_search_page(start, page_size),
                    headers,
                )
                rows = payload.get("data") if isinstance(payload, dict) else None
                if not isinstance(rows, list) or not rows:
                    break
                cn_map = self.entity_id_by_completename()
                for row in rows:
                    # Entidad REAL del diagrama vía nombre completo (campo 80);
                    # si no resuelve, caemos al campo 81 (padre) como antes.
                    completename = str(row.get(str(fields["entity_completename"])) or "").strip()
                    real_entity = cn_map.get(completename)
                    diagrams.append(
                        {
                            "id": row.get(str(fields["id"])),
                            "name": row.get(str(fields["name"])) or "",
                            "shortdescription": row.get(str(fields["shortdescription"])) or "",
                            "plugin_archimap_graphstates_id": row.get(
                                str(fields["plugin_archimap_graphstates_id"])
                            )
                            or "",
                            "entities_id": real_entity
                            if real_entity is not None
                            else row.get(str(fields["entities_id"])),
                        }
                    )
                # Avanzamos por las filas REALMENTE devueltas: si GLPI limita el
                # tamaño de página por debajo de lo pedido (list_limit), un
                # "len(rows) < page_size" cortaría antes de tiempo y perdería
                # diagramas. El totalcount nos dice cuándo hemos terminado.
                if total is None:
                    try:
                        total = int(payload.get("totalcount"))
                    except (TypeError, ValueError):
                        total = None
                start += len(rows)
                if total is not None:
                    if start >= total:
                        break
                elif len(rows) < page_size:
                    break
        if entity_id is not None:
            diagrams = [
                diagram
                for diagram in diagrams
                if str(diagram.get("entities_id", "")).isdigit()
                and int(diagram["entities_id"]) == int(entity_id)
            ]
        return diagrams

    def list_covered_entity_ids(self) -> set[int]:
        """Conjunto de entities_id con al menos un diagrama.

        Mucho mas ligero que list_network_diagrams(): pide solo el campo
        entities_id, sin nombre/descripcion/estado. Usado por la cobertura del
        admin y el export de sedes sin diagrama.
        """
        field_key = str(GlpiEndpoints.ARCHIMAP_SEARCH_FIELDS["entity_completename"])
        cn_map = self.entity_id_by_completename()
        covered: set[int] = set()
        with self._session_or_active() as headers:
            page_size = 500
            start = 0
            total: int | None = None
            while True:
                payload = self._request(
                    GlpiEndpoints.archimap_entities_page(start, page_size), headers
                )
                rows = payload.get("data") if isinstance(payload, dict) else None
                if not isinstance(rows, list) or not rows:
                    break
                for row in rows:
                    # Resolver la sede real por su nombre completo (campo 80).
                    real_id = cn_map.get(str(row.get(field_key) or "").strip())
                    if real_id is not None:
                        covered.add(int(real_id))
                # Igual que list_network_diagrams: avanzar por filas reales y
                # parar con totalcount para no infra-paginar si el servidor
                # limita el tamaño de página.
                if total is None:
                    try:
                        total = int(payload.get("totalcount"))
                    except (TypeError, ValueError):
                        total = None
                start += len(rows)
                if total is not None:
                    if start >= total:
                        break
                elif len(rows) < page_size:
                    break
        return covered

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
            # Estado 2 = "Validated": el diagrama se abre en GLPI en SOLO LECTURA
            # (Archimap bloquea la edición de grafos validados; hay que "Reabrir"
            # para editar). Estado 1 = "In Progress" lo abría editable.
            "plugin_archimap_graphstates_id": 2,
            "graph": quote(graph_xml, safe=""),
            "is_helpdesk_visible": 1,
        }
        with self._session_or_active() as headers:
            response = self._request(
                GlpiEndpoints.PLUGIN_ARCHIMAP_GRAPH,
                headers,
                method="POST",
                payload={"input": diagram},
            )
            diagram_id = response.get("id") if isinstance(response, dict) else None
            if not diagram_id:
                raise GlpiError("GLPI no ha devuelto el ID del diagrama creado.")
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
                GlpiEndpoints.PLUGIN_ARCHIMAP_GRAPH_ITEM,
                headers,
                method="POST",
                payload={"input": relation},
            )
        relation_id = response.get("id") if isinstance(response, dict) else None
        if not relation_id:
            raise GlpiError("GLPI no ha podido asociar el diagrama a la sede.")
        return int(relation_id)

    def diagram_url(self, diagram_id: int) -> str:
        web_url = os.environ.get("GLPI_WEB_URL", "").strip().rstrip("/")
        if not web_url:
            web_url = self.url.removesuffix("/apirest.php")
        return f"{web_url}{GlpiEndpoints.ARCHIMAP_GRAPH_FORM}?id={int(diagram_id)}"

    def get_network_diagram(self, diagram_id: int) -> dict:
        with self._session_or_active() as headers:
            payload = self._request(
                f"{GlpiEndpoints.PLUGIN_ARCHIMAP_GRAPH}/{int(diagram_id)}",
                headers,
            )
        if not isinstance(payload, dict) or not payload.get("id"):
            raise GlpiError("Diagrama no encontrado.")
        return payload

    def get_network_diagram_xml(self, diagram_id: int) -> tuple[str, str]:
        diagram = self.get_network_diagram(diagram_id)
        raw_graph = str(diagram.get("graph") or "").strip()
        if not raw_graph:
            raise GlpiError("El diagrama no tiene contenido draw.io.")
        xml = unquote(raw_graph) if raw_graph.startswith("%") else raw_graph
        if not xml.lstrip().startswith("<"):
            raise GlpiError("El diagrama no contiene un mxfile valido.")
        name = str(diagram.get("name") or f"Diagrama-{diagram_id}").strip()
        return xml, name

    def delete_network_diagram(self, diagram_id: int) -> None:
        with self._session_or_active() as headers:
            self._request(
                f"{GlpiEndpoints.PLUGIN_ARCHIMAP_GRAPH}/{int(diagram_id)}",
                headers,
                method="DELETE",
            )

    def update_entity_address(self, entity_id: int, address: str) -> None:
        from .address_formatter import normalize_street_address

        clean_address = normalize_street_address(address)
        if not clean_address:
            raise GlpiError("La direccion no es valida.")
        with self._session_or_active() as headers:
            self._request(
                f"{GlpiEndpoints.ENTITY}/{int(entity_id)}",
                headers,
                method="PUT",
                payload={
                    "input": {
                        "id": int(entity_id),
                        "address": to_glpi_ascii(clean_address),
                    }
                },
            )

    def create_site_entity(self, client_id: int, name: str, address: str = "") -> tuple[int, str]:
        """Crea una sede (Entity hija) bajo el cliente indicado. Devuelve (id, nombre)."""
        clean_name = re.sub(r"\s+", " ", (name or "")).strip()
        if not clean_name:
            raise GlpiError("El nombre de la sede no puede estar vacío.")
        payload_input = {
            "name": to_glpi_ascii(clean_name)[:255],
            "entities_id": int(client_id),
        }
        if address and address.strip():
            from .address_formatter import normalize_street_address

            payload_input["address"] = to_glpi_ascii(normalize_street_address(address) or address.strip())
        with self._session_or_active() as headers:
            response = self._request(
                GlpiEndpoints.ENTITY,
                headers,
                method="POST",
                payload={"input": payload_input},
            )
        new_id = response.get("id") if isinstance(response, dict) else None
        if not new_id:
            raise GlpiError("GLPI no ha devuelto el ID de la sede creada.")
        # Invalidar caché de completename->id: la nueva sede debe ser resoluble.
        _ENTITY_CN_CACHE.pop(self.url, None)
        return int(new_id), clean_name

    def update_network_diagram_graph(self, diagram_id: int, graph_xml: str) -> None:
        with self._session_or_active() as headers:
            self._request(
                f"{GlpiEndpoints.PLUGIN_ARCHIMAP_GRAPH}/{int(diagram_id)}",
                headers,
                method="PUT",
                payload={
                    "input": {
                        "id": int(diagram_id),
                        "graph": quote(graph_xml, safe=""),
                    }
                },
            )

    def save_network_diagram_version(
        self,
        diagram_id: int,
        graph_xml: str,
        *,
        technician: dict | None = None,
    ) -> tuple[int, str]:
        """Persist changes on the edited diagram and create a dated copy in GLPI."""
        diagram = self.get_network_diagram(diagram_id)
        entity_id = diagram.get("entities_id")
        if not isinstance(entity_id, int) or entity_id <= 0:
            raise GlpiError("No se pudo determinar la sede del diagrama.")
        source_name = str(diagram.get("name") or f"Diagrama-{diagram_id}").strip()
        base_name = diagram_base_name(source_name)
        version_name = versioned_diagram_name(base_name)
        tech = technician or {}
        if " - " in base_name:
            client_name, site_name = base_name.split(" - ", 1)
        else:
            client_name, site_name = base_name, ""
        description = build_diagram_description(
            client_name=client_name,
            site_name=site_name,
            technician=tech,
            source="Version",
            filename=f"{version_name}.drawio",
        )
        # Creamos primero la copia fechada (backup) y DESPUÉS actualizamos el
        # diagrama original. Así, si el segundo paso falla, la copia ya existe y
        # no perdemos el contenido nuevo (evita un estado sin respaldo).
        version_id = self.create_network_diagram(
            entity_id=entity_id,
            name=version_name,
            description=description,
            graph_xml=graph_xml,
        )
        self.update_network_diagram_graph(diagram_id, graph_xml)
        return int(version_id), version_name


def format_address(entity: dict) -> str:
    parts = [
        entity.get("address"),
        entity.get("postcode"),
        entity.get("town"),
        entity.get("state"),
        entity.get("country"),
    ]
    return to_glpi_ascii(", ".join(str(part).strip() for part in parts if part and str(part).strip()))


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
