"""Remove background from device PNG assets using rembg."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from remove_library_backgrounds import process_assets

if __name__ == "__main__":
    assets_dir = Path(__file__).resolve().parents[1] / "assets"
    print(f"Assets folder: {assets_dir}")
    count = process_assets()
    print(f"\n{count} images processed.")
