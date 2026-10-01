import datetime as dt
import json
import unittest

import helpers
from examscribe_lib.common import write_text
from examscribe_lib.esm import parse
from examscribe_lib.render import inline, question_html, value_html


class RenderTests(unittest.TestCase):
    def test_inline_protects_math_and_blanks(self):
        html = inline("The ____ is $a_1 + b_1$ and **bold**")
        self.assertIn("blank-slot", html)
        self.assertIn("$a_1 + b_1$", html)
        self.assertIn("<strong>bold</strong>", html)

    def test_html_escaped(self):
        self.assertNotIn("<script>", inline("<script>alert(1)</script>"))

    def test_citation_chips(self):
        html = value_html('A claim. [p.12: "exact words from the book"] (covers: SUM-1)')
        self.assertIn('class="cite"', html)
        self.assertIn("p.12", html)
        self.assertNotIn("covers", html)

    def test_question_types(self):
        doc = parse("::: question Q-1\ntype: mcq\nbloom: remember\nask: Pick one\noption A: a\noption B: b\n"
                    "option C: c\noption D: d\nanswer: B\nwhy: because [p.1: \"four words right here\"]\n:::\n"
                    "::: question Q-2\ntype: numeric\nbloom: apply\nask: How much?\nanswer: 15.7[kJ]\n"
                    "why: x [p.1: \"four words right here\"]\n:::\n")
        mcq = question_html(doc.blocks[0])
        self.assertIn('data-answer="B"', mcq)
        self.assertEqual(mcq.count('class="opt"'), 4)
        num = question_html(doc.blocks[1])
        self.assertIn('data-answer="15.7"', num)
        self.assertIn("kJ", num)


class PlanAndMistakesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ws = helpers.new_workspace()

    @classmethod
    def tearDownClass(cls):
        helpers.cleanup(cls.ws)

    def test_schedule(self):
        from examscribe_lib.studyplan import build_schedule, write_calendar
        events = build_schedule(self.ws)
        kinds = [e["kind"] for e in events]
        self.assertEqual(kinds[0], "learn")
        self.assertIn("review", kinds)
        self.assertIn("mixed", kinds)
        self.assertEqual(kinds[-1], "exam")
        self.assertEqual(events[-1]["date"], "2026-12-15")
        mock = [e for e in events if e["kind"] == "mock"][0]
        self.assertEqual(mock["date"], "2026-12-13")
        daily = {}
        for e in events:
            if e["kind"] == "learn":
                daily[e["date"]] = daily.get(e["date"], 0) + e["minutes"]
        self.assertTrue(all(v <= 2 * 60 for v in daily.values()))
        cal = write_calendar(self.ws, events)
        raw = cal["ics"].read_bytes()
        self.assertIn(b"\r\nEND:VCALENDAR\r\n", raw)
        self.assertEqual(raw.count(b"BEGIN:VEVENT"), len(events))

    def test_mistake_log(self):
        from examscribe_lib import mistakes
        mistakes.record(self.ws, "Q-1.1-01", False, dt.date(2026, 9, 27))
        self.assertEqual(mistakes.due(self.ws), [])                    # due tomorrow
        import os
        os.environ["EXAMSCRIBE_TODAY"] = "2026-09-28"
        try:
            self.assertEqual(mistakes.due(self.ws), ["Q-1.1-01"])
            for day in (28, 29, 30):
                mistakes.record(self.ws, "Q-1.1-01", True, dt.date(2026, 9, day))
            self.assertEqual(mistakes.due(self.ws), [])                # graduated after 3 in a row
            payload = {"results": [{"id": "Q-2.1-01", "correct": False, "at": "2026-09-27T10:00:00"}]}
            f = self.ws.root / "results.json"
            f.write_text(json.dumps(payload), encoding="utf-8-sig")    # a BOM must not break import
            msg = mistakes.cli(self.ws, ["import", str(f)])
            self.assertIn("1 missed", msg)
        finally:
            os.environ["EXAMSCRIBE_TODAY"] = "2026-09-27"


class MaterialsTests(unittest.TestCase):
    def test_past_paper_flow(self):
        ws = helpers.new_workspace()
        try:
            from examscribe_lib.materials import add_material, check_material_task, pending_material_task
            from examscribe_lib.priority import compute_priorities
            paper = ws.root / "paper.txt"
            paper.write_text("1. How much heat does 20 g of water absorb when warmed by 5 degrees Celsius? Use the "
                             "specific heat capacity.\n2. Define enthalpy change and give its sign for an exothermic "
                             "reaction.\n3. What is the SI unit of energy?\n", encoding="utf-8")
            msg = add_material(ws, paper, "past-paper", "2025")
            self.assertIn("3 item", msg)
            task = pending_material_task(ws)
            self.assertIsNotNone(task)
            text = task.edit.read_text(encoding="utf-8")
            self.assertIn("2.2", text.split("candidates:")[1].split("\n")[0])   # q1 -> specific heat section first
            picks = iter(["2.2", "2.3", "1.2"])
            out = []
            for line in text.split("\n"):
                if line.startswith("pick:"):
                    line = f"pick: {next(picks)}"
                elif line.startswith("reason:"):
                    line = "reason: The question tests this section."
                out.append(line)
            write_text(task.edit, "\n".join(out))
            ok, info = check_material_task(ws, task)
            self.assertTrue(ok, info)
            plan = compute_priorities(ws)
            self.assertIn("1 past-paper question(s)", plan["sections"]["2.2"]["reasons"])
        finally:
            helpers.cleanup(ws)


if __name__ == "__main__":
    unittest.main()
