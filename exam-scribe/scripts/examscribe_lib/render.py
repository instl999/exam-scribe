"""HTML study pages built from verified drafts.

Every page is self-contained (CSS/JS inlined; KaTeX and Mermaid load from a CDN
and degrade to plain text offline). Trust badges come only from the scripts:
  ✓ verified   ⚠ check this (with the reason)   ○ not yet verified   💡 AI-added
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

from .common import ASSETS_DIR, Workspace, key_of, read_text, slugify, write_text
from .esm import CITE_RE, COVERS_RE, citations, covers, is_unsure, strip_citations
from .lint import _split_cells
from .notes import ChapterNotes, NoteBlock
from .schema import LETTERS
from .tiers import AI_FIELD_LABELS
from .ui import T, flag_reason, js_strings, reason, use_language

try:
    from markdown_it import MarkdownIt
    _MD = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})
except ImportError:  # pragma: no cover
    _MD = None

KATEX = "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist"
MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs"
BADGE = {"ok": ("✓", "verified against the book"), "warn": ("⚠", "check this"),
         "pending": ("○", "not verified yet"), "ai": ("\U0001f4a1", "AI-added, not from the book")}
BLOOM_ORDER = ["remember", "understand", "apply", "analyze", "evaluate"]


def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


BLANK_HTML = '<span class="blank-slot" aria-label="blank">______</span>'


def inline(text: str) -> str:
    """Inline Markdown (bold/italic/code) with $math$ and ____ blanks protected; HTML is escaped."""
    # placeholders use private-use characters: markdown-it replaces NUL and would destroy them
    maths: list[str] = []

    def hold(m: re.Match) -> str:
        maths.append(m.group(0))
        return f"M{len(maths) - 1}"
    t = re.sub(r"\$[^$\n]+\$", hold, text or "")
    t = re.sub(r"_{3,}", "B", t)
    if _MD is not None:
        out = _MD.renderInline(t)
    else:
        out = esc(t)
    out = out.replace("B", BLANK_HTML)
    return re.sub("M(\\d+)", lambda m: esc(maths[int(m.group(1))]), out)


def cite_chip(page: str, quote: str) -> str:
    return (f'<span class="cite" tabindex="0">p.{esc(page)}<span class="tip">“{esc(quote)}” '
            f'<span class="muted">(p.{esc(page)})</span></span></span>')


def value_html(value: str) -> str:
    """Claim text + citation chips (covers markers removed)."""
    value = COVERS_RE.sub("", value or "")
    out, pos = [], 0
    for m in CITE_RE.finditer(value):
        out.append(inline(value[pos:m.start()]))
        out.append(cite_chip(m.group("page").strip(), m.group("quote").strip()))
        pos = m.end()
    out.append(inline(value[pos:]))
    return "".join(out).strip()


def badge(status: str, reasons: list[str] | None = None) -> str:
    if not status:
        return ""
    sym, title = BADGE[status]
    tip = T(title) + (T(": ") + "; ".join(flag_reason(r) for r in reasons) if reasons else "")
    return f'<span class="badge {status}" title="{esc(tip)}" aria-label="{esc(tip)}">{sym}</span>'


def _lead(label: str) -> str:
    """A label followed by its text: no space after a full-width colon (Chinese, Japanese)."""
    return esc(label) + ("" if label.endswith(("：", "︰")) else " ")


def stars_html(n: int | None) -> str:
    if not n:
        return ""
    tip = esc(T("priority {n} of 3", n=n))
    return f'<span class="stars" title="{tip}">{"★" * n}{"☆" * (3 - n)}</span>'


def page(ws: Workspace, title: str, body: str, crumb: str = "", mermaid: bool = False, exam: bool = False,
         default_mode: str | None = None) -> str:
    use_language(ws)
    css = read_text(ASSETS_DIR / "study.css")
    js = read_text(ASSETS_DIR / "study.js")
    lang = ws.config.get("output", {}).get("language") or "en"
    course = slugify(ws.config.get("title", "course"), 30)
    mode_attr = f' data-default-mode="{default_mode}"' if default_mode else ""
    ui_attr = esc(js_strings())
    t_over, t_course, t_mode = esc(T("Course overview")), esc(T("⌂ Course")), esc(T("Study mode"))
    t_read, t_recall, t_theme = esc(T("Read")), esc(T("Recall")), esc(T("Light/dark"))
    head_extra = (f'<link rel="stylesheet" href="{KATEX}/katex.min.css">'
                  f'<script defer src="{KATEX}/katex.min.js"></script>'
                  f'<script defer src="{KATEX}/contrib/auto-render.min.js" onload="try{{renderMathInElement(document.body,'
                  '{delimiters:[{left:\'$$\',right:\'$$\',display:true},{left:\'$\',right:\'$\',display:false}],'
                  'throwOnError:false})}catch(e){}"></script>')
    mm = ""
    if mermaid:
        mm = ('<script type="module">import mermaid from "' + MERMAID + '";'
              'const dark=(document.documentElement.getAttribute("data-theme")||'
              '(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"))==="dark";'
              'mermaid.initialize({startOnLoad:true,theme:dark?"dark":"default",securityLevel:"strict"});</script>')
    return f"""<!doctype html>
