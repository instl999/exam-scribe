"""Scanned books in every fixture language: the text an OCR engine returns (lines with boxes, no fonts, no bold)
must still give the chapters, sections, end parts, verbatim definitions and key terms.

The "OCR" here is perfect (the lines of the text version of the same book), so the tests check ExamScribe's
handling of OCR text, not an engine's accuracy. One test also runs real Tesseract when its data is installed.
"""
import shutil
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401  (sets sys.path)

import pymupdf

import lang_books
from examscribe_lib import ocr as O
from examscribe_lib.common import write_json
from examscribe_lib.config import init_workspace
from examscribe_lib.ingest import ingest, ocr_cache_path
from examscribe_lib.inventory import build_inventory

LANGS = ["zh", "ja", "ko", "ru", "de", "fr", "es"]


def scanned_copy(text_pdf: Path, out: Path, dpi: int = 100) -> None:
    src = pymupdf.open(text_pdf)
    dst = pymupdf.open()
    for p in src:
        q = dst.new_page(width=p.rect.width, height=p.rect.height)
        q.insert_image(q.rect, pixmap=p.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY))
    dst.save(str(out))


def perfect_ocr(ws, text_pdf: Path) -> None:
    """Write the OCR cache as an engine would: one entry per visual line, text and box only."""
    doc = pymupdf.open(text_pdf)
    for page in doc:
        lines = []
        for b in page.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                text = "".join(s["text"] for s in ln["spans"]).strip()
                if text:
                    x0, y0, x1, y1 = ln["bbox"]
                    lines.append({"text": text, "x0": x0, "y0": y0, "x1": x1, "y1": y1})
        write_json(ocr_cache_path(ws, page.number), {"engine": "fake", "lang": "", "dpi": 200,
                                                     "width": round(page.rect.width, 1),
                                                     "height": round(page.rect.height, 1), "angle": 0, "lines": lines})


class ScannedLanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="examscribe-scanlang-"))
        cls.ws, cls.truth = {}, {}
        for lang in LANGS:
            text_pdf = cls.tmp / f"text-{lang}.pdf"
            cls.truth[lang] = lang_books.build(text_pdf, lang)
            scan = cls.tmp / f"scan-{lang}.pdf"
            scanned_copy(text_pdf, scan)
            ws = init_workspace(cls.tmp / f"ws-{lang}", scan, "strict", None, lang)
            ingest(ws)
            perfect_ocr(ws, text_pdf)
            ingest(ws)
            build_inventory(ws)
            ws.reload()
            cls.ws[lang] = ws

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_outline_from_ocr_text(self):
        for lang in LANGS:
            ws = self.ws[lang]
            self.assertEqual(ws.outline["method"], "headings", lang)
            chapters = ws.outline["chapters"]
            self.assertEqual([c["id"] for c in chapters], ["ch01", "ch02"], lang)
            for c, title in zip(chapters, lang_books.LANGS[lang]["chapters"]):
                self.assertEqual(c["title"], title, lang)
            kinds = [(s["id"], s["kind"]) for c in chapters for s in c["sections"]]
            self.assertEqual([k for k, v in kinds if v == "content"], ["1.1", "1.2", "2.1", "2.2"], lang)
            self.assertEqual(sum(1 for _, v in kinds if v == "end"), 6, lang)
            self.assertEqual(ws.outline["label_method"], "printed-page-numbers", lang)

    def test_definitions_verbatim_and_terms(self):
        for lang in LANGS:
            ws = self.ws[lang]
            text = "".join(p["text"].replace("\n", "") for p in ws.pages)
            flat = text.replace(" ", "")
            for pair in lang_books.LANGS[lang]["defs"]:
                for _, sentence in pair:
                    self.assertIn(sentence.replace(" ", ""), flat, f"{lang}: {sentence[:20]}")
            items = ws.all_inventory_items().values()
            found = {it["text"].casefold() for it in items if it["kind"] == "term"}
            want = [t.casefold() for c in self.truth[lang]["terms"].values() for t in c]
            missing = [t for t in want if t not in found]
            self.assertLessEqual(len(missing), 1, f"{lang}: missing {missing}, found {sorted(found)}")
            junk = [t for t in found if t not in want]
            self.assertEqual(junk, [], f"{lang}: unexpected terms")


class RealTesseractTests(unittest.TestCase):
    @unittest.skipUnless(O.pick_engine(None, "fr", preferred="tesseract") is not None, "Tesseract French data missing")
    def test_french_scan_with_tesseract(self):
        tmp = Path(tempfile.mkdtemp(prefix="examscribe-tess-"))
        try:
            text_pdf = tmp / "text.pdf"
            truth = lang_books.build(text_pdf, "fr")
            scanned_copy(text_pdf, tmp / "scan.pdf", dpi=200)
            ws = init_workspace(tmp / "ws", tmp / "scan.pdf", "strict", None, "fr")
            ingest(ws)
            ws.reload()
            eng = O.pick_engine(ws, preferred="tesseract")
            eng.workers = 1
            res = O.run_ocr(ws, list(range(len(ws.pages))), eng, say=None)
            self.assertEqual(res["left"], 0, res["problems"])
            ingest(ws)
            build_inventory(ws)
            ws.reload()
            text = " ".join(p["text"] for p in ws.pages)
            for pair in lang_books.LANGS["fr"]["defs"]:
                for _, sentence in pair:
                    self.assertIn(sentence, text)
            self.assertEqual(len(ws.outline["chapters"]), 2)
            terms = {it["text"] for it in ws.all_inventory_items().values() if it["kind"] == "term"}
            self.assertGreaterEqual(len(terms & {t for c in truth["terms"].values() for t in c}), 7, terms)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
