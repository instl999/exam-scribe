"""Priorities with visible reasons, and the study-plan summary shown to the user.

A star rating is only useful if the student can see why it was given, so every
section's stars come with the signals behind them: past-paper hits, syllabus
lines, learning objectives, end-of-chapter exercises, boxed content, and key
terms that later chapters reuse.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter

from .common import Workspace, now_iso, today
from .config import get_key
from .tiers import TIERS

WEIGHTS = {"past": 3.0, "syllabus": 1.5, "objectives": 1.0, "exercises": 1.0, "reuse": 0.8, "terms": 0.5,
           "boxed": 0.4}


def _norm(values: dict[str, float]) -> dict[str, float]:
    mx = max(values.values(), default=0)
    return {k: (v / mx if mx else 0.0) for k, v in values.items()}


def compute_priorities(ws: Workspace) -> dict:
    if not ws.state.get("stages", {}).get("inventory", {}).get("done"):
        from .inventory import build_inventory
        build_inventory(ws)
    chapters = ws.chapters_in_scope()
    mats = ws.state.get("materials", {})
    items_all = ws.all_inventory_items()
    past: Counter = Counter()
    syllabus: set[str] = set()
    n_papers = 0
    for m in mats.values():
        if m.get("kind") == "past-paper" and m.get("mapping"):
            n_papers += 1
            for picks in m["mapping"].values():
                for p in picks:
                    sec = items_all.get(p, {}).get("section") or p
                    past[sec] += 1
        if m.get("kind") == "syllabus" and m.get("mapping"):
            for picks in m["mapping"].values():
                syllabus.update(picks)
    signals: dict[str, dict] = {}
    for ch in chapters:
        inv = ws.inventory(ch["id"])
        for sec in inv["sections"]:
            if not sec.get("pages") or ("start" in sec and not ws.section_in_scope(sec)):
                continue
            sid = sec["id"]
            its = [it for it in inv["items"] if it.get("section") == sid]
            terms = [it for it in its if it["kind"] == "term"]
            signals[sid] = {
                "chapter": ch["id"], "title": sec["title"], "pages": sec["pages"],
                "past": past.get(sid, 0),
                "syllabus": 1 if sid in syllabus else 0,
                "objectives": sum(1 for it in its if it["kind"] == "objective"),
                "exercises": inv.get("exercise_counts", {}).get(sid, 0),
                "reuse": sum(len(t.get("also_in", [])) for t in terms) +
                         sum(1 for t in terms if (t.get("signals") or {}).get("in_summary")),
                "terms": len(terms) + sum(1 for it in its if it["kind"] == "equation"),
                "boxed": sum(1 for t in terms if t.get("boxed")),
            }
    norms = {k: _norm({sid: s[k] for sid, s in signals.items()}) for k in WEIGHTS}
    scores = {sid: sum(WEIGHTS[k] * norms[k][sid] for k in WEIGHTS) for sid in signals}
    ranked = sorted(scores, key=lambda s: -scores[s])
    n = len(ranked)
    stars = {}
    for i, sid in enumerate(ranked):
        stars[sid] = 3 if i < max(1, round(n * 0.3)) else (2 if i < max(1, round(n * 0.7)) else 1)
    sections = {}
    for sid, s in signals.items():
        reasons = []
        if s["past"]:
            reasons.append(f"{s['past']} past-paper question(s)")
        if s["syllabus"]:
            reasons.append("listed in the syllabus")
        if s["objectives"]:
            reasons.append(f"{s['objectives']} learning objective(s)")
        if s["exercises"]:
            reasons.append(f"{s['exercises']} end-of-chapter exercise(s)")
        if s["reuse"]:
            reasons.append("ideas reused in summaries or later chapters")
        if s["boxed"]:
            reasons.append("boxed key content")
        minutes = max(15, 7 * len(s["pages"])) * {3: 1.2, 2: 1.0, 1: 0.7}[stars[sid]]
        sections[sid] = {"chapter": s["chapter"], "title": s["title"], "stars": stars[sid],
                         "score": round(scores[sid], 3), "reasons": reasons or ["book signals only"],
                         "pages": s["pages"], "minutes": int(round(minutes))}
    plan = ws.state.setdefault("plan", {})
    plan.update({"order": [c["id"] for c in chapters], "sections": sections, "computed": now_iso(),
                 "past_papers": n_papers, "syllabus": bool(syllabus)})
    ws.save_state()
    return plan


def item_stars(ws: Workspace, item: dict) -> int:
    sec = ws.state.get("plan", {}).get("sections", {}).get(item.get("section") or "", {})
    base = sec.get("stars", 2)
    sig = item.get("signals") or {}
    bonus = 1 if (sig.get("in_summary") or sig.get("in_objectives") or sig.get("in_key_equations")) else 0
    return min(3, base + bonus) if base < 3 else 3


def stars(n: int) -> str:
    return "★" * n + "☆" * (3 - n)


def plan_summary(ws: Workspace) -> str:
    plan = compute_priorities(ws)
    cfg = ws.config
    exam_date = get_key(cfg, "exam.date")
    start = dt.date.fromisoformat(get_key(cfg, "study.start_date")) if get_key(cfg, "study.start_date") else today()
    hours = get_key(cfg, "study.hours_per_day") or 2
    lines = ["STUDY PLAN (draft)"]
    if exam_date:
        days = (dt.date.fromisoformat(exam_date) - start).days
        lines.append(f"Exam: {exam_date} ({days} days from {start.isoformat()})")
    else:
        days = 28
        lines.append("Exam date: not given (the calendar assumes 4 weeks)")
    lines.append(f"Formats: {', '.join(get_key(cfg, 'exam.formats') or ['not set'])}; book policy: "
                 f"{get_key(cfg, 'exam.book_policy') or 'not set'}; notes language: {get_key(cfg, 'output.language')}")
    secs = plan["sections"]
    total = sum(s["minutes"] for s in secs.values())
    review = 60 * len(plan["order"])
    avail = max(0, days) * hours * 60
    lines.append(f"Time: about {total / 60:.1f} h to learn + {review / 60:.1f} h of spaced review; available about "
                 f"{avail / 60:.0f} h ({hours} h/day).")
    if avail and total + review > avail:
        lines.append("  NOT ENOUGH TIME for everything: 1-star sections will be skim-only; focus on 3-star sections.")
    lines.append("")
    lines.append("Priorities (and why):")
    for cid in plan["order"]:
        ch = ws.chapter(cid)
        lines.append(f"  {cid} {ch['title']}")
        for sid, s in secs.items():
            if s["chapter"] != cid:
                continue
            lines.append(f"    {stars(s['stars'])} {sid} {s['title'][:40]:<40} {'; '.join(s['reasons'])}")
    src = []
    if plan.get("past_papers"):
        src.append(f"{plan['past_papers']} past paper(s)")
    if plan.get("syllabus"):
        src.append("the syllabus")
    src.append("the book's objectives, exercises and boxed content")
    lines.append(f"Stars are based on: {', '.join(src)}." +
                 ("" if plan.get("past_papers") else " Adding past papers makes them much more reliable."))
    lines.append("")
    lines.append("You will get: study notes per chapter (read and recall modes), self-tests with checked answers, "
                 "flashcards (Anki), review sheets, weekly mixed practice, a timed mock exam, a cheat sheet, a study "
                 "calendar, and a verification report listing anything a human should double-check.")
    tier = ws.tier
    lines.append(f"Quality: tier '{tier}' — {TIERS[tier]['summary']}")
    return "\n".join(lines)
