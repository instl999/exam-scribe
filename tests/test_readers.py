"""Reading books without PyMuPDF (pdfplumber / pypdf fallbacks), the `extract` command, and pdftotext output."""
import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import helpers

from examscribe_lib.config import init_workspace
from examscribe_lib.ingest import ingest
from examscribe_lib.inventory import build_inventory


def _summary(ws) -> dict:
    items = ws.all_inventory_items()
    return {"labels": [p["label"] for p in ws.pages], "chapters": [c["id"] for c in ws.outline["chapters"]],
            "terms": sorted(it["text"] for it in items.values() if it["kind"] == "term"),
            "figures": sorted(k for k in items if k.startswith(("FIG-", "TAB-"))),
            "equations": sorted(k for k in items if k.startswith("EQ-")),
            "examples": sorted(k for k in items if k.startswith("WE-"))}


class ReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = helpers.ensure_book()
        cls.tmp = Path(tempfile.mkdtemp(prefix="examscribe-readers-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _read(self, name: str, reader: str | None) -> dict:
        old = os.environ.get("EXAMSCRIBE_PDF_READER")
        os.environ["EXAMSCRIBE_PDF_READER"] = reader or ""
        try:
            ws = init_workspace(self.tmp / name, self.book, "strict", None, "en")
            summary = ingest(ws)
            build_inventory(ws)
            ws.reload()
            self.assertEqual(summary["reader"], reader or "pymupdf")
            return _summary(ws)
        finally:
            if old is None:
                os.environ.pop("EXAMSCRIBE_PDF_READER", None)
            else:
                os.environ["EXAMSCRIBE_PDF_READER"] = old

    @unittest.skipUnless(importlib.util.find_spec("pdfplumber"), "pdfplumber not installed")
    def test_pdfplumber_matches_pymupdf(self):
        self.assertEqual(self._read("ws-plumber", "pdfplumber"), self._read("ws-mupdf", None))

    @unittest.skipUnless(importlib.util.find_spec("pypdf"), "pypdf not installed")
    def test_pypdf_reads_text_labels_and_outline(self):
        base = self._read("ws-mupdf2", None)
        got = self._read("ws-pypdf", "pypdf")
        self.assertEqual(got["labels"], base["labels"])
        self.assertEqual(got["chapters"], base["chapters"])
        self.assertEqual(got["equations"], base["equations"])
        self.assertGreaterEqual(len(got["terms"]), len(base["terms"]) // 2)     # no bold: defining sentences only

    def test_extract_markdown(self):
        from examscribe_lib.extract import extract_markdown
        out = self.tmp / "book.md"
        info = extract_markdown(self.book, out, pages="1-2")
        text = out.read_text(encoding="utf-8")
        self.assertEqual(info["pages"], 2)
        self.assertIn("<!-- page 1 -->", text)
        self.assertIn("<!-- page 2 -->", text)
        self.assertNotIn("<!-- page 3 -->", text)
        self.assertIn("**energy**", text.casefold())          # bold key terms survive
        self.assertIn("# ", text)
        # the Markdown can itself be used as the book
        ws = init_workspace(self.tmp / "ws-md", out, "strict", None, "en")
        ingest(ws)
        ws.reload()
        self.assertEqual([p["label"] for p in ws.pages], ["1", "2"])

    def test_pdftotext_output(self):
        txt = self.tmp / "book.txt"
        txt.write_text("Chapter 1\nEnergy is the capacity to do work.\n\fHeat is the transfer of energy.\n\f\fLast page.\n\f",
                       encoding="utf-8")
        ws = init_workspace(self.tmp / "ws-txt", txt, "strict", None, "en")
        ingest(ws)
        ws.reload()
        self.assertEqual([p["label"] for p in ws.pages], ["1", "2", "3", "4"])     # an empty page keeps its number
        self.assertIn("Heat is the transfer", ws.page_by_label("2")["text"])
        self.assertIn("Last page.", ws.page_by_label("4")["text"])


if __name__ == "__main__":
    unittest.main()
