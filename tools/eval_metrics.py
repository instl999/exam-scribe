"""Quality metrics for a finished (or partly finished) ExamScribe workspace.

Use it to compare models or tiers on the same book:
    python tools/eval_metrics.py <workspace> [--json]

Metrics
  coverage      share of the book's own key terms (its glossary), key equations and summary sentences that the
                notes cover; learning objectives tested by at least one question
  evidence      share of claims verified / flagged / pending; approximate quotes
  checker       planted false claims caught; worksheets that had to be redone
  answer keys   confirmed / disputed by blind solving
  effort        FAILed checks per writing task, items accepted as UNSURE after running out of attempts
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exam-scribe" / "scripts"))

from examscribe_lib import verify as V  # noqa: E402
from examscribe_lib.common import Workspace, key_of, read_text  # noqa: E402
from examscribe_lib.esm import covers, is_unsure, parse  # noqa: E402


def chapter_metrics(ws: Workspace, cid: str) -> dict:
    inv = ws.inventory(cid)
    blocks = {}
    q_covers, mk_covers = set(), set()
    unsure = 0
    for path in V.draft_files(ws, cid):
        for b in parse(read_text(path)).blocks:
            blocks[b.id] = b
            unsure += sum(1 for f in b.fields if is_unsure(f.value))
            if b.kind == "question" and not b.get("skip"):
                q_covers.update(x for x in re.split(r"[,\s]+", b.value("covers")) if x)
            if b.kind == "must-know":
                for f in b.all("point"):
                    mk_covers.update(covers(f.value))

    def covered(item_id: str) -> bool:
        b = blocks.get(item_id)
        return bool(b) and not b.get("skip") and not is_unsure(b.value("definition") or b.value("latex") or "x")
    terms = [it for it in inv["items"] if it["kind"] == "term"]
    glossary_keys = {key_of(g["term"]) for g in inv.get("glossary", [])}
    gl_terms = [t for t in terms if key_of(t["text"]) in glossary_keys] or terms
    eqs = [it for it in inv["items"] if it["kind"] == "equation"]
    keyeq = [e for e in eqs if (e.get("signals") or {}).get("in_key_equations")] or eqs
    sums = [it["id"] for it in inv["items"] if it["kind"] == "summary"]
    los = [it["id"] for it in inv["items"] if it["kind"] == "objective"]
    trust = V.chapter_trust(ws, cid) if ws.verify_dir(cid).exists() else {"counts": {}, "questions": {}, "claims": {}}
    verdicts = V.load_verdicts(ws, cid) if ws.verify_dir(cid).exists() else {}
    stats = verdicts.get("canary_stats", {})
    cs = ws.state.get("chapters", {}).get(cid, {})
    attempts = {k: v for k, v in ws.state.get("attempts", {}).items() if f":{cid}" in k}
    qs = trust.get("questions", {})

    def ratio(a, b):
        return round(a / b, 3) if b else None
    counts = trust.get("counts", {})
    total = sum(counts.values())
    return {
        "coverage": {"glossary_terms": ratio(sum(covered(t["id"]) for t in gl_terms), len(gl_terms)),
                     "key_equations": ratio(sum(covered(e["id"]) for e in keyeq), len(keyeq)),
                     "summary_sentences": ratio(sum(s in mk_covers for s in sums), len(sums)),
                     "objectives_tested": ratio(sum(lo in q_covers for lo in los), len(los))},
        "evidence": {"claims": total, "verified": ratio(counts.get("ok", 0), total),
                     "flagged": ratio(counts.get("warn", 0), total), "pending": ratio(counts.get("pending", 0), total),
                     "unsure_fields": unsure},
        "checker": {"canaries_planted": stats.get("planted", 0), "canaries_caught": stats.get("caught", 0),
                    "catch_rate": ratio(stats.get("caught", 0), stats.get("planted", 0)),
                    "worksheets_redone": stats.get("rejected_batches", 0)},
        "answer_keys": {"questions": len(qs), "confirmed": sum(v["status"] == "ok" for v in qs.values()),
                        "disputed": sum(v["status"] == "warn" for v in qs.values())},
        "effort": {"failed_checks": sum(attempts.values()), "tasks_with_failures": len(attempts),
                   "accepted_flags": sum(len(v) for v in cs.get("flags", {}).values())},
    }


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    ws = Workspace.open(Path(sys.argv[1]))
    out = {"workspace": str(ws.root), "tier": ws.tier,
           "chapters": {c["id"]: chapter_metrics(ws, c["id"]) for c in ws.chapters_in_scope()
                        if ws.draft_dir(c["id"]).exists()}}
    if "--json" in sys.argv:
        print(json.dumps(out, indent=2))
        return
    print(f"Workspace {out['workspace']} (tier {out['tier']})")
    for cid, m in out["chapters"].items():
        print(f"\n{cid}")
        for group, vals in m.items():
            print(f"  {group:<12} " + ", ".join(f"{k}={v}" for k, v in vals.items()))


if __name__ == "__main__":
    main()
