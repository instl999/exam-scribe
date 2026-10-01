import unittest

import helpers


class IngestInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ws = helpers.new_workspace()
        cls.truth = helpers.truth()

    @classmethod
    def tearDownClass(cls):
        helpers.cleanup(cls.ws)

    def test_page_labels(self):
        labels = [p["label"] for p in self.ws.pages]
        self.assertEqual(labels[:4], ["i", "ii", "iii", "1"])
        self.assertEqual(len(labels), self.truth["page_count"])

    def test_headers_and_page_numbers_removed(self):
        text = self.ws.page_by_label("2")["text"]
        self.assertNotIn("Chapter 1 | Energy and Its Units", text)

    def test_ligatures_and_hyphenation(self):
        p7 = self.ws.page_by_label("7")["text"]
        self.assertIn("until the temperature of the block", p7)
        self.assertNotIn("ﬁ", "".join(p["text"] for p in self.ws.pages))

    def test_subscripts_marked(self):
        self.assertIn("ΔH = q_p (2.3)", self.ws.page_by_label("11")["text"])

    def test_outline(self):
        chapters = self.ws.outline["chapters"]
        self.assertEqual([c["id"] for c in chapters], ["ch01", "ch02"])
        content = [s["id"] for s in chapters[1]["sections"] if s["kind"] == "content"]
        self.assertEqual(content, self.truth["chapters"]["ch02"]["sections"])
        ends = [s["title"] for s in chapters[0]["sections"] if s["kind"] == "end"]
        self.assertIn("Key Terms", ends)
        self.assertIn("Answer Key", [o["title"] for o in self.ws.outline["other"]])

    def test_quality_flags(self):
        flags = {p["label"]: p["flags"] for p in self.ws.pages}
        self.assertIn("scanned-no-text", flags["16"])
        self.assertEqual(flags["1"], [])

    def test_figures(self):
        from examscribe_lib.common import read_json
        from examscribe_lib.media import ensure_chapter_media
        figs = {f["id"]: f for f in read_json(self.ws.source_dir / "figures.json")}
        for want in ("FIG-1.1", "FIG-2.1", "FIG-2.2", "TAB-2.1"):
            self.assertIn(want, figs)
            self.assertTrue(figs[want]["crop"])
        # pictures are made per chapter, only when a chapter is worked on
        ensure_chapter_media(self.ws, self.ws.chapter("ch02"))
        figs = {f["id"]: f for f in read_json(self.ws.source_dir / "figures.json")}
        for want in ("FIG-2.1", "FIG-2.2", "TAB-2.1"):
            self.assertTrue((self.ws.root / figs[want]["image"]).exists())
        items = self.ws.inventory("ch02")["items"]
        eqs = [it for it in items if it["kind"] == "equation" and it.get("bbox")]
        self.assertTrue(eqs and all((self.ws.root / it["image"]).exists() for it in eqs))
        self.assertTrue(all(it.get("image") for it in items if it["kind"] in ("figure", "table")))

    def test_two_column_page_order(self):
        import pymupdf
        from examscribe_lib.ingest import _extract_pdf_page
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        css = "p { font-family: serif; font-size: 10pt; line-height: 1.3; }"
        left = " ".join(f"Left column sentence {i} talks about energy and heat in a closed system." for i in range(12))
        right = " ".join(f"Right column sentence {i} explains enthalpy and pressure-volume work." for i in range(12))
        page.insert_htmlbox(pymupdf.Rect(54, 72, 296, 720), f"<p>{left}</p>", css=css)
        page.insert_htmlbox(pymupdf.Rect(316, 72, 558, 720), f"<p>{right}</p>", css=css)
        pe = _extract_pdf_page(page)
        self.assertTrue(pe.two_column)
        texts = [l["text"] for l in pe.lines]
        first_right = next(i for i, t in enumerate(texts) if "Right" in t)
        self.assertTrue(all("Right" not in t for t in texts[:first_right]))
        self.assertTrue(all("Left" not in t for t in texts[first_right:]))

    def test_fast_key_matches_indexed_key(self):
        from examscribe_lib.common import build_key, key_of
        samples = [p["text"] for p in self.ws.pages] + [
            "Speciﬁc heat", "−890 kJ", "4 .5 and 4. 5", "2-kg ball", "x - 5", "½mv²", "été",
            "ＡＢＣ 　full", "Ω ohm Å", "café ß STRASSE", "温度是分子",
            "H₂O and x³", "_under_score_", "3.14.15", "-5 -x 5-", "µm and μm", "ﬃ ﬄ"]
        for t in samples:
            self.assertEqual(key_of(t), build_key(t)[0], repr(t[:60]))

    def test_inventory_terms(self):
        for ch, terms in self.truth["terms"].items():
            inv = self.ws.inventory(ch)
            found = {it["text"] for it in inv["items"] if it["kind"] == "term"}
            for t in terms:
                self.assertIn(t, found, f"{ch}: term {t!r} not found")

    def test_inventory_contexts(self):
        items = self.ws.all_inventory_items()
        self.assertTrue(items["T-energy"]["context"].startswith("Energy is the capacity"))
        self.assertTrue(items["T-heat"]["context"].startswith("Heat (q) is the transfer"))
        self.assertTrue(items["T-law-of-conservation-of-energy"]["signals"]["boxed"])

    def test_inventory_other_items(self):
        items = self.ws.all_inventory_items()
        for eq in self.truth["equations"]:
            self.assertIn("EQ-" + eq["number"], items)
        for ex in self.truth["examples"]:
            self.assertIn("WE-" + ex["number"], items)
        los = [i for i in items.values() if i["kind"] == "objective"]
        self.assertEqual(len(los), sum(len(v) for v in self.truth["objectives"].values()))
        inv2 = self.ws.inventory("ch02")
        self.assertEqual(inv2["exercise_counts"], {"2.1": 2, "2.2": 2, "2.3": 1})
        self.assertEqual(len([i for i in inv2["items"] if i["kind"] == "summary"]), 8)
        self.assertEqual([d["chapter"] for d in inv2["depends_on"]], ["ch01"])


