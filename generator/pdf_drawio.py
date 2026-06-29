"""Extract the draw.io diagram embedded inside a PDF exported from draw.io.

draw.io's "Export as PDF" with *Include a copy of my diagram* embeds the
original mxfile inside the PDF (as an attachment and/or inside a content
stream). This lets us accept those PDFs on the upload form and publish the
real, editable diagram to GLPI instead of a flat image — transparently for
whoever uploads it.

We only ever pull out the existing ``<mxfile>`` payload; there is no lossy
raster-to-vector conversion involved.
"""

from __future__ import annotations

import base64
import io
import re
import zlib
from urllib.parse import unquote

# The diagram may appear verbatim, URL-encoded ("%3Cmxfile") or base64-wrapped.
_MXFILE_RE = re.compile(rb"<mxfile\b[\s\S]*?</mxfile>", re.IGNORECASE)
_MXGRAPH_RE = re.compile(rb"<mxGraphModel\b[\s\S]*?</mxGraphModel>", re.IGNORECASE)
_MXFILE_ENCODED_RE = re.compile(rb"%3[Cc]mxfile\b[\s\S]*?%3[Cc]/mxfile%3[Ee]")
_BASE64_MXFILE_RE = re.compile(rb"PG14ZmlsZ[0-9A-Za-z+/=]+")  # b64 of "<mxfile"

# Bound decompression so a malicious PDF cannot inflate to gigabytes (zip-bomb).
_MAX_INFLATE = 64 * 1024 * 1024  # 64 MB per stream


class PdfDrawioError(ValueError):
    """Raised when a PDF does not contain an embedded draw.io diagram."""


def _wrap_graph_model(graph_xml: str) -> str:
    return f'<mxfile><diagram name="Page-1">{graph_xml}</diagram></mxfile>'


def _search_mxfile(blob: bytes) -> str | None:
    if not blob:
        return None
    match = _MXFILE_RE.search(blob)
    if match:
        return match.group(0).decode("utf-8", "ignore")
    encoded = _MXFILE_ENCODED_RE.search(blob)
    if encoded:
        decoded = unquote(encoded.group(0).decode("latin-1"))
        if "<mxfile" in decoded:
            return decoded
    b64 = _BASE64_MXFILE_RE.search(blob)
    if b64:
        try:
            raw = base64.b64decode(b64.group(0), validate=False)
        except (ValueError, base64.binascii.Error):
            raw = b""
        found = _MXFILE_RE.search(raw)
        if found:
            return found.group(0).decode("utf-8", "ignore")
    graph = _MXGRAPH_RE.search(blob)
    if graph:
        return _wrap_graph_model(graph.group(0).decode("utf-8", "ignore"))
    return None


def _bounded_inflate(data: bytes) -> bytes:
    try:
        return zlib.decompressobj().decompress(bytes(data), _MAX_INFLATE)
    except zlib.error:
        return b""


def _from_attachments(raw: bytes) -> str | None:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        reader = PdfReader(io.BytesIO(raw))
        attachments = getattr(reader, "attachments", {}) or {}
    except Exception:
        return None
    for contents in attachments.values():
        items = contents if isinstance(contents, list) else [contents]
        for item in items:
            data = bytes(item) if not isinstance(item, (bytes, bytearray)) else bytes(item)
            found = _search_mxfile(data)
            if found:
                return found
    return None


def _from_pdf_objects(raw: bytes) -> str | None:
    """Walk every indirect object; decode streams and scan metadata/XMP."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        reader = PdfReader(io.BytesIO(raw))
    except Exception:
        return None

    # Document info + XMP metadata (draw.io sometimes stores it there).
    try:
        info = reader.metadata
        if info:
            for value in info.values():
                found = _search_mxfile(str(value).encode("utf-8", "ignore"))
                if found:
                    return found
    except Exception:
        pass
    try:
        xmp = reader.xmp_metadata
        if xmp is not None and getattr(xmp, "stream", None) is not None:
            found = _search_mxfile(xmp.stream.get_data())
            if found:
                return found
    except Exception:
        pass

    # Every indirect object: decode stream data when present.
    try:
        num_objects = len(reader.xref.get(0, {})) if reader.xref else 0  # noqa: F841
    except Exception:
        pass
    seen = set()
    try:
        candidates = list(reader._objects)
    except Exception:
        candidates = []
    for obj in candidates:
        if obj is None or id(obj) in seen:
            continue
        seen.add(id(obj))
        get_data = getattr(obj, "get_data", None)
        if callable(get_data):
            try:
                data = get_data()
            except Exception:
                data = b""
            found = _search_mxfile(data if isinstance(data, bytes) else bytes(data or b""))
            if found:
                return found
    return None


def _from_streams(raw: bytes) -> str | None:
    """Last resort: scan raw bytes and bounded-inflate embedded zlib streams."""
    found = _search_mxfile(raw)
    if found:
        return found
    scanned = 0
    for match in re.finditer(rb"\x78[\x01\x5e\x9c\xda]", raw):
        scanned += 1
        if scanned > 256:  # avoid O(n^2) on pathological inputs
            break
        inflated = _bounded_inflate(raw[match.start():])
        found = _search_mxfile(inflated)
        if found:
            return found
    return None


def extract_drawio_from_pdf(raw: bytes) -> str:
    """Return the embedded mxfile XML, or raise PdfDrawioError if absent."""
    for strategy in (_from_attachments, _from_pdf_objects, _from_streams):
        result = strategy(raw)
        if result:
            return result
    raise PdfDrawioError(
        "El PDF no contiene un diagrama de draw.io editable. "
        "Vuelve a exportarlo marcando «Incluir una copia del diagrama» o sube el .drawio original."
    )