<html lang="{esc(lang)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title><style>{css}</style>{head_extra}</head>
<body data-course="{esc(course)}" data-ui="{ui_attr}"{mode_attr}{' data-exam' if exam else ''}>
<header class="top"><div class="bar"><a href="index.html" class="btn noprint" title="{t_over}">{t_course}</a>
<span class="crumb">{esc(crumb or title)}</span>
<span class="seg noprint" role="group" aria-label="{t_mode}"><button class="btn" data-set-mode="read">{t_read}</button><button class="btn" data-set-mode="recall">{t_recall}</button></span>
<button class="btn noprint" id="theme-toggle" title="{t_theme}">◐</button></div></header>
<main>{body}</main>{mm}<script>{js}</script></body></html>
"""


def legend() -> str:
    return ('<div class="legend"><span>' + badge("ok") + ' ' + esc(T("verified against the book")) +
            '</span><span>' + badge("warn") + ' ' + esc(T("check this (hover for why)")) + '</span><span>' +
            badge("pending") + ' ' + esc(T("not verified yet")) + '</span><span>' + badge("ai") + ' ' +
            esc(T("AI-added memory aid, not from the book")) + '</span><span><span class="cite">p.12</span> ' +
            esc(T("book page (hover for the quote)")) + '</span></div>')


# ============================================================================ blocks

def _field_rows(notes: ChapterNotes, nb: NoteBlock, keys: list[tuple[str, str]], ans: bool = True) -> str:
    out = []
    occ: dict[str, int] = {}
    for f in nb.blk.fields:
        label = dict(keys).get(f.key)
        if label is None:
            continue
        label = T(label)
        n = occ.get(f.key, 0)
        occ[f.key] = n + 1
        st, reasons = notes.field_status(nb, f.key, n)
        v = f.value.strip()
        if is_unsure(v):
            note = esc(T("Not in the book (writer marked it UNSURE: {reason})", reason=v[6:].lstrip(": ")))
            out.append(f'<div class="row why-flag"><span class="label">{esc(label)}</span>{note}</div>')
            continue
        if f.key == "misconception":
            m = re.match(r"^\s*wrong\s*:\s*(?P<w>.+?)\s*\|\s*right\s*:\s*(?P<r>.+)$", v, re.I | re.S)
            if m:
                out.append(f'<div class="row"><span class="label">{esc(T("Common mistake"))}</span><span class="wrong">✗ '
                           f'{inline(m.group("w"))}</span><br><span class="right">✓ {value_html(m.group("r"))}</span> '
                           f'{badge(st, reasons)}</div>')
                continue
        out.append(f'<div class="row"><span class="label">{esc(label)}</span>{value_html(v)} {badge(st, reasons)}</div>')
    return "".join(out)


def _ai_rows(nb: NoteBlock) -> str:
    out = []
    for f in nb.blk.fields:
        if f.key.startswith("ai-") and f.value.strip() and not is_unsure(f.value):
            label = esc(T(AI_FIELD_LABELS.get(f.key, "AI")))
            out.append(f'<div class="ai-box">{badge("ai")} <span class="label">{label}'
                       f' — {esc(T("AI-added, not from the book"))}</span> {inline(f.value)}</div>')
    return "".join(out)


def _img(ws: Workspace, rel_path: str | None, alt: str, site_dir: Path) -> str:
    if not rel_path:
        return ""
    src = ws.root / rel_path
    if not src.exists():
        return ""
    target = site_dir / "img" / src.name
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or target.stat().st_mtime < src.stat().st_mtime:
        target.write_bytes(src.read_bytes())
    return f'<img src="img/{esc(src.name)}" alt="{esc(alt)}" loading="lazy">'


def concept_card(ws: Workspace, notes: ChapterNotes, nb: NoteBlock, conflicts: dict, items: dict, stars: int | None) -> str:
    b = nb.blk
    term = b.value("term")
    orig = b.value("term-original")
    st = notes.block_status(nb)
    cue = b.value("cue") or T("What is {term}?", term=term)
    parts = [f'<div class="card concept" id="{esc(b.id)}"><div class="head"><span class="kind">{esc(T("Key term"))}</span>'
             f'<span class="title">{esc(term)}</span>' + (f' <span class="muted">({esc(orig)})</span>' if orig else "") +
             f' {badge(st)} {stars_html(stars)}</div><div class="cue">{_lead(T("Recall:"))}{inline(cue)}</div>'
             f'<div class="reveal-hint">{esc(T("Say the answer out loud, then click the blurred text to check."))}</div>'
             '<div class="ans">']
    d = b.get("definition")
    if d is not None and not is_unsure(d.value):
        cs = citations(d.value)
        sst, rs = notes.field_status(nb, "definition", 0)
        if cs:
            parts.append(f'<blockquote class="book">{inline(cs[0].quote)} {cite_chip(cs[0].page, cs[0].quote)} '
                         f'{badge(sst, rs)}</blockquote>')
    elif d is not None:
        parts.append(f'<div class="why-flag">{esc(T("The writer could not find the book’s definition (UNSURE)."))}</div>')
    parts.append(_field_rows(notes, nb, [("definition-translation", "Translation"), ("plain", "In plain words"),
                                         ("why", "Why it matters"), ("example", "Example"),
                                         ("misconception", "Common mistake")]))
    for f in b.all("figure"):
        it = items.get(f.value.strip())
        if it:
            parts.append(f'<figure>{_img(ws, it.get("image"), it.get("caption", ""), ws.site_dir)}'
                         f'<figcaption>{esc(it.get("caption", ""))} (p.{esc(it.get("page", ""))})</figcaption></figure>')
    parts.append(_ai_rows(nb))
    for c in conflicts.get(b.id, []):
        what = T("uses different notation" if c["verdict"] == "DIFFERENT_NOTATION" else "says something different")
        lead = esc(T("Your instructor’s material ({material}) {what}:", material=c["material"], what=what))
        follow = esc(T("For the exam, follow your instructor."))
        parts.append(f'<div class="instructor">⚠ {lead} '
                     f'{esc(c["slides"])}. {esc(c["explain"])} <strong>{follow}</strong></div>')
    parts.append("</div></div>")
    return "".join(parts)


def formula_card(ws: Workspace, notes: ChapterNotes, nb: NoteBlock, items: dict, stars: int | None) -> str:
    b = nb.blk
    it = items.get(b.id, {})
    st = notes.block_status(nb)
    fst = notes.trust.get("formulas", {}).get(b.id, {})
    latex = b.value("latex")
    printed = _img(ws, it.get("image"), T("formula as printed in the book"), ws.site_dir)
    num = f" ({esc(it.get('number'))})" if it.get("number") else ""
    parts = [f'<div class="card formula" id="{esc(b.id)}"><div class="head"><span class="kind">{esc(T("Formula"))}{num}</span>'
             f'<span class="title">{inline(b.value("name"))}</span> {badge(st)} {stars_html(stars)}</div>'
             f'<div class="cue">{esc(T("Recall: write the formula and say when it holds."))}</div>'
             f'<div class="reveal-hint">{esc(T("Click the blurred text to check."))}</div><div class="ans">'
             f'<div class="math-block">$${esc(latex)}$$ {badge(fst.get("status", ""), [fst["reason"]] if fst.get("reason") else None)}</div>']
    if printed:
        parts.append(f'<div class="printed"><span class="label">{esc(T("As printed"))}</span>{printed}'
                     f'<span class="muted">p.{esc(it.get("page", ""))}</span></div>')
    parts.append(_field_rows(notes, nb, [("where", "Symbols"), ("holds-when", "Holds when"), ("example", "Example")]))
    chk = b.value("check")
    if chk:
        forms = [chk] + [f.value for f in b.all("rearrange")]
        parts.append('<div class="row"><span class="label">' + esc(T("Forms (checked by script)")) + '</span>' +
                     " &nbsp;•&nbsp; ".join(f"<code>{esc(x)}</code>" for x in forms) + "</div>")
    parts.append(_ai_rows(nb))
    parts.append("</div></div>")
    return "".join(parts)


def _steps_html(b, fade: bool) -> str:
    steps = [f.value for f in b.all("step")]
    calcs = [f.value for f in b.all("calc")]
    n_show = max(1, len(steps) // 2) if fade else len(steps)
    lis = []
    for i, s in enumerate(steps):
        if fade and i >= n_show:
            lis.append(f'<li><span class="blank">{value_html(s)}</span></li>')
        else:
            lis.append(f"<li>{value_html(s)}</li>")
    out = f'<ol class="steps">{"".join(lis)}</ol>'
    if calcs and not fade:
        rows = "".join(f"<tr><td>{esc(c.split('=>')[0].strip())}</td><td>{esc(c.split('=>')[1].strip()) if '=>' in c else ''}</td></tr>"
                       for c in calcs)
        out += (f'<div class="scroll"><table class="calc-table"><tr><th>{esc(T("Calculation"))}</th>'
                f'<th>{esc(T("Result (recomputed by the script ✓)"))}</th></tr>{rows}</table></div>')
    return out


def example_card(notes: ChapterNotes, nb: NoteBlock) -> str:
    b = nb.blk
    st = notes.block_status(nb)
    parts = [f'<div class="card example" id="{esc(b.id)}"><div class="head"><span class="kind">{esc(T("Worked example"))}</span>'
             f'<span class="title">{inline(b.value("title"))}</span> {badge(st)}</div>',
             _field_rows(notes, nb, [("source", "Source"), ("problem", "Problem")]),
             '<div class="ans">', _steps_html(b, fade=False), _field_rows(notes, nb, [("result", "Answer")]), "</div>",
             f'<div class="card faded"><div class="head"><span class="kind">{esc(T("Your turn"))}</span>'
             f'<span class="title">{esc(T("Finish it yourself"))}</span></div><p class="muted">'
             f'{esc(T("Same problem: the first steps are given. Work out the rest on paper, then check."))}</p>',
             _steps_html(b, fade=True),
             f'<button class="btn show-steps noprint">{esc(T("Show the remaining steps"))}</button></div></div>']
    return "".join(parts)


def figure_card(ws: Workspace, notes: ChapterNotes, nb: NoteBlock, items: dict) -> str:
    b = nb.blk
    it = items.get(b.id, {})
    st = notes.block_status(nb)
    img = _img(ws, it.get("image"), it.get("caption", b.id), ws.site_dir)
    return (f'<div class="card figure" id="{esc(b.id)}"><div class="head"><span class="kind">'
            f'{esc(T("Table" if b.id.startswith("TAB") else "Figure"))} {esc(it.get("number", ""))}</span> {badge(st)}</div>'
            f'<figure>{img}<figcaption>{esc(it.get("caption", ""))} <span class="cite">p.{esc(it.get("page", ""))}</span>'
            f'</figcaption></figure>' + _field_rows(notes, nb, [("what", "What it shows"), ("look-for", "Look for")]) +
            "</div>")


def generic_card(notes: ChapterNotes, nb: NoteBlock, title_key: str, rows: list[tuple[str, str]], kind: str) -> str:
    b = nb.blk
    st = notes.block_status(nb)
    return (f'<div class="card" id="{esc(b.id)}"><div class="head"><span class="kind">{esc(T(kind))}</span>'
            f'<span class="title">{inline(b.value(title_key))}</span> {badge(st)}</div><div class="ans">' +
            _field_rows(notes, nb, rows) + "</div></div>")


def trace_card(notes: ChapterNotes, nb: NoteBlock) -> str:
    b = nb.blk
    st = notes.block_status(nb)
    return (f'<div class="card" id="{esc(b.id)}"><div class="head"><span class="kind">{esc(T("Trace the code"))}</span>'
            f'<span class="title">{inline(b.value("ask"))}</span> {badge(st)}</div><pre><code>{esc(b.code or "")}</code></pre>'
            f'<div class="ans"><div class="row"><span class="label">{esc(T("Output"))}</span><code>{esc(b.value("output"))}</code></div>' +
            _field_rows(notes, nb, [("why", "Why")]) + "</div></div>")


def compare_table(notes: ChapterNotes, nb: NoteBlock, names: dict) -> str:
    b = nb.blk
    if b.get("skip"):
        return ""
    items = [x.strip() for x in _split_cells(b.value("items"))]
    heads = [names.get(x, x) for x in items]
    rows = []
    for i, f in enumerate(b.all("row")):
        cells = _split_cells(f.value)
        st, rs = notes.field_status(nb, "row", i)
        tds = "".join(f"<td>{value_html(c)}</td>" for c in cells[1:])
        rows.append(f"<tr><th>{inline(cells[0])} {badge(st, rs)}</th>{tds}</tr>")
    return (f'<div class="card" id="{esc(b.id)}"><div class="head"><span class="kind">{esc(T("Don’t mix these up"))}</span>'
            f'<span class="title">{esc(" vs ".join(heads))}</span></div><div class="scroll ans"><table><tr><th></th>' +
            "".join(f"<th>{esc(h)}</th>" for h in heads) + "</tr>" + "".join(rows) + "</table></div></div>")


def mermaid_map(notes: ChapterNotes, nb: NoteBlock, names: dict) -> str:
    b = nb.blk
    nodes, edges, lines, styles = {}, [], [], []
    for i, f in enumerate(b.all("link")):
        m = re.match(r"^\s*(?P<a>\S+)\s*->\s*(?P<b>\S+)\s*\|\s*(?P<rel>.+)$", f.value)
        if not m:
            continue
        a, c = m.group("a"), m.group("b")
        for x in (a, c):
            nodes.setdefault(x, f"n{len(nodes)}")
        rel_txt = strip_citations(m.group("rel"))
        short = rel_txt if len(rel_txt) <= 34 else rel_txt[:32] + "…"
        st, rs = notes.field_status(nb, "link", i)
        edges.append(f'{nodes[a]} -- "{_mm(short)}" --> {nodes[c]}')
        if st == "warn":
            styles.append(f"linkStyle {len(edges) - 1} stroke:#d97706,stroke-width:2px,stroke-dasharray:4 3")
        lines.append(f"<li>{esc(names.get(a, a))} → {esc(names.get(c, c))}: {value_html(m.group('rel'))} "
                     f"{badge(st, rs)}</li>")
    if not edges:
        return ""
    decl = [f'{nid}["{_mm(names.get(x, x))}"]' for x, nid in nodes.items()]
    graph = "graph LR\n  " + "\n  ".join(decl + edges + styles)
    return (f'<div class="card"><div class="head"><span class="kind">{esc(T("Concept map"))}</span><span class="title">'
            f'{esc(T("How the ideas connect"))}</span> <span class="muted">{esc(T("(AI-drawn; every arrow is a cited claim)"))}'
            f'</span></div>'
            f'<pre class="mermaid">{esc(graph)}</pre><ul>{"".join(lines)}</ul></div>')


def _mm(s: str) -> str:
    return re.sub(r'["\[\]{}<>|#;]', " ", s).strip()


# ============================================================================ questions

def question_html(nb_or_blk, status: str = "", number: int | None = None, show_meta: bool = True,
                  chapter: str = "") -> str:
    b = nb_or_blk.blk if isinstance(nb_or_blk, NoteBlock) else nb_or_blk
    qtype = b.value("type").lower()
    answer = b.value("answer").strip()
    ask = b.value("ask")
    qid = b.id
    data_answer = answer
    body = ""
    if qtype == "mcq":
        data_answer = answer.upper()[:1]
        opts = "".join(f'<button class="opt" data-letter="{c.upper()}"><strong>{c.upper()}.</strong> '
                       f'{inline(b.value(f"option {c}"))}</button>' for c in LETTERS if b.get(f"option {c}"))
        body = f'<div class="opts">{opts}</div>'
    elif qtype == "tf":
        data_answer = "T" if answer.lower().startswith("t") else "F"
        body = (f'<div class="opts"><button class="opt" data-letter="T">{esc(T("True"))}</button>'
                f'<button class="opt" data-letter="F">{esc(T("False"))}</button></div>')
    elif qtype == "numeric":
        m = re.match(r"\s*([-+]?[\d.,]+(?:[eE][-+]?\d+)?)\s*(?:\[(.*?)\])?", answer)
        num = m.group(1).replace(",", "") if m else answer
        unit = m.group(2) if m and m.group(2) else ""
        data_answer = num
        body = (f'<input type="text" inputmode="decimal" aria-label="{esc(T("Your answer"))}"> '
                f'<span class="muted">{esc(unit)}</span> <button class="btn check">{esc(T("Check"))}</button>')
    elif qtype == "cloze":
        body = (f'<input type="text" aria-label="{esc(T("Missing words"))}"> '
                f'<button class="btn check">{esc(T("Check"))}</button>')
    else:
        body = (f'<button class="btn show-answer">{esc(T("Show model answer"))}</button><div class="selfgrade noprint">'
                f'<button class="btn" data-grade="1">{esc(T("I got it"))}</button>'
                f'<button class="btn" data-grade="0">{esc(T("I missed it"))}</button></div>')
    accept = json.dumps([f.value for f in b.all("accept")])
    shown_answer = answer
    if qtype == "mcq" and b.get(f"option {data_answer.lower()}"):
        shown_answer = f"{data_answer}. {b.value('option ' + data_answer.lower())}"
    why_not = "".join(f'<div class="muted">{esc(T("{letter} is wrong:", letter=c.upper()))} '
                      f'{value_html(b.value("why-not " + c))}</div>' for c in LETTERS if b.get(f"why-not {c}"))
    calc = ""
    if b.all("calc"):
        calc = "<div class='calc'>" + "<br>".join(esc(f.value) for f in b.all("calc")) + "</div>"
    meta = ""
    if show_meta:
        meta = (f'<div class="qmeta"><span>{esc(qtype)}</span><span>{esc(b.value("bloom"))}</span>'
                + (f"<span>{esc(chapter)}</span>" if chapter else "") + f"<span>{esc(qid)}</span>{badge(status)}</div>")
    num = f"{number}. " if number else ""
    return (f'<div class="card q" data-qid="{esc(qid)}" data-type="{esc(qtype)}" data-answer="{esc(data_answer)}" '
            f"data-accept='{esc(accept)}'>{meta}<div class=\"ask\">{num}{inline(ask)}</div>{body}"
            f'<div class="feedback"><strong class="verdict"></strong> {_lead(T("Answer:"))}<strong>{inline(shown_answer)}</strong>'
            f'<div>{value_html(b.value("why"))}</div>{why_not}{calc}</div></div>')


# ============================================================================ chapter page

def render_chapter(ws: Workspace, notes: ChapterNotes, conflicts: dict, plan: dict) -> Path:
    ch, inv = notes.ch, notes.inv
    items = {it["id"]: it for it in inv["items"]}
    all_items = ws.all_inventory_items()
    names = {k: (v.get("display") or v.get("text") or k) for k, v in all_items.items()}
    secs = plan.get("sections", {})
    pages = [p for s in inv["sections"] for p in s["pages"]]
    deps = [d["chapter"] for d in inv.get("depends_on", [])]
    used_by = []
    for c in ws.chapters_in_scope():
        try:
            if ch["id"] in [d["chapter"] for d in ws.inventory(c["id"]).get("depends_on", [])]:
                used_by.append(c["id"])
        except Exception:
            pass
    use_language(ws)
    counts = notes.trust.get("counts", {})
    where = T("Chapter {n} · book pages {a}–{b} · needs: {needs} · used by: {used}", n=ch["number"],
              a=pages[0] if pages else "?", b=pages[-1] if pages else "?",
              needs=", ".join(deps) or T("nothing earlier"), used=", ".join(used_by) or T("no later chapter"))
    tally = T("{ok} claims verified · {warn} to check · {pending} not yet verified", ok=counts.get("ok", 0),
              warn=counts.get("warn", 0), pending=counts.get("pending", 0))
    out = [f'<h1>{esc(ch["title"])}</h1><div class="meta">{esc(where)}</div>', f'<div class="meta">{esc(tally)}</div>',
           legend()]
    toc = [f'<nav class="toc noprint"><a href="#pretest">{esc(T("Pretest"))}</a>']
    for s in inv["sections"]:
        toc.append(f'<a href="#sec-{esc(s["id"])}">{esc(s["id"])} {esc(s["title"][:28])}</a>')
    toc.append(f'<a href="#connections">{esc(T("Connections"))}</a><a href="#must-know">{esc(T("Must know"))}</a>'
               f'<a href="#self-test">{esc(T("Self-test"))}</a>'
               f'<a href="review-{esc(ch["id"])}.html">{esc(T("Review sheet"))}</a></nav>')
    out.append("".join(toc))
    ov = notes.chapter_block("overview")
    if ov:
        out.append('<div class="card"><div class="head"><span class="kind">' + esc(T("Big picture")) + '</span></div>' +
                   _field_rows(notes, ov, [("answers", "This chapter answers"), ("big-picture", "Where it fits")]) + "</div>")
    qs = notes.questions()
    qstatus = notes.trust.get("questions", {})
    pre = sorted(qs, key=lambda q: (qstatus.get(q.id, {}).get("status") != "ok",
                                    q.blk.value("type") not in ("mcq", "tf", "cloze"),
                                    BLOOM_ORDER.index(q.blk.value("bloom")) if q.blk.value("bloom") in BLOOM_ORDER else 9))[:3]
    out.append(f'<h2 id="pretest">{esc(T("Pretest"))}</h2><p class="muted">' + esc(T(
        "Try these before reading. Guessing wrong is fine: it makes the answer stick when you meet it below. You will "
        "see them again in the self-test.")) + '</p>')
    out += [question_html(q, qstatus.get(q.id, {}).get("status", ""), show_meta=False) for q in pre]
    for s in inv["sections"]:
        si = secs.get(s["id"], {})
        out.append(f'<h2 id="sec-{esc(s["id"])}">{esc(s["id"])} {esc(s["title"])} {stars_html(si.get("stars"))}</h2>')
        if si.get("reasons"):
            why = T("Priority because: {reasons}", reasons="; ".join(reason(r) for r in si["reasons"]))
            out.append(f'<div class="meta">{esc(why)}</div>')
        los = [it for it in inv["items"] if it["kind"] == "objective" and it.get("section") == s["id"]]
        if los:
            out.append('<div class="meta">' + esc(T("After this section you should be able to:")) + ' ' +
                       "; ".join(esc(lo["text"]) for lo in los) + "</div>")
        for nb in notes.section_blocks(s["id"]):
            if nb.blk.get("skip"):
                continue
            st = si.get("stars")
            if nb.kind == "concept":
                out.append(concept_card(ws, notes, nb, conflicts, all_items, st))
            elif nb.kind == "formula":
                out.append(formula_card(ws, notes, nb, items, st))
            elif nb.kind == "worked-example":
                out.append(example_card(notes, nb))
            elif nb.kind == "figure":
                out.append(figure_card(ws, notes, nb, items))
            elif nb.kind == "process":
                out.append(generic_card(notes, nb, "name", [("step", "Step")], "Process"))
            elif nb.kind == "timeline":
                out.append(generic_card(notes, nb, "name", [("event", "Event")], "Timeline"))
            elif nb.kind == "chain":
                out.append(generic_card(notes, nb, "name", [("link", "Cause → effect")], "Cause and effect"))
            elif nb.kind == "rule":
                out.append(generic_card(notes, nb, "name", [("rule", "Rule"), ("element", "Element"),
                                                             ("exception", "Exception"), ("case", "Case")], "Rule"))
            elif nb.kind == "trace":
                out.append(trace_card(notes, nb))
            elif nb.kind == "compare":
                out.append(compare_table(notes, nb, names))
    out.append(f'<h2 id="connections">{esc(T("Connections"))}</h2>')
    for nb in notes.of_kind("compare"):
        if nb.section is None:
            out.append(compare_table(notes, nb, names))
    mp = notes.chapter_block("map")
    if mp:
        out.append(mermaid_map(notes, mp, names))
    stg = notes.chapter_block("strategy")
    if stg:
        rows = []
        for i, f in enumerate(stg.blk.all("row")):
            cells = _split_cells(f.value)
            st, rs = notes.field_status(stg, "row", i)
            rows.append(f"<tr><td>{inline(cells[0])}</td><td>{value_html(' | '.join(cells[1:]))} {badge(st, rs)}</td></tr>")
        out.append(f'<div class="card"><div class="head"><span class="kind">{esc(T("Problem-solving"))}</span>'
                   f'<span class="title">{esc(T("When you see … do …"))}</span></div><div class="scroll ans"><table>'
                   + "".join(rows) + "</table></div></div>")
    for nb in notes.of_kind("outline"):
        out.append(generic_card(notes, nb, "prompt", [("thesis", "Thesis"), ("point", "Point"), ("counter", "Counterpoint")],
                                "Essay outline"))
    mk = notes.chapter_block("must-know")
    out.append(f'<h2 id="must-know">{esc(T("Must know"))}</h2>')
    if mk:
        lis = []
        for i, f in enumerate(mk.blk.all("point")):
            st, rs = notes.field_status(mk, "point", i)
            lis.append(f"<li>{value_html(f.value)} {badge(st, rs)}</li>")
        out.append(f'<div class="card"><ol class="ans">{"".join(lis)}</ol><div class="muted">'
                   f'{esc(T("Checked against the book’s own chapter summary."))}</div></div>')
    out.append(f'<h2 id="self-test">{esc(T("Self-test"))}</h2><p class="muted">' + esc(T(
        "From recall to analysis. Answers were confirmed by an independent solver unless marked otherwise.")) +
        f'</p><div class="noprint"><span id="score"></span> '
        f'<button class="btn" id="export-results">{esc(T("Export my results"))}</button></div>')
    by_level: dict[str, list] = {}
    for q in qs:
        by_level.setdefault(q.blk.value("bloom") or "other", []).append(q)
    n = 0
    for lvl in BLOOM_ORDER + ["other"]:
        if lvl not in by_level:
            continue
        out.append(f"<h3>{esc(T(lvl.capitalize()))}</h3>")
        for q in by_level[lvl]:
            n += 1
            out.append(question_html(q, qstatus.get(q.id, {}).get("status", ""), n))
    cited = sorted({p for v in notes.trust.get("claims", {}).values() for p in v.get("pages", [])},
                   key=lambda x: (len(x), x))
    out.append(f'<p class="meta">{esc(T("Book pages cited in these notes: {pages}", pages=", ".join(cited)))}</p>')
    path = ws.site_dir / f"{ch['id']}.html"
    write_text(path, page(ws, T("{title} — notes", title=ch["title"]), "\n".join(out), crumb=f"{ch['id']} · {ch['title']}",
                          mermaid=True))
    return path


def render_review_sheet(ws: Workspace, notes: ChapterNotes) -> Path:
    """Cornell-style: cue on the left, answer on the right (hidden in recall mode)."""
    use_language(ws)
    ch = notes.ch
    rows = []
    for nb in notes.blocks:
        b = nb.blk
        if b.get("skip"):
            continue
        st = notes.block_status(nb)
        if nb.kind == "concept":
            d = citations(b.value("definition"))
            ans = (f"“{inline(d[0].quote)}” {cite_chip(d[0].page, d[0].quote)}" if d else value_html(b.value("plain")))
            rows.append((b.value("cue") or T("What is {term}?", term=b.value("term")), ans, st))
            for f in b.all("misconception"):
                m = re.match(r"^\s*wrong\s*:\s*(?P<w>.+?)\s*\|\s*right\s*:\s*(?P<r>.+)$", f.value, re.I | re.S)
                if m:
                    rows.append((T("True or false: {s}", s=strip_citations(m.group("w"))),
                                 T("False.") + " " + value_html(m.group("r")), st))
        elif nb.kind == "formula":
            rows.append((T("Formula: {name}", name=b.value("name")),
                         f"$${esc(b.value('latex'))}$$ " + value_html(b.value("holds-when")), st))
        elif nb.kind == "compare":
            items = [x.strip() for x in _split_cells(b.value("items"))]
            names = ws.all_inventory_items()
            heads = [(names.get(x, {}).get("display") or x) for x in items]
            for f in b.all("row"):
                cells = _split_cells(f.value)
                if len(cells) >= 3:
                    rows.append((f"{' vs '.join(heads)}: {strip_citations(cells[0])}?",
                                 f"{esc(heads[0])}: {value_html(cells[1])}<br>{esc(heads[1] if len(heads) > 1 else '')}: "
                                 f"{value_html(cells[2])}", st))
        elif nb.kind == "must-know":
            for f in b.all("point"):
                rows.append((T("Must know"), value_html(f.value), st))
    trs = "".join(f"<tr><td>{inline(c)}</td><td><div class='ans'>{a}</div></td><td>{badge(s)}</td></tr>" for c, a, s in rows)
    body = (f'<h1>{esc(T("Review sheet — {title}", title=ch["title"]))}</h1><p class="muted">' + esc(T(
        "Cover the right column, answer from memory, then check. Recall mode blurs the answers for you.")) +
        f'</p><button class="btn noprint" id="hide-all">{esc(T("Hide all answers again"))}</button>'
        f'<div class="scroll"><table class="cornell"><tr><th>{esc(T("Cue"))}</th><th>{esc(T("Answer"))}</th><th></th></tr>'
        + trs + "</table></div>")
    path = ws.site_dir / f"review-{ch['id']}.html"
    write_text(path, page(ws, T("Review — {title}", title=ch["title"]), body, crumb=T("Review · {title}", title=ch["title"]),
                          default_mode="recall"))
    return path


def render_quiz_page(ws: Workspace, filename: str, title: str, intro: str, questions: list[tuple], timed: int | None = None) -> Path:
    """questions: list of (block, status, chapter_id)."""
    use_language(ws)
    qhtml = "".join(question_html(b, st, i + 1, chapter=chid) for i, (b, st, chid) in enumerate(questions))
    t_start, t_finish = esc(T("Start the timer ({m} min)", m=timed or 0)), esc(T("Finish and show answers"))
    t_export = esc(T("Export my results"))
    if timed:
        body = (f"<h1>{esc(title)}</h1><p>{intro}</p><p class='noprint'><button class='btn' id='start-exam'>{t_start}"
                f"</button> <span class='timer' id='timer' data-seconds='{timed * 60}'></span> "
                f"<button class='btn' id='finish-exam'>{t_finish}</button></p>"
                f"<div id='exam-body' hidden>{qhtml}</div><p><span id='score'></span> "
                f"<button class='btn noprint' id='export-results'>{t_export}</button></p>")
    else:
        body = (f"<h1>{esc(title)}</h1><p>{intro}</p><p class='noprint'><span id='score'></span> "
                f"<button class='btn' id='export-results'>{t_export}</button></p>{qhtml}")
    path = ws.site_dir / filename
    write_text(path, page(ws, title, body, crumb=title, exam=bool(timed)))
    return path
