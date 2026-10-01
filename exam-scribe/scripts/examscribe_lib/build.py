"""Build every output: chapter pages, review sheets, index, practice, cheat sheet, deck, calendar, report, exports."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from .common import Workspace, read_text, today, write_text
from .config import get_key
from .esm import citations, is_unsure, strip_citations
from .lint import _split_cells
from .materials import conflicts_by_term
from .notes import ChapterNotes, load_chapter
from .render import badge, esc, inline, page, render_chapter, render_review_sheet, stars_html
from .ui import FORMATS, POLICIES, T, answer_text, use_language


def build_chapter(ws: Workspace, cid: str) -> dict:
    from .media import ensure_chapter_media
    from .priority import compute_priorities
    if not ws.state.get("plan", {}).get("sections"):
        compute_priorities(ws)
    ensure_chapter_media(ws, ws.chapter(cid))
    use_language(ws)
    notes = load_chapter(ws, cid)
    path = render_chapter(ws, notes, conflicts_by_term(ws), ws.state.get("plan", {}))
    render_review_sheet(ws, notes)
    export_obsidian(ws, notes)
    from .anki import build_deck
    deck = build_deck(ws)
    render_index(ws)
    c = notes.trust.get("counts", {})
    q = notes.trust.get("questions", {})
    qok = sum(1 for v in q.values() if v["status"] == "ok")
    summary = T("{ok} claims verified, {warn} marked for a human check; {qok} of {qn} answer keys confirmed.",
                ok=c.get("ok", 0), warn=c.get("warn", 0), qok=qok, qn=len(q))
    return {"url": path.as_uri(), "summary": summary, "path": str(path)}


def build_all(ws: Workspace, pdf: bool = False) -> dict:
    from .anki import build_deck
    from .practice import build_cheat_sheet, build_lookup, build_mixed_sets, build_mock_exam, build_traps, question_pool
    from .priority import compute_priorities
    from .report import render_report
    from .studyplan import build_schedule, write_calendar
    use_language(ws)
    compute_priorities(ws)
    events = build_schedule(ws)
    cal = write_calendar(ws, events)
    built = []
    from .media import ensure_chapter_media
    for ch in ws.chapters_in_scope():
        if ws.draft_dir(ch["id"]).exists() and any(ws.draft_dir(ch["id"]).glob("*.md")):
            ensure_chapter_media(ws, ch)
            notes = load_chapter(ws, ch["id"])
            render_chapter(ws, notes, conflicts_by_term(ws), ws.state.get("plan", {}))
            render_review_sheet(ws, notes)
            export_obsidian(ws, notes)
            built.append(ch["id"])
    pool = question_pool(ws)
    mixed = build_mixed_sets(ws, pool, events)
    mock = build_mock_exam(ws, pool)
    cheat = build_cheat_sheet(ws)
    traps = build_traps(ws)
    lookup = build_lookup(ws) if (get_key(ws.config, "exam.book_policy") or "closed") != "closed" else None
    deck = build_deck(ws)
    rep = render_report(ws)
    index = render_index(ws)
    pdfs = export_pdfs(ws) if pdf else []
    t = rep["totals"]
    lines = ["Tell the user their study materials are ready:",
             f"  Start here (course map, today's plan, all links): {index.as_uri()}",
             f"  Chapters built: {', '.join(built) or 'none yet'}",
             f"  Flashcards: {deck['apkg'] or deck['tsv']} ({deck['cards']} cards"
             + (f"; {deck['held_back']} held back until verified" if deck["held_back"] else "") + ")",
             f"  Study calendar (import into any calendar app): {cal['ics']}",
             f"  Mock exam: {mock['path'].as_uri() if mock else 'not enough verified questions yet'}",
             f"  Cheat sheet: {cheat['path'].as_uri()}   Traps: {traps['path'].as_uri()}",
             f"  Mixed practice sets: {len(mixed)}" + (f"   Lookup index: {lookup['path'].as_uri()}" if lookup else ""),
             f"  Verification report: {rep['path'].as_uri()}",
             f"  Quality: {t['ok']} claims verified; {t['warn']} marked for a human check; answer keys confirmed: "
             f"{t['q_ok']}, disputed: {t['q_warn']}."]
    if pdfs:
        lines.append(f"  PDFs: {len(pdfs)} file(s) in {ws.export_dir / 'pdf'}")
    lines.append("Mention that items marked \u26a0 should be checked against the book before relying on them.")
    ws.state["built_all"] = True
    ws.save_state()
    return {"message": "\n".join(lines), "index": index}


def render_index(ws: Workspace) -> Path:
    use_language(ws)
    plan = ws.state.get("plan", {})
    secs = plan.get("sections", {})
    chapters = ws.chapters_in_scope()
    nodes, edges = [], []
    for c in chapters:
        st = max([s["stars"] for s in secs.values() if s["chapter"] == c["id"]] or [0])
        label = f"{c['id']} {c['title'][:28]}" + (" " + "\u2605" * st if st else "")
        safe = re.sub(r"[^\w .,:()\u2605-]", " ", label)
        node_id = c["id"].replace("-", "_")
        nodes.append(f'{node_id}["{safe}"]')
        try:
            for d in ws.inventory(c["id"]).get("depends_on", []):
                if any(x["id"] == d["chapter"] for x in chapters):
                    edges.append(f'{d["chapter"].replace("-", "_")} --> {c["id"].replace("-", "_")}')
        except Exception:
            pass
    graph = "graph LR\n  " + "\n  ".join(nodes + edges) if nodes else ""
    cards = []
    for c in chapters:
        cs = ws.state.get("chapters", {}).get(c["id"], {})
        f = ws.site_dir / f"{c['id']}.html"
        info = cs.get("built_info", {})
        status = info.get("summary", T("not built yet")) if f.exists() else T("not written yet")
        t_notes, t_review, t_soon = esc(T("Notes")), esc(T("Review sheet")), esc(T("coming soon"))
        links = (f'<a href="{c["id"]}.html">{t_notes}</a> \u00b7 <a href="review-{c["id"]}.html">{t_review}</a>'
                 if f.exists() else f'<span class="muted">{t_soon}</span>')
        sec_lines = "".join(f'<div>{stars_html(s["stars"])} {esc(sid)} {esc(s["title"])}</div>'
                            for sid, s in secs.items() if s["chapter"] == c["id"])
        cards.append(f'<div class="card"><div class="head"><span class="title">{esc(c["id"])} {esc(c["title"])}</span>'
                     f'</div>{sec_lines}<div class="meta">{esc(status)}</div><div>{links}</div></div>')
    events = ws.state.get("schedule", {}).get("events", [])
    t = today().isoformat()
    upcoming = [e for e in events if e["date"] >= t][:12]
    today_style = ' style="font-weight:600"'
    rows = "".join(f"<tr{today_style if e['date'] == t else ''}><td>{esc(e['date'])}</td>"
                   f"<td>{esc(e['title'])}</td><td>{esc(str(e.get('minutes') or ''))}</td><td class='muted'>"
                   f"{esc(e.get('detail', ''))}</td></tr>" for e in upcoming)
    extra_links = [("mock-exam.html", "Mock exam"), ("cheat-sheet.html", "Cheat sheet"), ("traps.html", "Traps"),
                   ("lookup.html", "Lookup index"), ("review-due.html", "Due today"), ("report.html", "Verification report")]
    links = " \u00b7 ".join(f'<a href="{h}">{esc(T(n))}</a>' for h, n in extra_links if (ws.site_dir / h).exists())
    practice = sorted(ws.site_dir.glob("practice-*.html"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 0))
    if practice:
        links += " \u00b7 " + esc(T("Mixed practice:")) + " " + ", ".join(f'<a href="{p.name}">{re.sub(r"[^0-9]", "", p.stem)}</a>'
                                                          for p in practice)
    exam = get_key(ws.config, "exam.date")
    downloads = []
    for name, label in (("flashcards.apkg", "Anki deck"), ("flashcards.tsv", "Flashcards (TSV)"),
                        ("study-plan.ics", "Calendar (.ics)")):
        if (ws.export_dir / name).exists():
            downloads.append(f'<a href="../export/{name}">{esc(T(label))}</a>')
    dot = " \u00b7 "
    downloads_html = dot.join(downloads)
    formats = ", ".join(T(FORMATS.get(x, x)) for x in (get_key(ws.config, "exam.formats") or []))
    policy = get_key(ws.config, "exam.book_policy") or ""
    meta = T("Exam: {date} \u00b7 formats: {formats} \u00b7 {policy}", date=exam or T("date not set"), formats=formats,
             policy=T(POLICIES.get(policy, policy)) if policy else "")
    recall = "<strong>" + esc(T("Recall")) + "</strong>"
    steps = [esc(T("Follow the plan below: each day says what to do and for how long.")),
             esc(T("New chapter: take the pretest, read the notes, then do the self-test in {recall} mode.",
                   recall="\x00")).replace("\x00", recall),
             esc(T("Review days: flashcards first, then the review sheet with answers hidden.")),
             esc(T("Export your results from any quiz page and log them (mistakes import), so missed questions come back.")),
             esc(T("Items marked \u26a0 are not fully verified: check them in the book before relying on them."))]
    heads = "".join(f"<th>{esc(T(h))}</th>" for h in ("Date", "Task", "Min", "How"))
    body = (f"<h1>{esc(ws.config.get('title') or T('Exam prep'))}</h1>"
            f"<div class='meta'>{esc(meta)}</div><p>{links}</p><p class='muted'>{downloads_html}</p>"
            f"<h2>{esc(T('How to use this'))}</h2><ol>" + "".join(f"<li>{x}</li>" for x in steps) + "</ol>"
            f"<h2>{esc(T('Plan'))}</h2>" + (f"<div class='scroll'><table><tr>{heads}</tr>{rows}</table></div>" if rows
                                         else f"<p class='muted'>{esc(T('Run build to create the plan.'))}</p>") +
            f"<h2>{esc(T('Chapters'))}</h2>" + (f"<pre class='mermaid'>{esc(graph)}</pre>" if edges else "") +
            f"<div class='grid2'>{''.join(cards)}</div>")
    path = ws.site_dir / "index.html"
    write_text(path, page(ws, ws.config.get("title") or T("Exam prep"), body, crumb=T("Course overview"),
                          mermaid=bool(edges)))
    return path


def export_obsidian(ws: Workspace, notes: ChapterNotes) -> Path:
    """Obsidian-flavored Markdown: callouts, foldable answers, page references."""
    sym = {"ok": "\u2705", "warn": "\u26a0\ufe0f", "pending": "\u25cb", "": ""}

    def cites_md(v: str) -> str:
        v = re.sub(r'\[p\.\s?([^\]:"]+?)\s*:\s*"(.+?)"\s*\]', lambda m: f"(p. {m.group(1).strip()})", v)
        return re.sub(r"\(\s*covers?\s*:[^)]*\)", "", v).strip()
    ch = notes.ch
    use_language(ws)
    colon = T(": ")
    out = [f"# {ch['title']}", "", "> " + T("Generated by ExamScribe from the book. {ok} verified, {warn} check, {pending} "
                                         "not yet verified, {ai} AI-added.", ok=sym["ok"], warn=sym["warn"],
                                         pending=sym["pending"], ai="\U0001f4a1"), ""]
    ov = notes.chapter_block("overview")
    if ov:
        out += [f"> [!abstract] {T('Big picture')}", f"> {cites_md(ov.blk.value('answers'))}", f"> {cites_md(ov.blk.value('big-picture'))}", ""]
    for s in notes.inv["sections"]:
        out += [f"## {s['id']} {s['title']}", ""]
        for nb in notes.section_blocks(s["id"]):
            b = nb.blk
            if b.get("skip"):
                continue
            st = sym[notes.block_status(nb)]
            if nb.kind == "concept":
                d = citations(b.value("definition"))
                out.append(f"> [!note]- {b.value('term')} {st}")
                if d:
                    out.append(f"> \u201c{d[0].quote}\u201d (p. {d[0].page})")
                for key, label in (("plain", "In plain words"), ("why", "Why"), ("example", "Example")):
                    for f in b.all(key):
                        if not is_unsure(f.value):
                            out.append(f"> **{T(label)}{colon}** {cites_md(f.value)}")
                for f in b.all("misconception"):
                    m = re.match(r"^\s*wrong\s*:\s*(?P<w>.+?)\s*\|\s*right\s*:\s*(?P<r>.+)$", f.value, re.I | re.S)
                    text = f"\u2717 {m.group('w')} \u2192 \u2713 {cites_md(m.group('r'))}" if m else cites_md(f.value)
                    out.append(f"> **{T('Common mistake')}{colon}** {text}")
                for f in b.fields:
                    if f.key.startswith("ai-") and f.value.strip():
                        out.append(f"> \U0001f4a1 *{T('AI-added')}{colon}* {f.value}")
                out.append("")
            elif nb.kind == "formula":
                out += [f"> [!info]- {b.value('name')} {st}", f"> $${b.value('latex')}$$",
                        f"> **{T('Symbols')}{colon}** {cites_md(b.value('where'))}",
                        f"> **{T('Holds when')}{colon}** {cites_md(b.value('holds-when'))}", ""]
            elif nb.kind == "worked-example":
                out += [f"> [!example]- {b.value('title')} {st}", f"> {cites_md(b.value('problem'))}"]
                out += [f"> {i}. {cites_md(f.value)}" for i, f in enumerate(b.all("step"), start=1)]
                out += [f"> **{T('Answer')}{colon}** {cites_md(b.value('result'))}", ""]
            elif nb.kind == "figure":
                out += [f"> [!quote] {b.id} {st}", f"> {cites_md(b.value('what'))}", ""]
    mk = notes.chapter_block("must-know")
    if mk:
        out += [f"## {T('Must know')}", ""] + [f"- {cites_md(f.value)}" for f in mk.blk.all("point")] + [""]
    qs = notes.questions()
    if qs:
        out += [f"## {T('Self-test')}", ""]
        for q in qs:
            b = q.blk
            out.append(f"> [!question]- {b.value('ask')}")
            if b.value("type") == "mcq":
                for c in "abcd":
                    if b.get(f"option {c}"):
                        out.append(f"> {c.upper()}. {b.value('option ' + c)}")
            out += [f"> **{T('Answer')}{colon}** {answer_text(b.value('type'), b.value('answer'))}",
                    f"> {cites_md(b.value('why'))}", ""]
    path = ws.export_dir / "obsidian" / f"{ch['id']}.md"
    write_text(path, "\n".join(out) + "\n")
    return path


def _browser() -> str | None:
    cands = [shutil.which(n) for n in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser")]
    cands += [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    for c in cands:
        if c and Path(c).exists():
            return c
    return None


def export_pdfs(ws: Workspace) -> list[Path]:
    exe = _browser()
    if not exe:
        return []
    out_dir = ws.export_dir / "pdf"
    out_dir.mkdir(parents=True, exist_ok=True)
    done = []
    for html_file in sorted(ws.site_dir.glob("*.html")):
        if html_file.name.startswith(("practice-", "review-due", "mock-exam")):
            continue
        target = out_dir / (html_file.stem + ".pdf")
        try:
            subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                            "--virtual-time-budget=8000", f"--print-to-pdf={target}", html_file.as_uri()],
                           check=False, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if target.exists():
                done.append(target)
        except (OSError, subprocess.TimeoutExpired):
            continue
    return done
