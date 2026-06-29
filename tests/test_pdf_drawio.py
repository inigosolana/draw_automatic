import io
import unittest

from generator.pdf_drawio import PdfDrawioError, extract_drawio_from_pdf

try:
    from pypdf import PdfWriter

    HAS_PYPDF = True
except ImportError:  # pragma: no cover - exercised only without the dependency
    HAS_PYPDF = False

MXFILE = '<mxfile host="app"><diagram name="P1">payload-123</diagram></mxfile>'


@unittest.skipUnless(HAS_PYPDF, "pypdf no instalado")
class PdfDrawioExtractionTests(unittest.TestCase):
    def _pdf_with_attachment(self, name: str, content: bytes) -> bytes:
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.add_attachment(name, content)
        buffer = io.BytesIO()
        writer.write(buffer)
        return buffer.getvalue()

    def test_extracts_mxfile_from_drawio_attachment(self) -> None:
        pdf = self._pdf_with_attachment("cumcum_sede1.drawio", MXFILE.encode("utf-8"))
        self.assertEqual(extract_drawio_from_pdf(pdf), MXFILE)

    def test_raises_when_pdf_has_no_diagram(self) -> None:
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        buffer = io.BytesIO()
        writer.write(buffer)
        with self.assertRaises(PdfDrawioError):
            extract_drawio_from_pdf(buffer.getvalue())


class PdfDrawioRawScanTests(unittest.TestCase):
    def test_finds_mxfile_in_raw_bytes(self) -> None:
        blob = b"%PDF-1.7 ... garbage ..." + MXFILE.encode("utf-8") + b" ... trailer"
        self.assertEqual(extract_drawio_from_pdf(blob), MXFILE)

    def test_non_pdf_without_diagram_raises(self) -> None:
        with self.assertRaises(PdfDrawioError):
            extract_drawio_from_pdf(b"just some bytes, no diagram here")


if __name__ == "__main__":
    unittest.main()
