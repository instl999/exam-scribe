"""Flashcards: an Anki deck (.apkg via genanki) plus a TSV that any flashcard app can import.

Cards follow the minimum-information principle: one fact per card, cloze
deletions for definitions, "true or false" cards for common mistakes, and
comparison cards for easily confused pairs. Only verified content becomes a
card unless the config says otherwise; flagged items are held back.
"""
from __future__ import annotations

import re

from .common import Workspace, sha, slugify, write_text
from .esm import citations, is_unsure, strip_citations
from .lint import _split_cells
from .notes import ChapterNotes, load_chapter
from .schema import LETTERS
from .ui import T, answer_text, use_language

try:
    import genanki
except ImportError:  # pragma: no cover
    genanki = None

CARD_CSS = """.card { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; font-size: 19px; text-align: left;
 color: #1d1c1a; background: #fbfaf7; line-height: 1.5; padding: 8px; }
.nightMode .card, .card.nightMode { color: #ebe8e1; background: #1f1f1c; }
.src { font-size: 13px; color: #8a8578; margin-top: 12px; } .q { font-weight: 600; }
blockquote { margin: 6px 0; padding: 4px 10px; border-left: 3px solid #2f5fa7; }
.cloze { font-weight: 700; color: #2f5fa7; }"""
BASIC_ID, CLOZE_ID = 1607392310, 1607392311


def _math(s: str) -> str:
    return re.sub(r"\$(.+?)\$", r"\\(\1\\)", s)


def _clean(value: str) -> str:
    return _math(strip_citations(value))


def _tf_tag() -> str:
    tag = T("(true or false?)")
    return tag if tag.startswith("\uff08") else " " + tag


def _src(value: str) -> str:
    pages = sorted({c.page for c in citations(value)}, key=lambda p: (len(p), p))
    return T("Book p.{pages}", pages=", ".join(pages)) if pages else ""


def chapter_cards(notes: ChapterNotes, include_unverified: bool) -> tuple[list[dict], int]:
    cards, held = [], 0
    ch = notes.ch

    def ok(status: str) -> bool:
        return status == "ok" or (include_unverified and status in ("pending", "warn"))
    for nb in notes.blocks:
        b = nb.blk
        if b.get("skip"):
            continue
        tag_base = [f"ch::{ch['id']}", f"sec::{nb.section or 'chapter'}"]
        if nb.kind == "concept":
            term = b.value("term")
            d = citations(b.value("definition"))
            st, _ = notes.field_status(nb, "definition", 0)
            pst, _ = notes.field_status(nb, "plain", 0)
            if d and ok(st):
                quote = d[0].quote
                back = f"<blockquote>{quote}</blockquote>"
                if not is_unsure(b.value("plain")) and ok(pst):
                    back += _clean(b.value("plain"))
                cards.append({"key": f"{b.id}:def", "front": b.value("cue") or T("What is {term}?", term=f"<b>{term}</b>"),
                              "back": back, "src": T("Book p.{pages}", pages=d[0].page), "tags": tag_base + ["definition"]})
                rx = re.compile(re.escape(term), re.I)
                if rx.search(quote):
                    cloze = rx.sub(lambda m: "{{c1::" + m.group(0) + "}}", quote, count=1)
                    cards.append({"key": f"{b.id}:cloze", "cloze": cloze, "extra": "", "src": T("Book p.{pages}", pages=d[0].page),
                                  "tags": tag_base + ["cloze"]})
            elif d:
                held += 1
            for i, f in enumerate(b.all("misconception")):
                mst, _ = notes.field_status(nb, "misconception", i)
                m = re.match(r"^\s*wrong\s*:\s*(?P<w>.+?)\s*\|\s*right\s*:\s*(?P<r>.+)$", f.value, re.I | re.S)
                if m and ok(mst):
                    cards.append({"key": f"{b.id}:mis{i}", "front": T("True or false: {s}", s=_math(m.group("w"))),
                                  "back": f"<b>{T('False.')}</b> " + _clean(m.group("r")), "src": _src(m.group("r")),
                                  "tags": tag_base + ["trap"]})
                elif m:
                    held += 1
        elif nb.kind == "formula":
            fst = notes.trust.get("formulas", {}).get(b.id, {}).get("status", "pending")
            hst, _ = notes.field_status(nb, "holds-when", 0)
            if ok(fst):
                back = f"\\[{b.value('latex')}\\]"
                if not is_unsure(b.value("where")):
                    back += f"<div>{_clean(b.value('where'))}</div>"
                cards.append({"key": f"{b.id}:formula", "front": T("Formula: {name}", name=f"<b>{_math(b.value('name'))}</b>"),
                              "back": back, "src": _src(b.value("source")), "tags": tag_base + ["formula"]})
                if not is_unsure(b.value("holds-when")) and ok(hst):
                    cards.append({"key": f"{b.id}:holds", "front": T("When does this hold?") + f" \\[{b.value('latex')}\\]",
                                  "back": _clean(b.value("holds-when")), "src": _src(b.value("holds-when")),
                                  "tags": tag_base + ["condition"]})
            else:
                held += 1
        elif nb.kind == "compare":
            items = [x.strip() for x in _split_cells(b.value("items"))]
            names = notes.ws.all_inventory_items()
            heads = [names.get(x, {}).get("display") or x for x in items]
            for i, f in enumerate(b.all("row")):
                rst, _ = notes.field_status(nb, "row", i)
                cells = _split_cells(f.value)
                if len(cells) >= 3 and len(heads) >= 2 and ok(rst):
                    cards.append({"key": f"{b.id}:row{i}", "front": T("{a} vs {b}: {aspect}?", a=heads[0], b=heads[1], aspect=cells[0]),
                                  "back": f"<b>{heads[0]}:</b> {_clean(cells[1])}<br><b>{heads[1]}:</b> {_clean(cells[2])}",
                                  "src": _src(f.value), "tags": tag_base + ["compare"]})
                elif len(cells) >= 3:
                    held += 1
        elif nb.kind == "process":
            steps = [f.value for f in b.all("step")]
            for i in range(len(steps) - 1):
                st1, _ = notes.field_status(nb, "step", i + 1)
                if ok(st1):
                    cards.append({"key": f"{b.id}:next{i}", "front": T("{name}: what comes after \u201c{step}\u201d?",
                                                                      name=b.value("name"), step=_clean(steps[i])),
                                  "back": _clean(steps[i + 1]),
                                  "src": _src(steps[i + 1]), "tags": tag_base + ["sequence"]})
        elif nb.kind == "question":
            qst = notes.trust.get("questions", {}).get(b.id, {}).get("status", "pending")
            if not ok(qst):
                held += 1
                continue
            qtype = b.value("type").lower()
            ans = b.value("answer").strip()
            why = _clean(b.value("why"))
            tags = tag_base + ["question", b.value("bloom") or "q"]
            if qtype == "mcq":
                opts = "<br>".join(f"{c.upper()}. {_math(b.value(f'option {c}'))}" for c in LETTERS if b.get(f"option {c}"))
                letter = ans.upper()[:1]
                cards.append({"key": f"{b.id}:q", "front": f"{_math(b.value('ask'))}<br><br>{opts}",
                              "back": f"<b>{letter}. {_math(b.value('option ' + letter.lower()))}</b><br>{why}",
                              "src": _src(b.value("why")), "tags": tags})
            elif qtype == "cloze" and re.search(r"_{3,}", b.value("ask")):
                cloze = re.sub(r"_{3,}", "{{c1::" + ans + "}}", b.value("ask"), count=1)
                cards.append({"key": f"{b.id}:q", "cloze": _math(cloze), "extra": why, "src": _src(b.value("why")),
                              "tags": tags})
            else:
                shown = ans.replace("[", " ").replace("]", "") if qtype == "numeric" else answer_text(qtype, ans)
                cards.append({"key": f"{b.id}:q", "front": _math(b.value("ask")) + (_tf_tag() if qtype == "tf" else ""),
                              "back": f"<b>{_math(shown)}</b><br>{why}", "src": _src(b.value("why")), "tags": tags})
    return cards, held


