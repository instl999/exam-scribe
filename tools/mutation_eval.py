"""Mutation testing: how many realistic errors do the checks catch?

Plants known errors into notes that passed every check, then measures what catches them:
  * the deterministic layer (quote check, number check, calculator, linter) on every mutant, and
  * optionally a model checker: --worksheet writes a claim worksheet mixing real claims and mutants, and
    --score grades a filled worksheet (catch rate per error type, false alarms on real claims).

    python tools/mutation_eval.py                      # deterministic layer on the bundled sample drafts
    python tools/mutation_eval.py --worksheet out.md   # worksheet for testing a model as checker
    python tools/mutation_eval.py --score out.md       # grade the filled worksheet
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import helpers  # noqa: E402

from examscribe_lib import verify as V  # noqa: E402
from examscribe_lib.common import read_text, sha  # noqa: E402
from examscribe_lib.esm import CITE_RE, autofix, parse  # noqa: E402
from examscribe_lib.lint import lint_notes  # noqa: E402
from examscribe_lib.mutate import mutate_claim  # noqa: E402
from examscribe_lib.pipeline import compute_next, lint_ctx  # noqa: E402

FILES = [("ch01", "1.1.md"), ("ch01", "1.2.md"), ("ch02", "2.1.md"), ("ch02", "2.2.md"), ("ch02", "2.3.md")]


def prepared_workspace():
    ws = helpers.new_workspace()
    for ch in ("ch01", "ch02"):
        compute_next(ws)
        for c, name in FILES:
            if c == ch:
                helpers.install_draft(ws, ch, name)
        from examscribe_lib.pipeline import _parts
        _parts(ws, ws.chapter(ch))
    return ws


def text_mutations(line: str, rng: random.Random) -> list[tuple[str, str]]:
    """Mutations applied to the raw draft line (they may touch quotes, numbers, pages, calc results).

    Headings, comments and question/option wording are skipped: they carry no claims (question premises
    are checked by the blind solver, not by these deterministic checks)."""
    out = []
    s = line.lstrip()
    if not s or s.startswith(("#", "<!--", "LO-", "ask:", "option ", "title:", "name:")) or ":" not in s:
        return out
    m = CITE_RE.search(line)
    if m:
        q = m.group("quote")
        words = q.split()
        if len(words) > 5:   # paraphrase inside the quote
            i = rng.randrange(1, len(words) - 1)
            out.append(("quote-paraphrase", line.replace(q, " ".join(words[:i] + ["really"] + words[i:]), 1)))
        page = m.group("page")
        if page.isdigit():
            out.append(("wrong-page", line.replace(f"[p.{page}:", f"[p.{int(page) + 1}:", 1)))
    from examscribe_lib.citations import EQ_REF, REF_PATTERNS
    claim_part = REF_PATTERNS.sub(" ", EQ_REF.sub(" ", line.split("[p.")[0]))
    nums = re.findall(r"(?<![\w.\[])\d+\.\d+|\b\d{2,}\b", claim_part)
    if nums:
        n = rng.choice(nums)
        out.append(("number", line.replace(n, str(round(float(n) * 1.1 + 1, 2)), 1)))
    if line.startswith("calc:") and "=>" in line:
        left, right = line.split("=>", 1)
        num = re.search(r"[\d.]+", right)
        if num:
            out.append(("calc-result", left + "=>" + right.replace(num.group(0), str(round(float(num.group(0)) * 1.07, 3)), 1)))
    return out


def deterministic(ws) -> dict:
    rng = random.Random(11)
    stats = defaultdict(Counter)
    for ch, name in FILES:
        good = read_text(helpers.DRAFTS / ch / name)
        expected = ws.state["chapters"][ch]["expected"][name[:-3]]
        lines = good.split("\n")
        for i, line in enumerate(lines):
            for op, bad_line in text_mutations(line, rng):
                if bad_line == line:
                    continue
                bad = "\n".join(lines[:i] + [bad_line] + lines[i + 1:])
                fixed, _ = autofix(bad)
                res = lint_notes(parse(fixed), lint_ctx(ws, ch, "section", expected))
                stats[op]["planted"] += 1
                if not res.ok or any(x.level == "warn" and x.line == i + 1 for x in res.issues):
                    stats[op]["caught"] += 1
    return stats


def write_worksheet(ws, path: Path, n_real: int = 40, n_mutants: int = 20) -> None:
    rng = random.Random(5)
    claims = V.extract_claims(ws, "ch01") + V.extract_claims(ws, "ch02")
    rng.shuffle(claims)
    terms = [it["text"] for it in ws.all_inventory_items().values() if it["kind"] == "term"]
    items, answer = [], {}
    for c in claims[:n_real]:
        bid = "V-" + sha(c.id + "r", 8)
        items.append((bid, c.text, c.context))
        answer[bid] = "real"
    for c in claims[n_real:]:
        if len([a for a in answer.values() if a != "real"]) >= n_mutants:
            break
        mut = mutate_claim(c.text, c.context, terms, seed=rng.randint(0, 10 ** 6))
        if mut:
            bid = "V-" + sha(c.id + "m", 8)
            items.append((bid, mut[0], c.context))
            answer[bid] = mut[1]
    rng.shuffle(items)
    blocks = [f"::: claim {b}\nclaim: {cl}\ncontext: {' '.join(cx.split())}\nverdict: <<FILL: SUPPORTED | PARTIAL | "
              f"NOT_SUPPORTED | CONTRADICTED>>\nspan: <<FILL>>\nproblem: <<OPTIONAL>>\n:::" for b, cl, cx in items]
    path.write_text(V.HEADER_CLAIMS.format(ch="eval", n="1") + "\n" + "\n\n".join(blocks) + "\n", encoding="utf-8")
    path.with_suffix(".answers.json").write_text(json.dumps(answer, indent=1), encoding="utf-8")
    print(f"wrote {path} ({len(items)} items) and its answer key {path.with_suffix('.answers.json')}")


def score(path: Path) -> None:
    answer = json.loads(path.with_suffix(".answers.json").read_text(encoding="utf-8"))
    doc = parse(path.read_text(encoding="utf-8-sig"))
    per_op, false_alarms, real = Counter(), 0, 0
    caught = Counter()
    for b in doc.of_kind("claim"):
        truth = answer.get(b.id)
        verdict = b.value("verdict").strip().upper()
        if truth == "real":
            real += 1
            false_alarms += verdict != "SUPPORTED"
        elif truth:
            per_op[truth] += 1
            caught[truth] += verdict != "SUPPORTED"
    print("error type        caught / planted")
    for op in sorted(per_op):
        print(f"  {op:<16} {caught[op]:>3} / {per_op[op]}")
    print(f"real claims marked not SUPPORTED (false alarms or strictness): {false_alarms} / {real}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worksheet")
    ap.add_argument("--score")
    a = ap.parse_args()
    if a.score:
        score(Path(a.score))
        return
    ws = prepared_workspace()
    try:
        if a.worksheet:
            write_worksheet(ws, Path(a.worksheet))
            return
        stats = deterministic(ws)
        print("Deterministic checks (quote, number, calculator, linter) on planted errors:")
        print("error type          caught / planted")
        for op, c in sorted(stats.items()):
            print(f"  {op:<18} {c['caught']:>4} / {c['planted']}")
        print("Errors that change meaning without touching quotes or numbers (a swapped term, a dropped condition) "
              "are left to the independent checker; test it with --worksheet / --score.")
    finally:
        helpers.cleanup(ws)


if __name__ == "__main__":
    main()
