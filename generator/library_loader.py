from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .aliases import normalize_name, resolve_alias


@dataclass
class LibraryItem:
    title: str
    data: str
    width: int
    height: int
    aspect: str = "fixed"


class LibraryIndex:
    def __init__(self, items: list[LibraryItem]) -> None:
        self.items = items
        self.by_title = {item.title: item for item in items}
        self.by_normalized = {normalize_name(item.title): item for item in items}

    def find(self, name: str) -> LibraryItem | None:
        alias = resolve_alias(name)
        if alias in self.by_title:
            return self.by_title[alias]
        return self.by_normalized.get(normalize_name(alias))


def load_library(path: str | Path) -> LibraryIndex:
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"<mxlibrary>(.*)</mxlibrary>", text, re.DOTALL)
    if not match:
        raise ValueError("No se ha encontrado <mxlibrary> en la libreria.")
    entries = json.loads(match.group(1))
    items: list[LibraryItem] = []
    for entry in entries:
        title = entry.get("title")
        data = entry.get("data")
        if not title or not data:
            continue
        items.append(
            LibraryItem(
                title=title,
                data=data,
                width=int(entry.get("w", 120)),
                height=int(entry.get("h", 120)),
                aspect=entry.get("aspect", "fixed"),
            )
        )
    return LibraryIndex(items)
