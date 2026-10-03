"""Guardrails for agents that cut corners: changed skill files, hand-edited records, evidence that does not support
the verdict, and "plain" explanations that only repeat the definition."""
import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers


def run(*argv) -> tuple[int, str]:
    import examscribe
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = examscribe.main([str(a) for a in argv])
    return code, out.getvalue()


class SkillIntegrityTests(unittest.TestCase):
    def test_manifest_is_current(self):
        r = subprocess.run([sys.executable, str(helpers.ROOT / "tools" / "make_integrity.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_changed_skill_file_stops_every_command(self):
        from examscribe_lib.integrity import make_manifest
        tmp = Path(tempfile.mkdtemp(prefix="examscribe-skill-"))
        try:
            skill = tmp / "exam-scribe"
            shutil.copytree(helpers.SKILL, skill, ignore=shutil.ignore_patterns("__pycache__", "evals"))
            (skill / "scripts" / "integrity.json").write_text(json.dumps(make_manifest(skill)), encoding="utf-8")
            cli = [sys.executable, str(skill / "scripts" / "examscribe.py"), "format", "concept"]
            self.assertEqual(subprocess.run(cli, capture_output=True, text=True).returncode, 0)
            # a Windows checkout with CRLF line endings is not a change
            ref = skill / "references" / "format.md"
            ref.write_bytes(ref.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
            self.assertEqual(subprocess.run(cli, capture_output=True, text=True).returncode, 0)
            # an agent "fixing" the linter is
            lint = skill / "scripts" / "examscribe_lib" / "lint.py"
            lint.write_text(lint.read_text(encoding="utf-8") + "\n# relaxed\n", encoding="utf-8")
            r = subprocess.run(cli, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 3)
            self.assertIn("STOP", r.stdout)
            self.assertIn("scripts/examscribe_lib/lint.py", r.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class WorkspaceIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.ws = helpers.new_workspace()

    def tearDown(self):
        helpers.cleanup(self.ws)

    def test_hand_edited_state_stops_until_restored(self):
        root = self.ws.root
        self.assertEqual(run("status", root)[0], 0)
        state = json.loads((root / "state.json").read_text(encoding="utf-8"))
        state["plan_confirmed"] = True
        state.setdefault("chapters", {}).setdefault("ch01", {})["done"] = True       # "skip to the end"
        (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
        code, out = run("next", root)
        self.assertEqual(code, 3)
        self.assertIn("state.json", out)
        self.assertIn("restore", out)
        code, out = run("restore", root)
        self.assertEqual(code, 0)
        self.assertIn("put back", out)
        restored = json.loads((root / "state.json").read_text(encoding="utf-8"))
        self.assertFalse(restored.get("chapters", {}).get("ch01", {}).get("done"))
        self.assertEqual(run("next", root)[0], 0)
        self.assertIn("changed by hand 1 time", run("report", root)[1])

    def test_planted_verdicts_file_is_set_aside(self):
        root = self.ws.root
        fake = root / "chapters" / "ch01" / "verify" / "verdicts.json"
        fake.parent.mkdir(parents=True, exist_ok=True)
        fake.write_text(json.dumps({"claims": {"x": {"verdict": "SUPPORTED"}}}), encoding="utf-8")
        code, out = run("status", root)
        self.assertEqual(code, 3)
        self.assertIn("not written by the scripts", out)
        run("restore", root)
        self.assertFalse(fake.exists())
        self.assertTrue(any((root / ".backup" / "rejected").rglob("verdicts.json.*")))
        self.assertEqual(run("status", root)[0], 0)

    def test_files_the_scripts_write_never_trip_the_guard(self):
        root = self.ws.root
        for _ in range(3):
            code, out = run("next", root)
            self.assertEqual(code, 0, out)
            run("check", root)


class EvidenceTests(unittest.TestCase):
    def _lint(self, rows, ctx="Energy is the capacity to do work or to supply heat in a system."):
        from examscribe_lib.esm import parse
        from examscribe_lib.lint import lint_worksheet
        blocks, originals = [], {}
        for i, (claim, span) in enumerate(rows):
            bid = f"V-{i:04d}"
            originals[bid] = {"claim": claim, "context": ctx}
            blocks.append(f"::: claim {bid}\nclaim: {claim}\ncontext: {ctx}\nverdict: SUPPORTED\nspan: {span}\n:::")
        return {i.code for i in lint_worksheet(parse("\n\n".join(blocks) + "\n"), originals, "claim").issues}

    def test_span_must_be_about_the_claim(self):
        self.assertNotIn("span-unrelated", self._lint([("Energy can supply heat.", "to supply heat in a system")]))
        self.assertIn("span-unrelated", self._lint([("Work needs a force.", "to supply heat in a system")]))
        # inflections and compound words still count as shared words
        self.assertNotIn("span-unrelated", self._lint([("Energies supply heating.", "to supply heat in a system")]))
        zh = "能量是做功或提供热量的能力，热是在不同温度的物体之间传递的能量。"
        self.assertNotIn("span-unrelated", self._lint([("能量是做功的能力。", "能量是做功或提供热量的能力")], zh))
        self.assertIn("span-unrelated", self._lint([("动能是运动的能量。", "在不同温度的物体之间传递")], zh))

    def test_one_span_cannot_serve_many_claims(self):
        rows = [("Energy is a capacity.", "Energy is the capacity to do work")] * 4
        self.assertIn("span-repeated", self._lint(rows))
        self.assertNotIn("span-repeated", self._lint(rows[:3]))

    def test_plain_must_not_copy_the_definition(self):
        from examscribe_lib.esm import parse
        from examscribe_lib.lint import LintContext, lint_notes
        from examscribe_lib.tiers import tier_params
        quotes = mock.Mock(check=lambda *a, **k: mock.Mock(status="exact", context="", page="1"))
        ctx = LintContext(ws=mock.Mock(), tier=tier_params("strict"), expected={"T-energy": "concept"},
                          min_questions=0, qindex=quotes)
        quote = "Energy is the capacity to do work or to supply heat"
        block = ("::: concept T-energy\nterm: energy\ndefinition: [p.1: \"{q}\"]\nplain: {plain} [p.1: \"{q}\"]\n"
                 "why: It is the quantity every chapter keeps track of. [p.1: \"{q}\"]\n:::\n")
        codes = lambda plain: {i.code for i in lint_notes(parse(block.format(q=quote, plain=plain)), ctx).issues}
        self.assertIn("plain-copies-definition", codes("Energy is the capacity to do work or to supply heat."))
        self.assertNotIn("plain-copies-definition", codes("Energy is what lets something cause change."))


class CardTests(unittest.TestCase):
    def test_cards_say_keep_going_and_no_fill_in_programs(self):
        from examscribe_lib.pipeline import CHECKER_RULES, KEEP_GOING, WRITER_RULES, compute_next, render_card
        ws = helpers.new_workspace()
        try:
            card = render_card(ws, compute_next(ws))
            self.assertIn(KEEP_GOING, card)
            self.assertIn("program", card)
            self.assertTrue(any(".keys.json" in r for r in CHECKER_RULES))
            self.assertTrue(WRITER_RULES[-1].startswith("Never delete a block"))      # fix cards reuse the last rule
        finally:
            helpers.cleanup(ws)


class QuoteLengthTests(unittest.TestCase):
    def test_short_but_identifying_cjk_quotes_are_long_enough(self):
        from examscribe_lib.citations import quote_long_enough
        self.assertTrue(quote_long_enough("细胞是生物体的基本单位"))      # 11 characters
        self.assertTrue(quote_long_enough("情報社会の問題解決"))
        self.assertFalse(quote_long_enough("交叉学科"))                   # 4 characters identify nothing
        self.assertFalse(quote_long_enough("energy is work"))
        self.assertTrue(quote_long_enough("energy is the capacity"))


class EmptyExplanationTests(unittest.TestCase):
    def test_why_that_only_points_at_the_book(self):
        from examscribe_lib.lint import says_nothing
        # rejected by a strict checker in the gpt-6-sol trial; a lenient checker let such lines through
        for empty in ("这与书中的表述相符。", "这与书中的表述一致。", "书中给出这一基本定义。", "这是书中对人内传播的定义。",
                      "This matches what the book says.", "The book says so."):
            self.assertTrue(says_nothing(empty), empty)
        for real in ("课本明确指出传播学的交叉性质。", "传播学是一门交叉学科，与新闻学、社会学等学科联系密切。",
                     "因为能量守恒。", "Energy is the capacity to do work, so a falling object can do work.",
                     "Heat flows from the hotter body to the colder one."):
            self.assertFalse(says_nothing(real), real)


class UntouchedWorksheetTests(unittest.TestCase):
    def test_check_on_a_fresh_worksheet_costs_no_attempt(self):
        from examscribe_lib.pipeline import check, compute_next
        ws = helpers.new_workspace()
        try:
            for _ in range(40):                       # write every section, then reach the first worksheet
                task = compute_next(ws)
                if task.kind == "verify-claims":
                    break
                if task.kind in ("write-section", "write-chapter"):
                    helpers.install_draft(ws, task.chapter, task.edit.name)
                self.assertTrue(check(ws).ok or task.kind == "notify")
            self.assertEqual(task.kind, "verify-claims")
            res = check(ws)
            self.assertIn("NOT STARTED", res.text)
            self.assertNotIn(task.id, ws.state.get("attempts", {}))
            helpers.oracle_fill(ws)                   # a filled worksheet is judged as usual
            self.assertNotIn("NOT STARTED", check(ws).text)
        finally:
            helpers.cleanup(ws)


class SkeletonTests(unittest.TestCase):
    def test_instruction_comments_are_not_placeholders(self):
        # the draft's own instructions must not trip the unfilled-placeholder check (every model hit it)
        import re
        from examscribe_lib.esm import PLACEHOLDER_RE
        from examscribe_lib.pipeline import compute_next
        ws = helpers.new_workspace()
        try:
            text = compute_next(ws).edit.read_text(encoding="utf-8")
            comments = [line for line in text.splitlines() if line.strip().startswith("<!--")]
            self.assertTrue(comments)
            self.assertFalse([c for c in comments if PLACEHOLDER_RE.search(c)])
            self.assertTrue(re.search(r"<<FILL", text))          # the fields themselves still have placeholders
        finally:
            helpers.cleanup(ws)


class UntouchedDraftTests(unittest.TestCase):
    def test_check_on_the_untouched_draft_costs_no_attempt(self):
        from examscribe_lib.pipeline import check, compute_next
        ws = helpers.new_workspace()
        try:
            task = compute_next(ws)
            self.assertEqual(task.kind, "write-section")
            res = check(ws)
            self.assertFalse(res.ok)
            self.assertIn("NOT STARTED", res.text)
            self.assertNotIn(task.id, ws.state.get("attempts", {}))
            task.edit.write_text(task.edit.read_text(encoding="utf-8") + "\n", encoding="utf-8")   # touched
            res = check(ws)
            self.assertNotIn("NOT STARTED", res.text)
            self.assertEqual(ws.state["attempts"][task.id], 1)
        finally:
            helpers.cleanup(ws)


if __name__ == "__main__":
    unittest.main()
