from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta

from generator.glpi_client import GlpiError
from generator.safe_errors import public_error_message

MONTHS_ES = (
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
)


def activity_technician_name(row: dict) -> str:
    return row.get("technician_name") or row.get("technician", {}).get("name", "?")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _daily_labels(now: datetime, days: int) -> list[tuple[date, str]]:
    return [
        ((now - timedelta(days=offset)).date(), (now - timedelta(days=offset)).strftime("%d/%m"))
        for offset in range(days - 1, -1, -1)
    ]


def _year_month_windows(now: datetime) -> list[tuple[str, datetime, datetime, tuple[int, int]]]:
    windows: list[tuple[str, datetime, datetime, tuple[int, int]]] = []
    for offset in range(11, -1, -1):
        month = now.month - offset
        year = now.year
        while month <= 0:
            month += 12
            year -= 1
        tz = now.tzinfo or UTC
        start = datetime(year, month, 1, tzinfo=tz)
        end = (
            datetime(year + 1, 1, 1, tzinfo=tz)
            if month == 12
            else datetime(year, month + 1, 1, tzinfo=tz)
        )
        label = f"{MONTHS_ES[month - 1]} {str(year)[2:]}"
        windows.append((label, start, end, (year, month)))
    return windows


def build_admin_chart_periods(all_rows: list[dict], now: datetime) -> dict:
    """Aggregate activity rows into week/month/year chart payloads in a single O(N) pass."""
    now = _as_utc(now)
    cutoff_week = now - timedelta(days=7)
    cutoff_month = now - timedelta(days=30)
    cutoff_year = now - timedelta(days=365)

    week_days = _daily_labels(now, 7)
    month_days = _daily_labels(now, 30)
    year_windows = _year_month_windows(now)

    week_day_keys = {day for day, _ in week_days}
    month_day_keys = {day for day, _ in month_days}
    year_month_keys = {key: label for label, _, _, key in year_windows}

    daily_week = Counter({day: 0 for day, _ in week_days})
    daily_month = Counter({day: 0 for day, _ in month_days})
    monthly = Counter({label: 0 for label, _, _, _ in year_windows})

    week_rows: list[dict] = []
    month_rows: list[dict] = []
    year_rows: list[dict] = []
    tech_week: Counter[str] = Counter()
    tech_month: Counter[str] = Counter()
    tech_year: Counter[str] = Counter()

    for row in all_rows:
        created_ts = row.get("created_at")
        if created_ts is None:
            continue
        created = datetime.fromtimestamp(created_ts, UTC)
        created_day = created.date()
        technician = activity_technician_name(row)

        if created >= cutoff_year:
            year_rows.append(row)
            tech_year[technician] += 1
            month_label = year_month_keys.get((created.year, created.month))
            if month_label:
                monthly[month_label] += 1

        if created >= cutoff_month:
            month_rows.append(row)
            tech_month[technician] += 1
            if created_day in month_day_keys:
                daily_month[created_day] += 1

        if created >= cutoff_week:
            week_rows.append(row)
            tech_week[technician] += 1
            if created_day in week_day_keys:
                daily_week[created_day] += 1

    def period_payload(
        rows: list[dict],
        labels: list[str],
        values: list[int],
        technicians: Counter[str],
    ) -> dict:
        return {
            "labels": labels,
            "values": values,
            "total": len(rows),
            "top": [
                {"name": name, "count": count}
                for name, count in technicians.most_common(5)
            ],
        }

    week_labels = [label for _, label in week_days]
    month_labels = [label for _, label in month_days]
    year_labels = [label for label, _, _, _ in year_windows]

    return {
        "week": period_payload(
            week_rows,
            week_labels,
            [daily_week[day] for day, _ in week_days],
            tech_week,
        ),
        "month": period_payload(
            month_rows,
            month_labels,
            [daily_month[day] for day, _ in month_days],
            tech_month,
        ),
        "year": period_payload(
            year_rows,
            year_labels,
            [monthly[label] for label in year_labels],
            tech_year,
        ),
    }


def find_catalog_sede(catalog: list[dict], entity_id: int) -> dict | None:
    for province in catalog:
        for cliente in province.get("clientes", []):
            for sede in cliente.get("sedes", []):
                if sede.get("id") == entity_id:
                    return sede
    return None


def glpi_street(sede: dict) -> str:
    """Street address as stored in GLPI (ignores technician overrides)."""
    return sede.get("direccion_glpi") or sede.get("direccion", "")


