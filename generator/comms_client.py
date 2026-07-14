from __future__ import annotations

import json
import os
import re
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from .offer_mapper import ImportResult, extract_work_order_id, map_offer_to_form, normalize_products, parse_product_lines
from .work_order_json import import_result_from_json_payload, normalize_work_order_payload


from .import_errors import CommsError


class _LabelValueParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.labels: dict[str, str] = {}
        self._active_label = ""
        self._capture: list[str] = []
        self._in_table = False
        self._table_headers: list[str] = []
        self._table_rows: list[list[str]] = []
        self._current_row: list[str] = []
        self._cell_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key: value or "" for key, value in attrs}
        if tag in {"td", "th"}:
            self._cell_text = []
        if tag == "table":
            self._in_table = True
            self._table_headers = []
            self._table_rows = []
        if tag == "tr" and self._in_table:
            self._current_row = []
        if tag in {"dt", "label", "strong", "b"}:
            self._capture = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"dt", "label", "strong", "b"}:
            label = re.sub(r"\s+", " ", "".join(self._capture)).strip(" :")
            if label:
                self._active_label = label
        if tag in {"dd", "p", "span", "div", "td"} and self._active_label:
            value = re.sub(r"\s+", " ", "".join(self._capture)).strip()
            if value and len(value) < 300:
                self.labels.setdefault(self._active_label.lower(), value)
            self._active_label = ""
            self._capture = []
        if tag in {"td", "th"}:
            value = re.sub(r"\s+", " ", "".join(self._cell_text)).strip()
            self._current_row.append(value)
        if tag == "tr" and self._in_table:
            if self._current_row:
                if not self._table_headers and any(
                    header in " ".join(self._current_row).lower()
                    for header in ("producto", "descripcion", "descripción", "articulo", "artículo")
                ):
                    self._table_headers = [cell.lower() for cell in self._current_row]
                else:
                    self._table_rows.append(self._current_row)
        if tag == "table":
            self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._active_label or self._in_table:
            self._capture.append(data)
        if self._in_table:
            self._cell_text.append(data)


def _first_label(labels: dict[str, str], *candidates: str) -> str:
    for candidate in candidates:
        for key, value in labels.items():
            if candidate in key:
                return value
    return ""


def _products_from_table(headers: list[str], rows: list[list[str]]) -> list[dict]:
    if not rows:
        return []
    name_index = 0
    qty_index = -1
    for index, header in enumerate(headers):
        if any(token in header for token in ("producto", "descripcion", "descripción", "articulo", "artículo", "modelo")):
            name_index = index
        if any(token in header for token in ("cant", "qty", "unidad")):
            qty_index = index
    products: list[dict] = []
    for row in rows:
        if len(row) <= name_index:
            continue
        name = row[name_index].strip()
        if not name:
            continue
        quantity = 1
        if qty_index >= 0 and qty_index < len(row):
            qty_text = re.sub(r"[^\d]", "", row[qty_index])
            if qty_text.isdigit():
                quantity = max(1, int(qty_text))
        products.append({"name": name, "quantity": quantity})
    return products


def parse_work_order_html(html: str) -> dict:
    parser = _LabelValueParser()
    parser.feed(html)

    inline_labels = {
        "cliente": r"(?:cliente|raz[oó]n social|empresa)\s*:?\s*</[^>]+>\s*([^<]+)",
        "cif": r"(?:cif|nif)\s*:?\s*</[^>]+>\s*([^<]+)",
        "sede": r"(?:sede|centro|ubicaci[oó]n|instalaci[oó]n)\s*:?\s*</[^>]+>\s*([^<]+)",
        "direccion": r"(?:direcci[oó]n|domicilio|calle)\s*:?\s*</[^>]+>\s*([^<]+)",
    }
    extracted: dict[str, str] = {}
    for key, pattern in inline_labels.items():
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            extracted[key] = re.sub(r"\s+", " ", match.group(1)).strip()

    products = _products_from_table(parser._table_headers, parser._table_rows)
    if not products:
        for row in parser._table_rows:
            if len(row) == 1 and row[0]:
                products.append({"name": row[0], "quantity": 1})
            elif len(row) >= 2 and row[0] and not row[0].lower().startswith("total"):
                qty_text = re.sub(r"[^\d]", "", row[0])
                if qty_text.isdigit():
                    products.append({"name": row[1], "quantity": max(1, int(qty_text))})
                else:
                    products.append({"name": row[0], "quantity": 1})

    script_products: list[dict] = []
    _decoder = json.JSONDecoder()
    for match in re.finditer(r"<script[^>]*>(.*?)</script>", html, re.IGNORECASE | re.DOTALL):
        block = match.group(1)
        # Decodificar los objetos JSON del bloque con raw_decode (admite
        # anidamiento) y quedarse con los que expongan una clave "product(s)".
        pos = 0
        while True:
            start = block.find("{", pos)
            if start == -1:
                break
            try:
                payload, end = _decoder.raw_decode(block, start)
            except json.JSONDecodeError:
                pos = start + 1
                continue
            pos = end
            if not isinstance(payload, dict):
                continue
            raw = payload.get("products") or payload.get("product")
            if isinstance(raw, list):
                script_products.extend(item for item in raw if isinstance(item, dict))
    if script_products:
        products = script_products

    return {
        "cliente": extracted.get("cliente") or _first_label(parser.labels, "cliente", "razon social", "razón social", "empresa"),
        "cif": extracted.get("cif") or _first_label(parser.labels, "cif", "nif"),
        "sede": extracted.get("sede") or _first_label(parser.labels, "sede", "centro", "ubicacion", "ubicación", "instalacion", "instalación"),
        "direccion": extracted.get("direccion") or _first_label(parser.labels, "direccion", "dirección", "domicilio", "calle"),
        "connectivity_text": " ".join(parser.labels.values()),
        "products": products,
    }


