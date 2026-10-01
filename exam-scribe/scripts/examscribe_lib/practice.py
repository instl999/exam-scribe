"""Practice material assembled only from VERIFIED content: mixed sets, mock exam, cheat sheet, traps, lookup index.

Nothing here is newly generated text. Interleaved sets and the mock exam reuse
questions whose answer keys were confirmed by the independent solver; the cheat
sheet and traps list reuse verified formulas, must-know points, comparisons and
misconceptions. That keeps the final-review material as trustworthy as the notes.
"""
from __future__ import annotations

import random
import re

from .common import Workspace, read_json
from .config import get_key
from .esm import citations, is_unsure, strip_citations
from .lint import _split_cells
from .notes import load_chapter
from .render import badge, esc, inline, page, render_quiz_page, value_html
from .common import write_text
from .ui import T, answer_text, use_language


def question_pool(ws: Workspace, include_unverified: bool = False) -> list[dict]:
    plan = ws.state.get("plan", {}).get("sections", {})
    pool = []
    for ch in ws.chapters_in_scope():
        if not ws.draft_dir(ch["id"]).exists():
            continue
        notes = load_chapter(ws, ch["id"])
        for q in notes.questions():
            st = notes.trust.get("questions", {}).get(q.id, {}).get("status", "pending")
            if st != "ok" and not include_unverified:
                continue
            pool.append({"blk": q.blk, "chapter": ch["id"], "section": q.section, "status": st,
                         "stars": plan.get(q.section or "", {}).get("stars", 2), "type": q.blk.value("type"),
                         "bloom": q.blk.value("bloom")})
    return pool


def _missed(ws: Workspace) -> dict[str, int]:
    data = read_json(ws.progress_dir / "mistakes.json", {}) or {}
    out = {}
    for qid, rec in data.get("questions", {}).items():
        out[qid] = sum(1 for h in rec.get("history", []) if not h.get("correct"))
    return out


def _interleave(qs: list[dict], rng: random.Random) -> list[dict]:
    by_ch: dict[str, list[dict]] = {}
    for q in qs:
        by_ch.setdefault(q["chapter"], []).append(q)
    for v in by_ch.values():
        rng.shuffle(v)
    out, last = [], None
    while any(by_ch.values()):
        keys = [k for k, v in by_ch.items() if v and k != last] or [k for k, v in by_ch.items() if v]
        k = max(keys, key=lambda x: len(by_ch[x]) + rng.random())
        out.append(by_ch[k].pop())
        last = k
    return out


def _weighted_sample(qs: list[dict], n: int, rng: random.Random, missed: dict[str, int]) -> list[dict]:
    items = list(qs)
    chosen = []
    while items and len(chosen) < n:
        weights = [q["stars"] + 2 * min(2, missed.get(q["blk"].id, 0)) + 0.5 for q in items]
        i = rng.choices(range(len(items)), weights=weights)[0]
        chosen.append(items.pop(i))
    return chosen


def build_mixed_sets(ws: Workspace, pool: list[dict], events: list[dict]) -> list[dict]:
    use_language(ws)
    missed = _missed(ws)
    out = []
    for e in [e for e in events if e["kind"] == "mixed"]:
        k = e["set"]
        qs = [q for q in pool if q["chapter"] in e["chapters"]]
        if not qs:
            continue
        rng = random.Random(1000 + k)
        chosen = _interleave(_weighted_sample(qs, 12, rng, missed), rng)
        path = render_quiz_page(ws, f"practice-{k}.html", T("Mixed practice {k}", k=k),
                                esc(T("For {date}. Questions from {chapters}, mixed on purpose: deciding which idea "
                                      "applies is part of the practice.", date=e["date"],
                                      chapters=", ".join(e["chapters"]))),
                                [(q["blk"], q["status"], q["chapter"]) for q in chosen])
        out.append({"set": k, "date": e["date"], "path": path, "count": len(chosen)})
    return out