MARKDOWN_BOOK = """{0}------------------------------------------------

# Chapter 1 Motion

## 1.1 Speed

**Speed** is the distance traveled per unit of time. The average speed is the total distance divided by the total time:

$$v = d / t \\quad (1.1)$$

A car that travels 100 km in 2 h has an average speed of 50 km/h.

{1}------------------------------------------------

## 1.2 Acceleration

**Acceleration** is the rate at which velocity changes.

## Summary

Speed is distance per unit time. Acceleration is the rate of change of velocity.

{2}------------------------------------------------

# Chapter 2 Forces

## 2.1 Inertia

**Inertia** is the tendency of an object to resist changes in its motion.
"""


class MarkdownInputTests(unittest.TestCase):
    """Markdown with Marker-style page markers: the route for math-heavy books converted by Marker/MinerU."""

    def test_markdown_book(self):
        import tempfile
        from pathlib import Path
        from examscribe_lib.config import init_workspace
        from examscribe_lib.ingest import ingest
        from examscribe_lib.inventory import build_inventory
        tmp = Path(tempfile.mkdtemp(prefix="examscribe-md-"))
        try:
            book = tmp / "book.md"
            book.write_text(MARKDOWN_BOOK, encoding="utf-8")
            ws = init_workspace(tmp / "ws", book, "strict", None, "en")
            summary = ingest(ws)
            self.assertEqual(summary["pages"], 3)
            self.assertEqual([c["id"] for c in summary["chapters"]], ["ch01", "ch02"])
            self.assertEqual([p["label"] for p in ws.pages], ["1", "2", "3"])
            build_inventory(ws)
            items = ws.all_inventory_items()
            self.assertEqual(items["EQ-1.1"]["text"], "v = d / t")
            self.assertEqual(items["T-acceleration"]["page"], "2")
            self.assertIn("T-inertia", items)
            self.assertIn("A car that travels", ws.page_by_label("1")["text"].split("\n\n")[-1])
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
