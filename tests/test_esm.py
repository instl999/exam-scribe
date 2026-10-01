import unittest

import helpers  # noqa: F401
from examscribe_lib.esm import autofix, citations, covers, parse, strip_citations


class ParseTests(unittest.TestCase):
    def test_blocks_and_fields(self):
        doc = parse("# Title\n\n::: concept T-x\nterm: X\nplain: text [p.3: \"some words here now\"]\n:::\n")
        self.assertEqual(len(doc.blocks), 1)
        b = doc.blocks[0]
        self.assertEqual((b.kind, b.id), ("concept", "T-x"))
        self.assertEqual(b.value("term"), "X")
        self.assertFalse([i for i in doc.issues if i.level == "error"])

    def test_stray_text_and_unclosed(self):
        doc = parse("hello there\n::: concept T-x\nterm: X\n")
        codes = {i.code for i in doc.issues}
        self.assertIn("stray-text", codes)
        self.assertIn("unclosed", codes)

    def test_continuation_joined(self):
        doc = parse("::: concept T-x\nplain: first part\n  second part\n:::\n")
        self.assertEqual(doc.blocks[0].value("plain"), "first part second part")

    def test_fenced_code(self):
        doc = parse("::: trace TR-1\nask: What prints?\n```python\nprint(1)\n```\noutput: 1\n:::\n")
        self.assertEqual(doc.blocks[0].code.strip(), "print(1)")
        self.assertEqual(doc.blocks[0].value("output"), "1")

    def test_key_normalization(self):
        doc = parse("::: question Q-1\nOption A: yes\nwhy not b: no\n:::\n")
        self.assertIsNotNone(doc.blocks[0].get("option a"))
        self.assertIsNotNone(doc.blocks[0].get("why-not b"))


class CitationTests(unittest.TestCase):
    def test_citations_and_strip(self):
        v = 'Claim text. [p.12: "exact words from book"] [p.iv: "more words here too"] (covers: SUM-1, SUM-2)'
        cs = citations(v)
        self.assertEqual([c.page for c in cs], ["12", "iv"])
        self.assertEqual(strip_citations(v), "Claim text.")
        self.assertEqual(covers(v), ["SUM-1", "SUM-2"])


class AutofixTests(unittest.TestCase):
    def test_fixes(self):
        text = ("::: question Q-1\nOption A: x ✅\nWhy: text [p 12: “four words right here”]\n"
                "answer: A\n:::\n::: must-know ch01\n- a point [p.1: \"four words right here\"]\n:::\n")
        fixed, notes = autofix(text)
        self.assertIn("option A: x", fixed)
        self.assertNotIn("✅", fixed)
        self.assertIn('why: text [p.12: "four words right here"]', fixed)
        self.assertIn("point: a point", fixed)
        self.assertTrue(notes)

    def test_autofix_is_idempotent(self):
        text = '::: concept T-x\nterm: X\nplain: t [p.1: "four words right here"]\n:::\n'
        once, _ = autofix(text)
        twice, notes = autofix(once)
        self.assertEqual(once, twice)
        self.assertEqual(notes, [])


if __name__ == "__main__":
    unittest.main()
