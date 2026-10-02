"""End to end: every stage, including a rejected lazy checker, a fix loop, and the final build."""
import json
import re
import unittest

import helpers
from examscribe_lib import verify as V
from examscribe_lib.common import read_text, write_text
from examscribe_lib.pipeline import check, compute_next


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ws = helpers.new_workspace()

    @classmethod
    def tearDownClass(cls):
        helpers.cleanup(cls.ws)

    def test_full_run(self):
        ws = self.ws
        seen = helpers.drive(ws, lazy_first=True)
        self.assertEqual(seen[0], "write-section:ch01:1.1")
        self.assertIn("write-chapter:ch01", seen)
        self.assertIn("verify-formulas:ch01", seen)
        self.assertTrue(any(t.startswith("solve:ch02") for t in seen))
        # the check that finishes chapter 1 tells the model to share the chapter with the user right away
        ready = [t for t in helpers.CHECK_OUTPUTS if "Tell the user now" in t and 'Chapter ch01 "Energy' in t]
        self.assertEqual(len(ready), 1)
        self.assertIn("ch01.html", ready[0])
        self.assertEqual(seen[-1], "done")
        # every claim verified, every key confirmed
        from examscribe_lib.report import report_data
        d = report_data(ws)
        self.assertEqual(d["totals"]["warn"], 0)
        self.assertEqual(d["totals"]["pending"], 0)
        self.assertGreater(d["totals"]["ok"], 150)
        self.assertEqual(d["totals"]["q_ok"], 20)
        self.assertEqual(d["totals"]["rejected"], 1)          # the lazy worksheet was thrown away
        # outputs
        for name in ("index.html", "ch01.html", "ch02.html", "review-ch01.html", "mock-exam.html", "cheat-sheet.html",
                     "traps.html", "report.html", "practice-1.html"):
            self.assertTrue((ws.site_dir / name).exists(), name)
        for name in ("flashcards.apkg", "flashcards.tsv", "study-plan.ics", "obsidian/ch02.md", "verification-report.md"):
            self.assertTrue((ws.export_dir / name).exists(), name)
        ics = (ws.export_dir / "study-plan.ics").read_bytes()
        self.assertTrue(ics.startswith(b"BEGIN:VCALENDAR\r\n"))
        html = read_text(ws.site_dir / "ch02.html")
        self.assertIn("data-qid=\"Q-2.2-02\"", html)
        self.assertIn("✓", html)

        # --- a fix loop: break a claim, re-verify it with a checker that rejects it, then repair it
        path = ws.draft_dir("ch01") / "1.2.md"
        good = read_text(path)
        write_text(path, good.replace("it is small, so chemists often use kilojoules",
                                      "it is small, so chemists always use kilojoules"))
        task = compute_next(ws)
        self.assertEqual(task.kind, "verify-claims")
        keys = json.loads((ws.verify_dir("ch01") / ".keys.json").read_text(encoding="utf-8"))[task.worksheet]
        # checker marks the changed real claim PARTIAL, canaries NOT_SUPPORTED
        import hashlib
        text = read_text(task.edit)
        out = []
        cur_canary = False
        for line in text.split("\n"):
            m = re.match(r"^::: claim (\S+)", line)
            if m:
                cur_canary = hashlib.sha256((keys["salt"] + m.group(1)).encode()).hexdigest()[:16] in keys["canary"]
            if line.startswith("verdict:"):
                line = "verdict: NOT_SUPPORTED" if cur_canary else "verdict: PARTIAL"
            elif line.startswith("span:"):
                line = "span: NONE"
            elif line.startswith("problem:"):
                line = "problem: The context says often, not always."
            out.append(line)
        write_text(task.edit, "\n".join(out))
        res = check(ws)
        self.assertTrue(res.ok, res.text[:500])
        task = compute_next(ws)
        self.assertEqual(task.kind, "fix")
        self.assertIn("always use kilojoules", task.body)
        write_text(path, good)          # the writer repairs the claim
        res = check(ws)
        self.assertTrue(res.ok, res.text[:800])
        self.assertEqual(compute_next(ws).kind, "done")

    def test_accept_flags_after_attempts(self):
        ws = helpers.new_workspace()
        try:
            draft = ws.draft_dir("ch01") / "1.1.md"
            # checks on the untouched skeleton cost nothing, so they cannot be burned to reach --accept-flags
            for _ in range(5):
                self.assertIn("NOT STARTED", check(ws).text)
            self.assertIn("NOT STARTED", check(ws, accept_flags=True).text)
            draft.write_text(draft.read_text(encoding="utf-8") + "\n", encoding="utf-8")    # an attempt was made
            for _ in range(4):
                self.assertFalse(check(ws).ok)          # still full of placeholders
            res = check(ws, accept_flags=True)
            self.assertTrue(res.ok, res.text[:1500])
            text = read_text(ws.draft_dir("ch01") / "1.1.md")
            self.assertIn("UNSURE", text)
            self.assertNotIn("<<FILL", text)
            self.assertTrue(ws.state["chapters"]["ch01"]["flags"]["1.1"])
        finally:
            helpers.cleanup(ws)


if __name__ == "__main__":
    unittest.main()
