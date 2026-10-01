"""Text PDFs in other languages: extraction without OCR, outline, end-of-chapter parts, figures, examples,
key terms (bold or defining sentences), exercises, sentence splitting, quotes; broken text layers are detected."""
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401  (sets sys.path)

import lang_books
from examscribe_lib.citations import QuoteIndex
from examscribe_lib.common import split_sentences
from examscribe_lib.config import init_workspace
from examscribe_lib.ingest import ingest
from examscribe_lib.inventory import build_inventory
from examscribe_lib.probe import probe_book

READABLE = ["zh", "ja", "ko", "ru", "de", "fr", "es"]
BROKEN = ["ar", "hi"]          # PyMuPDF's HTML writer produces wrong glyph mappings for these scripts


class LanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="examscribe-lang-"))
        cls.ws, cls.truth = {}, {}
        for lang in READABLE + BROKEN:
            book = cls.tmp / f"book-{lang}.pdf"
            cls.truth[lang] = lang_books.build(book, lang)
            ws = init_workspace(cls.tmp / f"ws-{lang}", book, "strict", None, lang)
            ingest(ws)
            build_inventory(ws)
            ws.reload()
            cls.ws[lang] = ws

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_text_pdfs_need_no_ocr(self):
        for lang in READABLE:
            info = probe_book(self.tmp / f"book-{lang}.pdf", lang, engines=False)
            self.assertEqual(info["need_ocr"], 0, lang)
            self.assertEqual(info["lang_guess"], lang, lang)

    def test_definitions_extracted_verbatim(self):
        for lang in READABLE:
            text = re.sub(r"\s+", " ", "\n".join(p["text"] for p in self.ws[lang].pages))
            for pair in lang_books.LANGS[lang]["defs"]:
                for _, sentence in pair:
                    self.assertIn(sentence, text, f"{lang}: {sentence[:20]}")
        zh = "\n".join(p["text"] for p in self.ws["zh"].pages)
        filler = lang_books.LANGS["zh"]["filler"][1]         # wraps across a line in the PDF
        self.assertIn(filler, zh, "a line break inside Chinese text became a space")

    def test_structure(self):
        for lang in READABLE:
            ws = self.ws[lang]
            kinds = {s["id"]: s["kind"] for c in ws.outline["chapters"] for s in c["sections"]}
            self.assertEqual([k for k, v in kinds.items() if v == "content"], ["1.1", "1.2", "2.1", "2.2"], lang)
            self.assertEqual(sum(1 for v in kinds.values() if v == "end"), 6, lang)
            items = ws.all_inventory_items()
            for want in ("FIG-1.1", "FIG-2.1", "EQ-1.1", "EQ-2.1", "WE-1.1", "WE-2.1"):
                self.assertIn(want, items, f"{lang}: {want}")
            self.assertEqual(sum(1 for k in items if k.startswith("SUM-")), 4, lang)
            self.assertEqual(sum(len(ws.inventory(c["id"])["exercises"]) for c in ws.outline["chapters"]), 4, lang)

    def test_key_terms(self):
        for lang in READABLE:
            items = self.ws[lang].all_inventory_items().values()
            found = {it["text"].casefold() for it in items if it["kind"] == "term"}
            for t in [t for c in self.truth[lang]["terms"].values() for t in c]:
                self.assertIn(t.casefold(), found, f"{lang}: {t}")

    def test_sentences_and_quotes(self):
        for lang in READABLE:
            L = lang_books.LANGS[lang]
            sep = "" if lang in ("zh", "ja") else " "
            self.assertEqual(len(split_sentences(L["filler"][0] + sep + L["filler"][1])), 2, lang)
            ws = self.ws[lang]
            qi = QuoteIndex(ws)
            sentence = L["defs"][2][0][1]
            page = next(p["label"] for p in ws.pages if sentence in re.sub(r"\s+", " ", p["text"]))
            self.assertEqual(qi.check(page, sentence).status, "exact", lang)

    def test_notes_pass_lint_and_worksheets_plant_false_claims(self):
        """Beyond extraction: a section written from the book passes the linter, and the checker's worksheet
        contains the tier's number of planted false claims, made in the notes' language."""
        import hashlib
        from examscribe_lib import verify as V
        from examscribe_lib.config import set_key
        from examscribe_lib.pipeline import check, compute_next
        from examscribe_lib.tiers import tier_params
        for lang in ("de", "zh", "fr", "ko"):
            ws = init_workspace(self.tmp / f"notes-{lang}", self.tmp / f"book-{lang}.pdf", "strict", None, lang)
            ingest(ws)
            ws.reload()
            for k, v in (("exam.formats", "mcq,short-answer"), ("exam.book_policy", "closed"),
                         ("scope.chapters", "ch01"), ("study.hours_per_day", "2"), ("subject", "chemistry"),
                         ("intake.done", "true")):
                set_key(ws, k, v)
            ws.state["plan_confirmed"] = True
            ws.save_state()
            task = compute_next(ws)
            self.assertEqual(task.kind, "write-section", lang)
            term_of = {s: t for pair in lang_books.LANGS[lang]["defs"] for t, s in pair}
            helpers.oracle_write_section(task.edit, lang, term_of)
            res = check(ws)
            self.assertTrue(res.ok, f"{lang}: {res.text[:1500]}")
            names = V.make_claim_batches(ws, "ch01", tier_params("strict"))
            keys = json.loads((ws.verify_dir("ch01") / ".keys.json").read_text(encoding="utf-8"))
            for name in names:
                k = keys[name]
                self.assertGreaterEqual(len(k["canary"]), tier_params("strict")["canaries_per_batch"], lang)
                originals = json.loads((ws.verify_dir("ch01") / f"{name}.json").read_text(encoding="utf-8"))["originals"]
                h = lambda bid: hashlib.sha256((k["salt"] + bid).encode()).hexdigest()[:16]
                planted = [o["claim"] for bid, o in originals.items() if h(bid) in k["canary"]]
                self.assertTrue(planted, lang)

    def test_bookmarks_and_labels_from_scanning_tools(self):
        from examscribe_lib.ingest import _cjk_section, _levels_from_titles, build_outline, toc_has_titles
        # one bookmark per page, titled with the page number (Pdg2Pic / FreePic2Pdf scans): no structure
        junk = [[1, "书名", 1], [1, "版权", 2], [1, "前言", 3], [1, "目录", 11]] + [[1, str(i), i + 17] for i in range(1, 40)]
        self.assertFalse(toc_has_titles(junk))
        self.assertTrue(toc_has_titles([[1, "第一章 传播学的对象", 18], [1, "第一节 定义", 18]]))
        outline = build_outline(junk, [[] for _ in range(60)], [str(i) for i in range(60)], 60)
        self.assertEqual(outline["method"], "fallback")
        # a flat list with real titles: chapters by their numbering, the rest become their sections
        flat = [{"level": 1, "title": t, "page": p} for t, p in
                (("前言", 0), ("第一章 传播学的对象", 2), ("第一节 传播的定义", 2), ("第二节 传播学", 5),
                 ("第二章 人类传播的历史", 9), ("第一节 动物传播", 9))]
        self.assertEqual([e["level"] for e in _levels_from_titles(flat)], [1, 1, 2, 2, 1, 2])
        self.assertEqual(_cjk_section("第三节 精神交往理论"), ("3", "精神交往理论"))
        self.assertEqual(_cjk_section("第十二节"), ("12", ""))
        self.assertIsNone(_cjk_section("第三章 符号"))

    def test_label_lookup_with_case_clash(self):
        ws = self.ws["de"]
        pages = ws.pages
        saved = [p["label"] for p in pages]
        try:
            pages[0]["label"], pages[1]["label"] = "I", "i"      # a cover page "I" and a roman front-matter "i"
            ws._label_index = None
            self.assertEqual(ws.page_by_label("I")["index"], 0)
            self.assertEqual(ws.page_by_label("i")["index"], 1)
            self.assertEqual(ws.page_by_label(saved[2].upper() if saved[2].isalpha() else saved[2])["index"], 2)
        finally:
            for p, label in zip(pages, saved):
                p["label"] = label
            ws._label_index = None

    def test_broken_text_layers_are_flagged(self):
        for lang in BROKEN:
            info = probe_book(self.tmp / f"book-{lang}.pdf", lang, engines=False)
            self.assertGreater(info["need_ocr"], 0, lang)
            flags = {f for p in self.ws[lang].pages for f in p["flags"]}
            self.assertIn("garbled", flags, lang)


if __name__ == "__main__":
    unittest.main()
