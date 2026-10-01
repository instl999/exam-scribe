"""The linter must pass good drafts and catch the typical mistakes of weaker models."""
import re
import unittest

import helpers
from examscribe_lib.common import read_text
from examscribe_lib.esm import autofix, parse
from examscribe_lib.lint import lint_notes
from examscribe_lib.pipeline import compute_next, lint_ctx


class LintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ws = helpers.new_workspace()
        compute_next(cls.ws)          # creates skeletons for chapter 1
        cls.good = read_text(helpers.DRAFTS / "ch01" / "1.1.md")
        cls.expected = cls.ws.state["chapters"]["ch01"]["expected"]["1.1"]

    @classmethod
    def tearDownClass(cls):
        helpers.cleanup(cls.ws)

    def lint(self, text, part="1.1", mode="section", chapter="ch01"):
        fixed, _ = autofix(text)
        expected = (self.ws.state["chapters"][chapter]["expected"][part] if mode == "section"
                    else self.ws.state["chapters"][chapter]["chapter_expected"])
        return lint_notes(parse(fixed), lint_ctx(self.ws, chapter, mode, expected))

    def codes(self, text):
        return {i.code for i in self.lint(text).errors}

    def test_good_drafts_pass(self):
        res = self.lint(self.good)
        self.assertTrue(res.ok, [f"{i.line} {i.message}" for i in res.errors])
        self.assertGreater(res.stats["claims"], 20)

    def test_reference_example_passes(self):
        # the section example shipped with the skill must pass against the sample book
        compute_next(self.ws)
        from examscribe_lib.pipeline import _parts
        _parts(self.ws, self.ws.chapter("ch02"))
        text = read_text(helpers.SKILL / "references" / "examples" / "section-example.md")
        res = self.lint(text, part="2.2", chapter="ch02")
        self.assertTrue(res.ok, [f"{i.line} {i.message}" for i in res.errors])

    def test_skeleton_fails_with_placeholders(self):
        skel = read_text(self.ws.draft_dir("ch01") / "1.1.md")
        self.assertIn("placeholder", self.codes(skel))

    def test_paraphrased_definition(self):
        bad = self.good.replace('"Energy is the capacity to supply heat or do work."]\nplain',
                                '"Energy is the ability to provide heat or perform work."]\nplain')
        self.assertTrue(self.codes(bad) & {"quote-not-found", "quote-inexact"})

    def test_wrong_page(self):
        bad = self.good.replace('definition: [p.2: "Thermal energy', 'definition: [p.1: "Thermal energy')
        self.assertIn("quote-wrong-page", self.codes(bad))

    def test_invented_number(self):
        bad = self.good.replace("depends on both its mass and its speed. [p.1",
                                "is 41.8 J for a typical ball. [p.1")
        self.assertIn("number-unsupported", self.codes(bad))

    def test_calc_error(self):
        self.assertIn("calc", self.codes(self.good.replace("=> 9.00[J]", "=> 10.0[J]")))

    def test_numeric_answer_mismatch(self):
        self.assertIn("numeric-mismatch", self.codes(self.good.replace("answer: 9.00[J]", "answer: 8.00[J]")))

    def test_stray_text(self):
        self.assertIn("stray-text", self.codes(self.good.replace("::: figure FIG-1.1", "Energy matters!\n::: figure FIG-1.1")))

    def test_deleted_block(self):
        bad = re.sub(r"::: concept T-potential-energy.*?:::\n", "", self.good, flags=re.S)
        self.assertIn("block-missing", self.codes(bad))

    def test_mcq_rules(self):
        bad = self.good.replace("answer: A\n", "answer: B\n", 1)
        codes = self.codes(bad)
        self.assertIn("why-not", codes)
        self.assertIn("why-not-correct", codes)

    def test_missing_citation(self):
        bad = self.good.replace(' [p.1: "Work is done when a force moves matter through a distance."]', "")
        self.assertIn("no-citation", self.codes(bad))

    def test_definition_must_be_exact_citation(self):
        bad = self.good.replace('definition: [p.1: "Energy is the capacity to supply heat or do work."]',
                                'definition: Energy is the capacity [p.1: "Energy is the capacity to supply heat or do work."]')
        self.assertIn("exact-cite", self.codes(bad))

    def test_definition_must_name_term(self):
        bad = self.good.replace('definition: [p.1: "Energy is the capacity to supply heat or do work."]',
                                'definition: [p.1: "Work is done when a force moves matter through a distance."]')
        self.assertIn("definition-term", self.codes(bad))

    def test_new_concept_block_rejected(self):
        extra = "::: concept T-invented\nterm: Invented\ndefinition: UNSURE: not in the book at all\nplain: UNSURE: no idea here\n:::\n"
        self.assertIn("unknown-id", self.codes(self.good + "\n" + extra))

    def test_ai_field_tier_gate(self):
        bad = self.good.replace("ai-mnemonic:", "ai-analogy:")
        self.assertIn("ai-not-allowed", self.codes(bad))

    def test_unsure_needs_reason(self):
        bad = self.good.replace("holds-when: UNSURE: the book gives no conditions for this formula", "holds-when: UNSURE")
        self.assertIn("unsure-reason", self.codes(bad))

    def test_rearrangement_checked(self):
        bad = self.good.replace("rearrange: m = 2 * KE / v^2", "rearrange: m = KE / v^2")
        self.assertIn("rearrange", self.codes(bad))

    def test_trust_marks_autofixed(self):
        res = self.lint(self.good.replace("term: Energy", "term: Energy ✅"))
        self.assertTrue(res.ok)

    def test_chapter_summary_coverage(self):
        compute_next(self.ws)
        good = read_text(helpers.DRAFTS / "ch01" / "chapter.md")
        from examscribe_lib.pipeline import _chapter_draft
        _chapter_draft(self.ws, self.ws.chapter("ch01"))
        self.assertTrue(self.lint(good, mode="chapter").ok)
        bad = good.replace(" (covers: SUM-ch01-5)", "")
        self.assertIn("summary-uncovered", {i.code for i in self.lint(bad, mode="chapter").errors})


if __name__ == "__main__":
    unittest.main()