class CommsClient:
    def __init__(
        self,
        base_url: str,
        *,
        api_token: str = "",
        username: str = "",
        password: str = "",
        timeout: int = 20,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token.strip()
        self.username = username.strip()
        self.password = password
        self.timeout = timeout
        self._opener = build_opener(HTTPCookieProcessor())

    @classmethod
    def from_environment(cls) -> CommsClient | None:
        base_url = os.environ.get("COMMS_URL", "https://comms.aureamotriz.com").strip()
        api_token = os.environ.get("COMMS_API_TOKEN", "").strip()
        username = os.environ.get("COMMS_USERNAME", "").strip()
        password = os.environ.get("COMMS_PASSWORD", "")
        if not (api_token or (username and password)):
            return None
        return cls(base_url, api_token=api_token, username=username, password=password)

    def _request(self, url: str, *, headers: dict[str, str] | None = None, data: bytes | None = None, method: str = "GET") -> bytes:
        request_headers = {"User-Agent": "AusartaDrawioImporter/1.0", "Accept": "*/*"}
        if headers:
            request_headers.update(headers)
        request = Request(url, headers=request_headers, data=data, method=method)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:300]
            raise CommsError(f"Comms ha respondido con error {exc.code}: {body}") from exc
        except URLError as exc:
            raise CommsError(f"No se ha podido consultar AusartaConecta: {exc.reason}") from exc

    def _login(self) -> None:
        if not self.username or not self.password:
            raise CommsError("Faltan credenciales COMMS_USERNAME / COMMS_PASSWORD.")
        login_html = self._request(f"{self.base_url}/login/login").decode("utf-8", errors="replace")
        token_match = re.search(r'name="_csrfToken"\s+[^>]*value="([^"]+)"', login_html)
        if not token_match:
            raise CommsError("No se ha podido obtener el token CSRF de AusartaConecta.")
        form = urlencode(
            {
                "_csrfToken": token_match.group(1),
                "username": self.username,
                "password": self.password,
            }
        ).encode("utf-8")
        self._request(
            f"{self.base_url}/login/login",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=form,
            method="POST",
        )

    def _fetch_api_json(self, work_order_id: str) -> dict | None:
        if not self.api_token:
            return None
        headers = {"Authorization": f"Bearer {self.api_token}", "Accept": "application/json"}
        candidates = [
            f"{self.base_url}/api/work-orders/{work_order_id}",
            f"{self.base_url}/api/customers/work-order/{work_order_id}",
            f"{self.base_url}/customers/work-order/{work_order_id}.json",
        ]
        for url in candidates:
            try:
                raw = self._request(url, headers=headers)
            except CommsError:
                continue
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(payload, dict):
                return payload
        return None

    def _fetch_html_page(self, work_order_id: str) -> str:
        if self.username and self.password:
            self._login()
        url = f"{self.base_url}/customers/work-order/{work_order_id}"
        html = self._request(url).decode("utf-8", errors="replace")
        if "login/login" in html and 'name="_csrfToken"' in html:
            raise CommsError("AusartaConecta ha pedido login. Revisa COMMS_USERNAME y COMMS_PASSWORD.")
        return html

    def import_work_order(self, reference: str) -> ImportResult:
        work_order_id = extract_work_order_id(reference)
        if not work_order_id:
            raise CommsError("No se ha podido extraer el ID de la oferta.")

        payload: dict | None = self._fetch_api_json(work_order_id)
        if payload is not None:
            return import_result_from_json_payload(payload, work_order_id=work_order_id)
        else:
            html = self._fetch_html_page(work_order_id)
            normalized = parse_work_order_html(html)

        products = normalize_products(normalized.get("products") or [])
        if not products:
            raise CommsError("La oferta no contiene productos reconocibles.")

        return map_offer_to_form(
            products,
            cliente=normalized.get("cliente", ""),
            cif=normalized.get("cif", ""),
            sede=normalized.get("sede", ""),
            direccion=normalized.get("direccion", ""),
            connectivity_text=normalized.get("connectivity_text", ""),
            work_order_id=work_order_id,
        )


def import_products_text(text: str, *, work_order_id: str = "") -> ImportResult:
    products = parse_product_lines(text)
    if not products:
        raise CommsError("No se han encontrado productos en el texto pegado.")
    return map_offer_to_form(products, work_order_id=work_order_id)