def build_deck(ws: Workspace) -> dict:
    use_language(ws)
    include = bool(ws.config.get("anki", {}).get("include_unverified"))
    title = ws.config.get("title", "Exam prep")
    all_cards: list[tuple[dict, dict]] = []
    held = 0
    for ch in ws.chapters_in_scope():
        if not ws.draft_dir(ch["id"]).exists():
            continue
        notes = load_chapter(ws, ch["id"])
        cards, h = chapter_cards(notes, include)
        held += h
        all_cards += [(ch, c) for c in cards]
    out = ws.export_dir
    out.mkdir(parents=True, exist_ok=True)
    tsv = ["#separator:tab", "#html:true", "#tags column:3"]
    for ch, c in all_cards:
        front = c.get("front") or re.sub(r"\{\{c1::(.+?)\}\}", "[...]", c.get("cloze", ""))
        back = c.get("back") or re.sub(r"\{\{c1::(.+?)\}\}", r"\1", c.get("cloze", ""))
        tsv.append("\t".join(x.replace("\t", " ").replace("\n", " ") for x in
                             (front, back + (f" <small>({c['src']})</small>" if c.get("src") else ""), " ".join(c["tags"]))))
    write_text(out / "flashcards.tsv", "\n".join(tsv) + "\n")
    apkg = None
    if genanki is not None and all_cards:
        basic = genanki.Model(BASIC_ID, "ExamScribe Basic", fields=[{"name": "Front"}, {"name": "Back"}, {"name": "Source"}],
                              templates=[{"name": "Card", "qfmt": "<div class='q'>{{Front}}</div>",
                                          "afmt": "{{FrontSide}}<hr id=answer>{{Back}}<div class='src'>{{Source}}</div>"}],
                              css=CARD_CSS)
        cloze = genanki.Model(CLOZE_ID, "ExamScribe Cloze", fields=[{"name": "Text"}, {"name": "Extra"}, {"name": "Source"}],
                              templates=[{"name": "Cloze", "qfmt": "{{cloze:Text}}",
                                          "afmt": "{{cloze:Text}}<br>{{Extra}}<div class='src'>{{Source}}</div>"}],
                              css=CARD_CSS, model_type=genanki.Model.CLOZE)
        decks = {}
        course = slugify(title, 40)
        for ch, c in all_cards:
            if ch["id"] not in decks:
                did = int(sha(course + ":" + ch["id"], 8), 16) % (1 << 30) + 1000     # stable across rebuilds
                decks[ch["id"]] = genanki.Deck(did, f"ExamScribe::{title}::{ch['number']}. {ch['title']}")
            guid = genanki.guid_for(course, c["key"])
            tags = [re.sub(r"\s+", "_", t) for t in c["tags"]]
            if "cloze" in c:
                note = genanki.Note(model=cloze, fields=[c["cloze"], c.get("extra", ""), c.get("src", "")], guid=guid, tags=tags)
            else:
                note = genanki.Note(model=basic, fields=[c["front"], c["back"], c.get("src", "")], guid=guid, tags=tags)
            decks[ch["id"]].add_note(note)
        apkg = out / "flashcards.apkg"
        genanki.Package(list(decks.values())).write_to_file(str(apkg))
    return {"cards": len(all_cards), "held_back": held, "apkg": apkg, "tsv": out / "flashcards.tsv"}
