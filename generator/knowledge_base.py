from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .aliases import normalize_name


KNOWLEDGE_PATH = Path(__file__).resolve().parents[1] / "data" / "learned_library.json"


def _plain_label(value: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", value or "", flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(html.unescape(text).split()).strip()


def _image_from_style(style: str) -> str:
    match = re.search(r"(?:^|;)image=(data:image/[^;]+;base64,[^;]+|[^;]+)", style or "")
    return match.group(1) if match else ""


def learn_from_drawio(xml: str, source_name: str, knowledge_path: Path = KNOWLEDGE_PATH) -> list[str]:
    root = ET.fromstring(xml)
    cells = list(root.iter("mxCell"))
    labels: list[tuple[float, float, str]] = []
    images: list[tuple[float, float, str, str]] = []

    for cell in cells:
        geometry = cell.find("mxGeometry")
        if geometry is None:
            continue
        x = float(geometry.get("x", 0) or 0)
        y = float(geometry.get("y", 0) or 0)
        value = _plain_label(cell.get("value", ""))
        image = _image_from_style(cell.get("style", ""))
        if image:
            images.append((x, y, image, value))
        elif value and not cell.get("edge"):
            labels.append((x, y, value))

    learned: dict[str, dict] = {}
    if knowledge_path.exists():
        try:
            learned = json.loads(knowledge_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            learned = {}

    added: list[str] = []
    for x, y, image, embedded_label in images:
        candidates = []
        if embedded_label:
            candidates.append((0.0, embedded_label))
        for label_x, label_y, label in labels:
            horizontal = abs(label_x - x)
            vertical = label_y - y
            if horizontal <= 100 and -40 <= vertical <= 260:
                candidates.append((horizontal + abs(vertical - 160), label))
        if not candidates:
            continue
        label = min(candidates, key=lambda item: item[0])[1]
        model = label.split(" EXT ", 1)[0].split(" SN ", 1)[0].strip()
        if not model or len(model) > 80:
            continue
        key = normalize_name(model)
        if key and key not in learned:
            learned[key] = {
                "title": model,
                "data": image,
                "width": 120,
                "height": 120,
                "source": source_name,
            }
            added.append(model)

    if added:
        knowledge_path.parent.mkdir(parents=True, exist_ok=True)
        knowledge_path.write_text(json.dumps(learned, ensure_ascii=False, indent=2), encoding="utf-8")
    return added


def load_learned_items(knowledge_path: Path = KNOWLEDGE_PATH) -> list[dict]:
    if not knowledge_path.exists():
        return []
    try:
        payload = json.loads(knowledge_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return list(payload.values()) if isinstance(payload, dict) else []
