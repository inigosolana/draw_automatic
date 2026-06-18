"""Add missing phone icons to the mxlibrary XML file."""
from __future__ import annotations

import base64
import io
import json
import re
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
LIBRARY_PATH = ROOT / "library" / "libreria_Ausarta_JUN_2026.xml"
MAX_DIMENSION = 520

LIBRARY_SOURCES = {
    "T-30": str(ROOT / "assets" / "yealink_t30.png"),
    "T-33": str(ROOT / "assets" / "yealink_t33g.png"),
    "T-43": str(ROOT / "assets" / "yealink_t43u.png"),
    "T-44": str(ROOT / "assets" / "yealink_t44u.png"),
    "T-73": str(ROOT / "assets" / "yealink_t73w.png"),
    "TP-Link 8P": str(ROOT / "assets" / "tplink_8p.png"),
    "FANVIL_V64": "https://cdn11.bigcommerce.com/s-pbm1b2ubzb/images/stencil/1280x1280/products/2914/3946/1354b606zf05945.1687178785.png?c=1",
    "GXP2170": "https://content.grandstream.com/hubfs/Product%20Images/GXP/gxp2170_front_web.png",
}


def load_image(source: str) -> bytes:
    path = Path(source)
    if path.is_file():
        data = path.read_bytes()
    else:
        data = download_image(source)
    if len(data) < 1000:
        raise ValueError(f"image too small from {source}")
    return data


def download_image(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read()
    if len(data) < 5000:
        raise ValueError(f"image too small from {url}")
    return data


def image_to_data_uri(image_bytes: bytes) -> tuple[str, int, int]:
    with Image.open(io.BytesIO(image_bytes)) as image:
        image = image.convert("RGBA")
        width, height = image.size
        if max(width, height) > MAX_DIMENSION:
            scale = MAX_DIMENSION / max(width, height)
            image = image.resize(
                (max(1, int(width * scale)), max(1, int(height * scale))),
                Image.Resampling.LANCZOS,
            )
        width, height = image.size
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}", width, height


def load_entries() -> list[dict]:
    text = LIBRARY_PATH.read_text(encoding="utf-8")
    match = re.search(r"<mxlibrary>(.*)</mxlibrary>", text, re.DOTALL)
    if not match:
        raise ValueError("mxlibrary block not found")
    return json.loads(match.group(1))


def save_entries(entries: list[dict]) -> None:
    payload = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
    LIBRARY_PATH.write_text(f"<mxlibrary>{payload}</mxlibrary>\n", encoding="utf-8")


def upsert_phone(entries: list[dict], title: str, source: str) -> None:
    data_uri, width, height = image_to_data_uri(load_image(source))
    payload = {
        "title": title,
        "data": data_uri,
        "w": width,
        "h": height,
        "aspect": "fixed",
    }
    for index, entry in enumerate(entries):
        if entry.get("title") == title:
            entries[index] = payload
            print(f"updated: {title} ({width}x{height})")
            return
    entries.append(payload)
    print(f"added: {title} ({width}x{height})")


def main() -> None:
    entries = load_entries()
    for title, source in LIBRARY_SOURCES.items():
        upsert_phone(entries, title, source)
    entries = [entry for entry in entries if not str(entry.get("title", "")).startswith("Yealink_T33G")]
    save_entries(entries)
    print("library updated")


if __name__ == "__main__":
    main()
