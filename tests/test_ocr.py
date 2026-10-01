"""Scanned books: probe, page scope, OCR cache/resume, re-extraction from OCR text, pipeline order.

A fake engine (writing known lines) keeps these tests deterministic; one test also runs the real Windows OCR
engine when it is available.
"""
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (sets sys.path)

import pymupdf

from examscribe_lib import ocr as O
from examscribe_lib.config import init_workspace, set_key
from examscribe_lib.ingest import ingest, ocr_cache_path

# (text, line height in points) per page: what the fake engine "reads"
FAKE = [
    [("CHAPTER 1", 12), ("Energy Basics", 30), ("1.1 What Is Energy?", 16),
     ("Energy is the capacity to do work or to supply heat to an object.", 12),
     ("Every change in matter involves some transfer of energy between objects.", 12)],
    [("1.2 Kinetic Energy", 16),
     ("Kinetic energy is the energy that a moving object has because of its motion.", 12),
     ("A heavier object moving at the same speed carries more kinetic energy.", 12)],
    [("CHAPTER 2", 12), ("Heat", 30), ("2.1 Temperature", 16),
     ("Temperature is a measure of the average kinetic energy of the particles in a sample.", 12),
     ("Two samples at the same temperature can hold different amounts of energy.", 12)],
    [("2.2 Heat Flow", 16),
     ("Heat is the transfer of thermal energy between objects at different temperatures.", 12),
     ("Heat always flows from the warmer object to the cooler object on its own.", 12)],
]


def _fake_lines(i: int) -> list[dict]:
    out, y = [], 90.0
    for text, h in FAKE[i]:
        out.append({"text": text, "x0": 72.0, "y0": y, "x1": min(540.0, 72 + 5.2 * len(text)), "y1": y + h})
        y += h + 22
    return out


def fake_runner(ws, doc, todo, engine, deadline, prog):
    done = 0
    for i in todo:
        if done and time.time() >= deadline:      # like the real runners: stop when the budget is used up
            break
        O._save(ws, doc, i, _fake_lines(i), 1.0, 1.0, engine)
        done += 1
        fake_runner.calls.append(i)
        time.sleep(0.02)                  # a page takes time (Windows' clock only moves every ~16 ms)
    return done, []


fake_runner.calls = []
FAKE_ENGINE = O.Engine("windows", "en-US", 1, 200)


def make_scanned_book(path: Path) -> None:
    """Four image-only pages showing the FAKE text (so the real engine has something true to read)."""
    src = pymupdf.open()
    css = "p { font-family: serif; font-size: 11pt; margin: 0 0 8pt 0; } h1 { font-size: 24pt; } h2 { font-size: 14pt; }"
    for page_lines in FAKE:
        html = ""
        for text, h in page_lines:
            tag = "h1" if h >= 30 else "h2" if h == 16 else "p"
            html += f"<{tag}>{text}</{tag}>"
        p = src.new_page(width=612, height=792)
        p.insert_htmlbox(pymupdf.Rect(72, 72, 540, 720), html, css=css)
    out = pymupdf.open()
    for p in src:
        pix = p.get_pixmap(dpi=150, colorspace=pymupdf.csGRAY)
        q = out.new_page(width=612, height=792)
        q.insert_image(q.rect, pixmap=pix)
    out.save(str(path))


class OcrTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="examscribe-ocr-"))
        cls.book = cls.tmp / "scan.pdf"
        make_scanned_book(cls.book)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def new_ws(self, name: str):
        ws = init_workspace(self.tmp / name, self.book, "strict", None, "en")
        ingest(ws)
        ws.reload()
        return ws

    def test_probe(self):
        from examscribe_lib.probe import probe_book, probe_text
        info = probe_book(self.book, engines=False)
        self.assertEqual((info["pages"], info["scanned_pages"], info["need_ocr"], info["text_pages"]), (4, 4, 4, 0))
        self.assertEqual(info["need_ocr_pages"], "1-4")
        self.assertIn("4 pages are images without text", probe_text(info))

    def test_cache_resume_and_reextraction(self):
        ws = self.new_ws("ws_resume")
        self.assertEqual(ws.pages[1]["flags"], ["scanned-no-text"])
        self.assertEqual(O.pages_to_ocr(ws, mode="all"), [0, 1, 2, 3])
        fake_runner.calls = []
        with mock.patch.dict(O.RUNNERS, {"windows": fake_runner}):
            res = O.run_ocr(ws, [0, 1, 2, 3], FAKE_ENGINE, budget=1e-6, say=None)   # budget used up at once
            self.assertEqual((res["read"], res["left"]), (1, 3))
            res = O.run_ocr(ws, [0, 1, 2, 3], FAKE_ENGINE, budget=0, say=None)      # 0 = no limit
            self.assertEqual(res["left"], 0)
        self.assertEqual(sorted(fake_runner.calls), [0, 1, 2, 3])                   # every page read once
        self.assertTrue(all(ocr_cache_path(ws, i).exists() for i in range(4)))
        summary = ingest(ws)
        ws.reload()
        self.assertEqual(summary["ocr_pages"], 4)
        self.assertIn("ocr", ws.pages[1]["flags"])
        self.assertNotIn("scanned-no-text", ws.pages[1]["flags"])
        self.assertIn("Kinetic energy is the energy that a moving object has", ws.pages[1]["text"])
        self.assertEqual(O.pages_to_ocr(ws, mode="all"), [])
        # the outline comes from the OCR'd headings; "CHAPTER 1" above the title is joined to it
        outline = ws.outline
        self.assertEqual([(c["id"], c["title"]) for c in outline["chapters"]], [("ch01", "Energy Basics"), ("ch02", "Heat")])
        self.assertEqual([s["id"] for s in outline["chapters"][0]["sections"]], ["1.1", "1.2"])
        # no bold on OCR pages: key terms come from defining sentences
        from examscribe_lib.inventory import build_inventory
        build_inventory(ws)
        terms = {it["text"] for it in ws.all_inventory_items().values() if it["kind"] == "term"}
        self.assertTrue({"energy", "kinetic energy", "temperature", "heat"} <= terms, terms)

    def test_scope_pages_and_pipeline_order(self):
        from examscribe_lib.pipeline import compute_next
        ws = self.new_ws("ws_pipeline")
        set_key(ws, "scope.pages", "3-4")
        self.assertEqual(ws.config["scope"]["pages"]["ranges"], [[2, 3]])
        self.assertEqual(O.pages_to_ocr(ws), [2, 3])
        slow = O.Engine("windows", "en-US", 1, 200)
        with mock.patch.object(O, "pick_engine", return_value=slow), \
                mock.patch.object(O.Engine, "estimate", return_value=600.0):
            # a slow whole-book OCR waits for the intake, then reads only the exam's pages
            self.assertEqual(compute_next(ws).kind, "intake")
            for k, v in (("exam.formats", "mcq"), ("exam.book_policy", "closed"), ("scope.chapters", "all"),
                         ("study.hours_per_day", "2"), ("subject", "general"), ("intake.done", "true")):
                set_key(ws, k, v)
            t = compute_next(ws)
            self.assertEqual(t.kind, "run-ocr")
            self.assertIn("Read 2 scanned pages", t.goal)
        with mock.patch.object(O, "pick_engine", return_value=None):
            self.assertEqual(compute_next(ws).kind, "need-ocr-engine")
        with mock.patch.dict(O.RUNNERS, {"windows": fake_runner}):
            O.run_ocr(ws, O.pages_to_ocr(ws), FAKE_ENGINE, say=None)
        ingest(ws)
        ws.reload()
        self.assertEqual([c["id"] for c in ws.chapters_in_scope()], ["ch02"])
        self.assertEqual(ws.pages[0]["flags"], ["scanned-no-text"])      # outside the scope: never read
        self.assertEqual(compute_next(ws).kind, "confirm-outline")      # guessed chapters need the user's OK
        from examscribe_lib.outline_edit import confirm_outline
        confirm_outline(ws)
        self.assertNotIn(compute_next(ws).kind, ("run-ocr", "confirm-outline", "need-ocr-engine"))

    def test_rapidocr_result_shapes(self):
        box = [[10, 20], [110, 20], [110, 34], [10, 34]]
        old_style = ([[box, "Energy is the capacity", 0.98]], [0.1, 0.2, 0.3])     # rapidocr_onnxruntime
        new_style = type("Out", (), {"boxes": [box], "txts": ("Energy is the capacity",), "scores": (0.98,)})()
        for result in (old_style, new_style):
            self.assertEqual(O._rapid_lines(result), [{"text": "Energy is the capacity", "x0": 10.0, "y0": 20.0,
                                                       "x1": 110.0, "y1": 34.0}])
        self.assertEqual(O._rapid_lines((None, None)), [])

    def test_language_tags(self):
        tags = ["en-US", "zh-Hans-CN", "de-DE"]
        self.assertEqual(O._win_tag("en", tags), "en-US")
        self.assertEqual(O._win_tag("zh", tags), "zh-Hans-CN")
        self.assertIsNone(O._win_tag("zh-tw", tags))            # never Simplified for a Traditional book
        self.assertIsNone(O._win_tag("zh-hant", tags))
        self.assertEqual(O._win_tag("zh-hant", tags + ["zh-Hant-TW"]), "zh-Hant-TW")
        self.assertEqual(O._tess_lang("zh", ["chi_sim", "eng"]), "chi_sim+eng")
        self.assertIsNone(O._tess_lang("zh-hant", ["chi_sim", "eng"]))
        self.assertIsNone(O._tess_lang("fr", ["eng"]))

    @unittest.skipUnless(O.pick_engine(None, "en", preferred="windows") is not None, "Windows OCR not available")
    def test_windows_engine_reads_scans(self):
        ws = self.new_ws("ws_windows")
        eng = O.pick_engine(ws, preferred="windows")
        res = O.run_ocr(ws, [0, 1, 2, 3], eng, say=None)
        self.assertEqual(res["left"], 0, res["problems"])
        ingest(ws)
        ws.reload()
        text = " ".join(p["text"] for p in ws.pages)
        for phrase in ("capacity to do work", "because of its motion", "average kinetic energy",
                       "transfer of thermal energy"):
            self.assertIn(phrase, text)
        self.assertEqual([c["title"] for c in ws.outline["chapters"]], ["Energy Basics", "Heat"])


if __name__ == "__main__":
    unittest.main()
