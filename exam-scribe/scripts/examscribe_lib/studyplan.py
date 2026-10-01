"""A study calendar: learn, spaced reviews, weekly mixed practice, mock exam, cheat-sheet day.

Reviews follow expanding intervals (1, 3, 7, 14, 30 days after first study);
mixed practice interleaves every chapter learned so far; the last two days are
reserved for a timed mock exam and a final pass over the cheat sheet and traps.
"""
from __future__ import annotations

import datetime as dt
import uuid

from .common import Workspace, today, write_text
from .config import get_key
from .ui import T, use_language

REVIEW_GAPS = (1, 3, 7, 14, 30)
DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def build_schedule(ws: Workspace) -> list[dict]:
    use_language(ws)
    cfg = ws.config
    plan = ws.state.get("plan") or {}
    secs = plan.get("sections", {})
    order = plan.get("order") or [c["id"] for c in ws.chapters_in_scope()]
    start = dt.date.fromisoformat(get_key(cfg, "study.start_date")) if get_key(cfg, "study.start_date") else today()
    exam = dt.date.fromisoformat(get_key(cfg, "exam.date")) if get_key(cfg, "exam.date") else start + dt.timedelta(28)
    rest = set(get_key(cfg, "study.rest_days") or [])
    hours = float(get_key(cfg, "study.hours_per_day") or 2)
    capacity = int(hours * 60 * 0.65)          # minutes per day for new learning; the rest is for reviews
    days = [start + dt.timedelta(i) for i in range(max(0, (exam - start).days))]
    days = [d for d in days if DAY_NAMES[d.weekday()] not in rest]
    events: list[dict] = []
    if not days:
        return [{"date": exam.isoformat(), "kind": "exam", "title": T("Exam"), "minutes": 0}]
    final = days[-2:] if len(days) >= 6 else days[-1:]
    learn_days = [d for d in days if d not in final] or days[:1]
    need = {cid: sum(s["minutes"] for s in secs.values() if s["chapter"] == cid) or 60 for cid in order}
    total_need = sum(need.values())
    total_cap = capacity * len(learn_days) * 0.8
    squeeze = min(1.0, total_cap / total_need) if total_need else 1.0
    di, used = 0, 0
    learned_on: dict[str, dt.date] = {}
    for cid in order:
        remaining = max(20, int(need[cid] * squeeze))
        title = ws.chapter(cid)["title"]
        while remaining > 0 and di < len(learn_days):
            chunk = min(remaining, capacity - used)
            if chunk <= 10:
                di, used = di + 1, 0
                continue
            events.append({"date": learn_days[di].isoformat(), "kind": "learn", "chapter": cid,
                           "title": T("Learn {cid}: {title}", cid=cid, title=title), "minutes": chunk,
                           "detail": T("Pretest first, then the notes in read mode, then the self-test.")})
            learned_on.setdefault(cid, learn_days[di])
            used += chunk
            remaining -= chunk
            if used >= capacity - 10:
                di, used = di + 1, 0
        learned_on.setdefault(cid, learn_days[min(di, len(learn_days) - 1)])
    last_study = final[0] if final else exam
    for cid, d0 in learned_on.items():
        for gap in REVIEW_GAPS:
            d = d0 + dt.timedelta(gap)
            while DAY_NAMES[d.weekday()] in rest:
                d += dt.timedelta(1)
            if d >= last_study:
                break
            events.append({"date": d.isoformat(), "kind": "review", "chapter": cid,
                           "title": T("Review {cid} (+{gap}d)", cid=cid, gap=gap), "minutes": 20,
                           "detail": T("Flashcards, then the review sheet in recall mode. Redo missed questions.")})
    week = 1
    d = days[0] + dt.timedelta(6)
    while d < last_study:
        learned = [c for c, d0 in learned_on.items() if d0 <= d]
        if len(learned) >= 2 or (learned and len(order) == 1):
            events.append({"date": d.isoformat(), "kind": "mixed", "chapters": learned, "set": week,
                           "title": T("Mixed practice set {week}", week=week), "minutes": 40,
                           "detail": T("Interleaved questions from every chapter so far. Log mistakes.")})
            week += 1
        d += dt.timedelta(7)
    if len(final) == 2:
        events.append({"date": final[0].isoformat(), "kind": "mock", "title": T("Timed mock exam"), "minutes": 90,
                       "detail": T("Exam conditions. Afterwards, redo every missed question.")})
        events.append({"date": final[1].isoformat(), "kind": "cheatsheet", "title": T("Cheat sheet + traps"),
                       "minutes": 60, "detail": T("Read the cheat sheet and the traps list; light flashcards only.")})
    else:
        events.append({"date": final[0].isoformat(), "kind": "mock", "title": T("Mock exam + cheat sheet"),
                       "minutes": 90, "detail": T("Short on time: one mock exam, then the cheat sheet.")})
    events.append({"date": exam.isoformat(), "kind": "exam", "title": T("Exam day"), "minutes": 0,
                   "detail": T("Skim the cheat sheet in the morning. Sleep matters more than cramming.")})
    events.sort(key=lambda e: (e["date"], {"learn": 0, "review": 1, "mixed": 2, "mock": 3, "cheatsheet": 4,
                                           "exam": 5}[e["kind"]]))
    ws.state["schedule"] = {"events": events, "squeeze": round(squeeze, 2)}
    ws.save_state()
    return events


def write_calendar(ws: Workspace, events: list[dict]) -> dict:
    title = ws.config.get("title", "Exam prep")
    out_dir = ws.export_dir
    ics = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ExamScribe//Study plan//EN", "CALSCALE:GREGORIAN",
           f"X-WR-CALNAME:{_ics_text(T('Study: {title}', title=title))[:60]}"]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for e in events:
        d = dt.date.fromisoformat(e["date"])
        uid = uuid.uuid5(uuid.NAMESPACE_URL, f"examscribe:{ws.root}:{e['date']}:{e['title']}")
        mins = f" ({T('{m} min', m=e['minutes'])})" if e.get("minutes") else ""
        ics += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}", f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{(d + dt.timedelta(1)).strftime('%Y%m%d')}",
                _fold(f"SUMMARY:{_ics_text(e['title'] + mins)}"),
                _fold(f"DESCRIPTION:{_ics_text(e.get('detail', ''))}"), "TRANSP:TRANSPARENT", "END:VEVENT"]
    ics.append("END:VCALENDAR")
    ics_path = out_dir / "study-plan.ics"
    out_dir.mkdir(parents=True, exist_ok=True)
    ics_path.write_bytes(("\r\n".join(ics) + "\r\n").encode("utf-8"))
    md = ["# " + T("Study plan \u2014 {title}", title=title), "",
          "| " + " | ".join(T(h) for h in ("Date", "Task", "Minutes", "How")) + " |", "|---|---|---|---|"]
    for e in events:
        md.append(f"| {e['date']} | {e['title']} | {e.get('minutes') or ''} | {e.get('detail', '')} |")
    write_text(out_dir / "study-plan.md", "\n".join(md) + "\n")
    return {"ics": ics_path, "md": out_dir / "study-plan.md"}


def _ics_text(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    raw = line.encode("utf-8")
    if len(raw) <= 74:
        return line
    parts, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > 73:
            parts.append(cur.decode("utf-8"))
            cur = b
        else:
            cur += b
    parts.append(cur.decode("utf-8"))
    return "\r\n ".join(parts)
