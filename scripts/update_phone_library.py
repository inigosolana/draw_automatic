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
LIBRARY_PATH = ROOT / "libreria_Ausarta_JUN_2026.xml"
MAX_DIMENSION = 520

PHONE_SOURCES = {
    "T-30": "https://storage.googleapis.com/nxl-content/yealink/t30p-image-1.jpg",
    "T-43": "https://www.yealink.com/website-service/attachment/product/image/20220411/20220411105712296386c052c4461b54e15e1265968eb.png",
    "T-44": "https://www.yealink.com/website-service/attachment/product/image/20240201/20240201093245689c1bb7a3043e28c6ca82a8196d7fb.png",
    "T-73": "https://www.yealink.com/website-service/attachment/product/image/20250820/20250820062227606405d.jpg",
    "FANVIL_V64": "https://cdn11.bigcommerce.com/s-pbm1b2ubzb/images/stencil/1280x1280/products/2914/3946/1354b606zf05945.1687178785.png?c=1",
    "GXP2170": "https://content.grandstream.com/hubfs/Product%20Images/GXP/gxp2170_front_web.png",
}


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
    existing = next((entry for entry in entries if entry.get("title") == title), None)
    if existing:
        print(f"skip existing: {title}")
        return
    data_uri, width, height = image_to_data_uri(download_image(source))
    entries.append(
        {
            "title": title,
            "data": data_uri,
            "w": width,
            "h": height,
            "aspect": "fixed",
        }
    )
    print(f"added: {title} ({width}x{height})")


def main() -> None:
    entries = load_entries()
    for title, source in PHONE_SOURCES.items():
        upsert_phone(entries, title, source)
    save_entries(entries)
    print("library updated")


if __name__ == "__main__":
    main()
