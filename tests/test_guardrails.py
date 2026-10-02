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


if __name__ == "__main__":
    unittest.main()
