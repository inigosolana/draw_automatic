"""Remove backgrounds from local assets and embedded mxlibrary images."""
from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path

from rembg import remove

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = PROJECT_ROOT / "assets"
DEFAULT_LIBRARY = PROJECT_ROOT / "library" / "libreria_Ausarta_JUN_2026.xml"
DATA_URI_RE = re.compile(r"^data:image/[^;]+;base64,(.+)$", re.DOTALL)


def _decode_data_uri(data_uri: str) -> bytes | None:
    match = DATA_URI_RE.match(data_uri.strip())
    if not match:
        return None
    return base64.b64decode(match.group(1))


def _encode_png_data_uri(image_bytes: bytes) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def process_image_bytes(data: bytes, label: str) -> bytes:
    print(f"  {label} ...", flush=True)
    return remove(data)


def process_assets() -> int:
    if not ASSETS_DIR.exists():
        return 0
    count = 0
    for path in sorted(ASSETS_DIR.glob("*.png")):
        result = process_image_bytes(path.read_bytes(), path.name)
        path.write_bytes(result)
        count += 1
    return count


def process_library(library_path: Path) -> tuple[int, int]:
    text = library_path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"<mxlibrary>(.*)</mxlibrary>", text, re.DOTALL)
    if not match:
        raise ValueError(f"No se ha encontrado <mxlibrary> en {library_path}")

    entries = json.loads(match.group(1))
    processed = 0
    skipped = 0
    for entry in entries:
        title = entry.get("title") or "(sin titulo)"
        data_uri = entry.get("data", "")
        raw = _decode_data_uri(data_uri)
        if raw is None:
            skipped += 1
            continue
        result = process_image_bytes(raw, title)
        entry["data"] = _encode_png_data_uri(result)
        processed += 1

    new_json = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
    updated = text[: match.start(1)] + new_json + text[match.end(1) :]
    library_path.write_text(updated, encoding="utf-8")
    return processed, skipped


def main() -> int:
    library_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LIBRARY
    print(f"Assets: {ASSETS_DIR}")
    asset_count = process_assets()
    print(f"  {asset_count} PNG en assets/")

    print(f"Library: {library_path}")
    processed, skipped = process_library(library_path)
    print(f"  {processed} imagenes procesadas, {skipped} entradas omitidas (URL u otro formato)")
    print("Listo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
