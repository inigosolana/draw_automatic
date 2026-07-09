from __future__ import annotations

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .import_errors import CommsError
from .offer_mapper import ImportResult, extract_work_order_id
from .work_order_json import import_result_from_json_payload


def _normalize_work_order_id(reference: str) -> str:
    work_order_id = extract_work_order_id(reference)
    if not work_order_id:
        digits = re.sub(r"\D", "", reference or "")
        work_order_id = digits if len(digits) >= 3 else ""
    if work_order_id.isdigit():
        return str(int(work_order_id))
    return work_order_id


class CrmClient:
    def __init__(
        self,
        base_url: str,
        *,
        api_token: str = "",
        work_order_path: str = "/WorkOrders/getWorkOrderForDraw/{work_order_id}",
        timeout: int = 20,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token.strip()
        self.work_order_path = work_order_path.strip() or "/WorkOrders/getWorkOrderForDraw/{work_order_id}"
        self.timeout = timeout

    @classmethod
    def from_environment(cls) -> CrmClient | None:
        base_url = os.environ.get("CRM_API_URL", "").strip()
        api_token = os.environ.get("CRM_API_TOKEN", "").strip()
        if not base_url or not api_token:
            return None
        try:
            timeout = int(os.environ.get("CRM_API_TIMEOUT", "20") or 20)
        except (ValueError, TypeError):
            timeout = 20
        return cls(
            base_url,
            api_token=api_token,
            work_order_path=os.environ.get(
                "CRM_WORK_ORDER_PATH",
                "/WorkOrders/getWorkOrderForDraw/{work_order_id}",
            ).strip(),
            timeout=timeout,
        )

    def _work_order_url(self, work_order_id: str) -> str:
        path = self.work_order_path
        if "{work_order_id}" in path:
            path = path.format(work_order_id=work_order_id)
        elif "{id}" in path:
            path = path.format(id=work_order_id)
        else:
            path = path.rstrip("/") + f"/{work_order_id}"
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}{path if path.startswith('/') else '/' + path}"

    def fetch_work_order(self, work_order_id: str) -> dict:
        if not self.api_token:
            raise CommsError("CRM_API_TOKEN no esta configurado.")
        url = self._work_order_url(work_order_id)
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "Accept": "application/json",
                "User-Agent": "AusartaDrawioImporter/1.0",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:300]
            raise CommsError(f"El CRM respondio con error {exc.code}: {body}") from exc
        except URLError as exc:
            raise CommsError(f"No se ha podido consultar el CRM: {exc.reason}") from exc

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CommsError("El CRM no devolvio JSON valido.") from exc
        if not isinstance(payload, dict):
            raise CommsError("El CRM devolvio un JSON que no es un objeto.")
        return payload

    def import_work_order(self, reference: str) -> ImportResult:
        work_order_id = _normalize_work_order_id(reference)
        if not work_order_id:
            raise CommsError("No se ha podido extraer el ID de la orden de trabajo.")
        payload = self.fetch_work_order(work_order_id)
        return import_result_from_json_payload(payload, work_order_id=work_order_id)


def crm_configured() -> bool:
    return CrmClient.from_environment() is not None