def covered_entity_ids_from_diagrams(all_diagrams: list[dict]) -> set[int]:
    covered: set[int] = set()
    for diagram in all_diagrams:
        entity_id = diagram.get("entities_id")
        if entity_id and str(entity_id).isdigit():
            covered.add(int(entity_id))
    return covered


def _entity_covered(sede_id, cliente_id, covered: set[int]) -> bool:
    """Una sede está cubierta si su propio id tiene diagrama (publicado a nivel
    sede) o si lo tiene su cliente (en GLPI muchos diagramas cuelgan del cliente,
    no de la sede)."""
    if sede_id is not None and str(sede_id).isdigit() and int(sede_id) in covered:
        return True
    if cliente_id is not None and str(cliente_id).isdigit() and int(cliente_id) in covered:
        return True
    return False


def build_missing_sites_rows(catalog: list[dict], covered_entity_ids: set[int]) -> list[dict]:
    """Flat list of sedes without a diagram: cliente, sede, calle, provincia."""
    rows: list[dict] = []
    for province in catalog:
        province_name = province.get("nombre", "?")
        for cliente in province.get("clientes", []):
            client_name = cliente.get("nombre", "?")
            for sede in cliente.get("sedes", []):
                entity_id = sede.get("id")
                if entity_id is None:
                    continue
                if _entity_covered(entity_id, cliente.get("id"), covered_entity_ids):
                    continue
                rows.append(
                    {
                        "cliente": client_name,
                        "sede": sede.get("nombre", "?"),
                        "calle": glpi_street(sede),
                        "provincia": province_name,
                        "entity_id": int(entity_id),
                    }
                )
    rows.sort(key=lambda item: (item["provincia"], item["cliente"], item["sede"]))
    return rows


def build_coverage_data(
    catalog: list[dict],
    client,
    activity_rows: list[dict],
) -> dict | None:
    """Build coverage map: provinces with sites lacking a diagram."""
    if not client:
        return None

    try:
        covered_entity_ids = client.list_covered_entity_ids()
    except GlpiError as exc:
        return {
            "provinces": [],
            "total_sites": 0,
            "covered_sites": 0,
            "missing_sites": 0,
            "error": public_error_message(str(exc), context="consulta de diagramas GLPI"),
        }

    entity_to_province: dict[int, str] = {}
    total_sites = 0
    provinces_coverage: list[dict] = []

    for province in catalog:
        province_name = province.get("nombre", "?")
        province_data: dict = {
            "name": province_name,
            "technician": "",
            "total_sites": 0,
            "total_missing": 0,
            "clientes": [],
        }

        for cliente in province.get("clientes", []):
            client_name = cliente.get("nombre", "?")
            client_data: dict = {"name": client_name, "sedes": []}

            for sede in cliente.get("sedes", []):
                entity_id = sede.get("id")
                if entity_id is None:
                    continue
                total_sites += 1
                province_data["total_sites"] += 1
                entity_to_province[int(entity_id)] = province_name
                if not _entity_covered(entity_id, cliente.get("id"), covered_entity_ids):
                    client_data["sedes"].append(
                        {
                            "name": sede.get("nombre", "?"),
                            "direccion": sede.get("direccion", ""),
                            "entity_id": int(entity_id),
                        }
                    )
                    province_data["total_missing"] += 1

            if client_data["sedes"]:
                province_data["clientes"].append(client_data)

        if province_data["clientes"]:
            provinces_coverage.append(province_data)

    province_technicians: dict[str, Counter[str]] = defaultdict(Counter)
    for row in activity_rows:
        entity_id = row.get("entity_id")
        if not entity_id:
            continue
        province_name = entity_to_province.get(entity_id)
        if not province_name:
            continue
        technician = row.get("technician_name") or row.get("technician_username", "?")
        if technician and technician != "?":
            province_technicians[province_name][technician] += 1

    for province_data in provinces_coverage:
        technicians = province_technicians.get(province_data["name"])
        if technicians:
            province_data["technician"] = technicians.most_common(1)[0][0]

    provinces_coverage.sort(key=lambda item: item["total_missing"], reverse=True)
    missing_sites = sum(province["total_missing"] for province in provinces_coverage)
    return {
        "provinces": provinces_coverage,
        "total_sites": total_sites,
        "covered_sites": total_sites - missing_sites,
        "missing_sites": missing_sites,
        "error": None,
    }
