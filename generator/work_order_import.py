from __future__ import annotations

from generator.comms_client import CommsClient
from generator.crm_client import CrmClient
from generator.import_errors import CommsError


def import_work_order_by_id(reference: str):
    crm_client = CrmClient.from_environment()
    if crm_client:
        return crm_client.import_work_order(reference)
    comms_client = CommsClient.from_environment()
    if comms_client:
        return comms_client.import_work_order(reference)
    raise CommsError(
        "No hay CRM ni AusartaConecta configurados. "
        "Define CRM_API_URL y CRM_API_TOKEN, o COMMS_* en el entorno."
    )
