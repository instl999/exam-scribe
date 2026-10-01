"""Mistake log with successive relearning: missed questions come back until answered right three times in a row.

Intervals after a miss: 1 day, then 3, 7 and 14 days after each correct answer.
Results arrive from the study pages ("Export my results") or by hand
(`mistakes <ws> add Q-2.2-01`). `mistakes <ws> due` builds today's review set.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .common import ESError, Workspace, read_json, today, write_json
from .notes import load_chapter

INTERVALS = (1, 3, 7, 14)


def _load(ws: Workspace) -> dict:
    return read_json(ws.progress_dir / "mistakes.json", None) or {"questions": {}}


def _save(ws: Workspace, data: dict) -> None:
    write_json(ws.progress_dir / "mistakes.json", data)


def record(ws: Workspace, qid: str, correct: bool, when: dt.date | None = None) -> None:
    data = _load(ws)
    rec = data["questions"].setdefault(qid, {"history": [], "box": 0, "due": None, "graduated": False})
    day = when or today()
    rec["history"].append({"at": day.isoformat(), "correct": bool(correct)})
    if not correct:
        rec["box"] = 0
        rec["graduated"] = False
        rec["due"] = (day + dt.timedelta(INTERVALS[0])).isoformat()
    elif rec["due"] is not None:
        rec["box"] = min(rec["box"] + 1, len(INTERVALS) - 1)
        streak = 0
        for h in reversed(rec["history"]):
            if not h["correct"]:
                break
            streak += 1
        rec["graduated"] = streak >= 3
        rec["due"] = None if rec["graduated"] else (day + dt.timedelta(INTERVALS[rec["box"]])).isoformat()
    _save(ws, data)


def due(ws: Workspace) -> list[str]:
    data = _load(ws)
    t = today().isoformat()
    return sorted(q for q, r in data["questions"].items() if r.get("due") and r["due"] <= t and not r.get("graduated"))


def cli(ws: Workspace, args: list[str]) -> str:
    if not args:
        raise ESError("Use: mistakes <ws> add Q-ID... | import <results.json> | due")
    sub = args[0]
    if sub == "add":
        if len(args) < 2:
            raise ESError("Name at least one question ID, e.g. mistakes <ws> add Q-2.2-01")
        for qid in args[1:]:
            record(ws, qid, False)
        return f"Logged {len(args) - 1} missed question(s). They come back tomorrow. See: mistakes <ws> due"
    if sub == "import":
        if len(args) < 2:
            raise ESError("Give the exported results file, e.g. mistakes <ws> import examscribe-results-2026-10-01.json")
        payload = json.loads(Path(args[1]).read_text(encoding="utf-8-sig"))
        rows = payload.get("results", payload if isinstance(payload, list) else [])
        rows.sort(key=lambda r: r.get("at", ""))
        seen = set()
        for r in rows:
            key = (r["id"], r.get("at"))
            if key in seen:
                continue
            seen.add(key)
            when = dt.date.fromisoformat(r["at"][:10]) if r.get("at") else None
            record(ws, r["id"], bool(r.get("correct")), when)
        wrong = sum(1 for r in rows if not r.get("correct"))
        return f"Imported {len(rows)} result(s), {wrong} missed. Due now: {len(due(ws))}."
    if sub == "due":
        ids = due(ws)
        if not ids:
            return "Nothing due today."
        from .render import render_quiz_page
        items = []
        for ch in ws.chapters_in_scope():
            if not ws.draft_dir(ch["id"]).exists():
                continue
            notes = load_chapter(ws, ch["id"])
            for q in notes.questions():
                if q.id in ids:
                    items.append((q.blk, notes.trust.get("questions", {}).get(q.id, {}).get("status", ""), ch["id"]))
        path = render_quiz_page(ws, "review-due.html", "Due today",
                                "Questions you missed earlier. Each one returns until you get it right three times in "
                                "a row.", items)
        return f"{len(ids)} question(s) due: {', '.join(ids)}\nOpen: {path.as_uri()}"
    raise ESError(f"Unknown mistakes command '{sub}'.", "Use add, import or due.")