def build_mock_exam(ws: Workspace, pool: list[dict]) -> dict | None:
    use_language(ws)
    if not pool:
        return None
    n = get_key(ws.config, "exam.question_count") or min(30, len(pool))
    n = min(n, len(pool))
    formats = get_key(ws.config, "exam.formats") or []
    want_types = set()
    if "mcq" in formats:
        want_types |= {"mcq", "tf"}
    if "problems" in formats:
        want_types |= {"numeric"}
    if "short-answer" in formats or "essay" in formats:
        want_types |= {"short", "cloze"}
    rng = random.Random(4242)
    preferred = [q for q in pool if not want_types or q["type"] in want_types]
    rest = [q for q in pool if q not in preferred]
    chosen = _weighted_sample(preferred, n, rng, _missed(ws))
    if len(chosen) < n:
        chosen += _weighted_sample(rest, n - len(chosen), rng, {})
    chosen = _interleave(chosen, rng)
    minutes = get_key(ws.config, "exam.duration_minutes") or max(20, 2 * len(chosen))
    path = render_quiz_page(ws, "mock-exam.html", T("Mock exam"),
                            esc(T("{n} questions, {m} minutes, answers shown only when you finish. Work under exam "
                                  "conditions: no notes.", n=len(chosen), m=minutes)),
                            [(q["blk"], q["status"], q["chapter"]) for q in chosen],
                            timed=minutes)
    return {"path": path, "count": len(chosen), "minutes": minutes}


def build_cheat_sheet(ws: Workspace) -> dict:
    use_language(ws)
    plan = ws.state.get("plan", {}).get("sections", {})
    policy = get_key(ws.config, "exam.book_policy") or "closed"
    sections_html, n_items = [], 0
    for ch in ws.chapters_in_scope():
        if not ws.draft_dir(ch["id"]).exists():
            continue
        notes = load_chapter(ws, ch["id"])
        cards = []
        for nb in notes.of_kind("formula"):
            if nb.blk.get("skip") or notes.trust.get("formulas", {}).get(nb.id, {}).get("status") != "ok":
                continue
            hw = nb.blk.value("holds-when")
            hw_txt = "" if is_unsure(hw) else " — " + inline(strip_citations(hw))
            cards.append((plan.get(nb.section or "", {}).get("stars", 2),
                          f'<div class="card"><strong>{inline(nb.blk.value("name"))}</strong><div class="math-block">'
                          f'$${esc(nb.blk.value("latex"))}$$</div><div class="muted">{hw_txt}</div></div>'))
        mk = notes.chapter_block("must-know")
        if mk:
            for i, f in enumerate(mk.blk.all("point")):
                st, _ = notes.field_status(mk, "point", i)
                if st == "ok":
                    cards.append((3, f'<div class="card">• {inline(strip_citations(f.value))}</div>'))
        for nb in notes.of_kind("compare"):
            if nb.blk.get("skip"):
                continue
            items = [x.strip() for x in _split_cells(nb.blk.value("items"))]
            inv = ws.all_inventory_items()
            heads = [inv.get(x, {}).get("display") or x for x in items]
            rows = []
            for i, f in enumerate(nb.blk.all("row")):
                st, _ = notes.field_status(nb, "row", i)
                cells = _split_cells(f.value)
                if st == "ok" and len(cells) >= 3:
                    rows.append(f"<tr><td>{inline(cells[0])}</td><td>{inline(strip_citations(cells[1]))}</td>"
                                f"<td>{inline(strip_citations(cells[2]))}</td></tr>")
            if rows:
                cards.append((2, f'<div class="card"><table><tr><th></th><th>{esc(heads[0])}</th><th>'
                                 f'{esc(heads[1] if len(heads) > 1 else "")}</th></tr>{"".join(rows)}</table></div>'))
        cards.sort(key=lambda x: -x[0])
        n_items += len(cards)
        if cards:
            sections_html.append(f'<h3>{esc(ch["id"])} {esc(ch["title"])}</h3>' + "".join(c for _, c in cards))
    intro = T("Only verified formulas, must-know facts and comparisons. Read it the day before the exam; the most "
              "important items come first in each chapter.")
    if policy == "cheat-sheet":
        intro += " " + T("Your exam allows one sheet of notes: print this, then rewrite it by hand in your own words.")
    title = T("Cheat sheet")
    body = f"<h1>{esc(title)}</h1><p class='muted'>{esc(intro)}</p><div class='cheat'>{''.join(sections_html)}</div>"
    path = ws.site_dir / "cheat-sheet.html"
    write_text(path, page(ws, title, body, crumb=title))
    return {"path": path, "items": n_items}


