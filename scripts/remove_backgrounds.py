"""Remove background from all device PNG assets using rembg."""
from __future__ import annotations

from pathlib import Path

from rembg import remove
from PIL import Image
import io

ASSETS = Path(__file__).resolve().parents[1] / "assets"

DEVICE_IMAGES = [
    "yealink_t30.png",
    "yealink_t33g.png",
    "yealink_t43u.png",
    "yealink_t44u.png",
    "yealink_t73w.png",
    "yealink_w70b.png",
    "tplink_8p.png",
    "mikrotik_wap_lte.png",
    "teltonika.png",
    "mikrotik_hap_ac3.png",
]

# w71h.png is already stored separately — include it too
EXTRA = ["w71h.png"]


def process(path: Path) -> None:
    if not path.exists():
        print(f"  SKIP (not found): {path.name}")
        return
    print(f"  Processing: {path.name} ...", end=" ", flush=True)
    data = path.read_bytes()
    result = remove(data)
    path.write_bytes(result)
    print("done")


if __name__ == "__main__":
    print(f"Assets folder: {ASSETS}")
    for name in DEVICE_IMAGES + EXTRA:
        process(ASSETS / name)
    print("\nAll done.")