def build_traps(ws: Workspace) -> dict:
    use_language(ws)
    missed = _missed(ws)
    rows, n = [], 0
    for ch in ws.chapters_in_scope():
        if not ws.draft_dir(ch["id"]).exists():
            continue
        notes = load_chapter(ws, ch["id"])
        for nb in notes.of_kind("concept"):
            for i, f in enumerate(nb.blk.all("misconception")):
                st, _ = notes.field_status(nb, "misconception", i)
                m = re.match(r"^\s*wrong\s*:\s*(?P<w>.+?)\s*\|\s*right\s*:\s*(?P<r>.+)$", f.value, re.I | re.S)
                if m and st == "ok":
                    n += 1
                    rows.append(f'<div class="card"><div class="kind">{esc(nb.blk.value("term"))}</div>'
                                f'<div class="wrong">✗ {inline(m.group("w"))}</div>'
                                f'<div class="right">✓ {value_html(m.group("r"))}</div></div>')
        for q in notes.questions():
            if missed.get(q.id, 0) >= 2:
                n += 1
                rows.append(f'<div class="card"><div class="kind">{esc(T("You missed this {n} times ({qid})", n=missed[q.id], qid=q.id))}</div>'
                            f'{inline(q.blk.value("ask"))}<div class="right">✓ {inline(answer_text(q.blk.value("type"), q.blk.value("answer")))} '
                            f'— {value_html(q.blk.value("why"))}</div></div>')
    title = T("Traps")
    body = (f"<h1>{esc(title)}</h1><p class='muted'>" + esc(T(
        "Typical mistakes from the notes, plus questions you keep missing. Read the wrong version, then say the right "
        "one out loud.")) + "</p>" + ("".join(rows) or f"<p>{esc(T('No traps recorded yet.'))}</p>"))
    path = ws.site_dir / "traps.html"
    write_text(path, page(ws, title, body, crumb=title))
    return {"path": path, "count": n}


def build_lookup(ws: Workspace) -> dict:
    """Alphabetical index for open-book exams: where each term is in the book and in the notes."""
    use_language(ws)
    entries = []
    for ch in ws.chapters_in_scope():
        inv = ws.inventory(ch["id"])
        for it in inv["items"]:
            if it["kind"] in ("term", "equation"):
                name = it.get("display") or it.get("text") or it["id"]
                entries.append((name.casefold(), name, it.get("page", ""), ch["id"], it["id"], it["kind"]))
    entries.sort()
    rows = "".join(f"<tr><td>{esc(n)}</td><td>{esc(T('formula' if k == 'equation' else 'term'))}</td><td>p.{esc(p)}</td>"
                   f"<td><a href='{esc(c)}.html#{esc(i)}'>{esc(T('{c} notes', c=c))}</a></td></tr>"
                   for _, n, p, c, i, k in entries)
    title = T("Lookup index")
    heads = "".join(f"<th>{esc(T(h))}</th>" for h in ("Term", "Type", "Book", "Notes"))
    body = (f"<h1>{esc(title)}</h1><p class='muted'>" +
            esc(T("For open-book exams: find any term fast, in the book and in your notes.")) +
            f"</p><div class='scroll'><table><tr>{heads}</tr>" + rows + "</table></div>")
    path = ws.site_dir / "lookup.html"
    write_text(path, page(ws, title, body, crumb=title))
    return {"path": path, "count": len(entries)}
