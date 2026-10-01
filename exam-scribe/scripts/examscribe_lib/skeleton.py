"""Draft skeletons: pre-built files with one block per inventory item and <<FILL>> slots.

A skeleton removes most of the decisions a weak model gets wrong: which items
to cover (every inventory item already has a block), which IDs to use, which
fields each block needs, how many questions of which type and level to write,
and where the evidence probably is (hint comments quote the likely sentence).
"""
from __future__ import annotations

import re

from .common import Workspace, estimate_tokens, key_of
from .ingest import render_source, section_paragraphs
from .tiers import AI_FIELD_LABELS

CITE = '[p.N: "exact words"]'
CITE3 = '[p.N: "..."]'
APOS = "'"

SUBJECT_EXTRAS = {
    "biology-medicine": ("process", "PR"),
    "history-social": ("timeline", "TL"),
    "law": ("rule", "RU"),
    "computer-science": ("trace", "TR"),
}


def fill(text: str) -> str:
    return "<<FILL: " + text + ">>"


def opt(text: str) -> str:
    return "<<OPTIONAL: " + text + ">>"


def section_parts(ws: Workspace, ch: dict, tier: dict) -> list[dict]:
    """Content sections, split into parts that fit the tier's source-size budget."""
    parts = []
    budget = tier["max_source_tokens"]
    for sec in [s for s in ch["sections"] if s["kind"] == "content" and ws.section_in_scope(s)]:
        pairs = [(pg, p) for pg, p in section_paragraphs(ws, sec) if not p.get("in_figure")]
        if not pairs:
            continue          # no text (e.g. scanned pages outside the OCR'd range)
        text = "\n".join(p["text"] for _, p in pairs)
        tokens = estimate_tokens(text)
        if tokens <= budget or len(pairs) < 4:
            parts.append({"id": sec["id"], "section": sec["id"], "title": sec["title"], "pairs": pairs, "part": None})
            continue
        # split by paragraphs into roughly equal chunks, never inside a box
        n = -(-tokens // budget)
        target = tokens / n
        chunk, acc, idx = [], 0, 1
        for i, (pg, p) in enumerate(pairs):
            chunk.append((pg, p))
            acc += estimate_tokens(p["text"])
            nxt_same_box = i + 1 < len(pairs) and p.get("box", -1) >= 0 and pairs[i + 1][1].get("box") == p.get("box")
            if acc >= target and not nxt_same_box and idx < n:
                parts.append({"id": f"{sec['id']}.p{idx}", "section": sec["id"], "title": f"{sec['title']} (part {idx})",
                              "pairs": chunk, "part": idx})
                chunk, acc, idx = [], 0, idx + 1
        if chunk:
            parts.append({"id": f"{sec['id']}.p{idx}" if idx > 1 else sec["id"], "section": sec["id"],
                          "title": f"{sec['title']} (part {idx})" if idx > 1 else sec["title"], "pairs": chunk,
                          "part": idx if idx > 1 else None})
        siblings = [pt for pt in parts if pt["section"] == sec["id"]]
        for pt in siblings:
            pt["siblings"] = siblings        # parts of one section can share a page (see _items_in_part)
    return parts


def _part_pages(part: dict) -> list[str]:
    out = []
    for pg, _ in part["pairs"]:
        if pg["label"] not in out:
            out.append(pg["label"])
    return out


def _part_key(part: dict) -> str:
    if "_key" not in part:
        part["_key"] = key_of(" ".join(p["text"] for _, p in part["pairs"]))
    return part["_key"]


def _owns(part: dict, it: dict) -> bool:
    """A section split into parts can split a page: an item on such a page belongs to the one part whose text
    holds it (its defining sentence, caption or text), so no writer is asked for a term its source lacks."""
    sharing = [s for s in part.get("siblings", [part]) if it.get("page") in _part_pages(s)]
    if len(sharing) <= 1:
        return True
    probe = key_of(it.get("context") or it.get("caption") or it.get("text") or it.get("title") or "")[:40]
    if probe:
        for s in sharing:
            if probe in _part_key(s):
                return s is part
    return sharing[0] is part


def _items_in_part(inv: dict, part: dict) -> list[dict]:
    pages = set(_part_pages(part))
    items = []
    for it in inv["items"]:
        if it.get("section") != part["section"]:
            continue
        if part["part"] is not None and (it.get("page") not in pages or not _owns(part, it)):
            continue
        if it["kind"] in ("objective", "summary"):
            continue
        items.append(it)
    order = {lab: i for i, lab in enumerate(_part_pages(part))}
    return sorted(items, key=lambda it: order.get(it.get("page"), 999))


def question_plan(ws: Workspace, tier: dict, n_items: int, has_math: bool) -> list[tuple[str, str]]:
    """Question types and Bloom levels for a section: round-robin over the exam's formats so every
    section gets a mix (retrieval of facts, understanding, application), weighted toward the real exam."""
    formats = ws.config.get("exam", {}).get("formats") or ["mcq", "short-answer"]
    n = tier["questions_per_section"]
    if n_items <= 2:
        n = max(3, n - 1)
    groups: list[list[tuple[str, str]]] = []
    if "mcq" in formats:
        groups.append([("mcq", "understand"), ("mcq", "remember"), ("mcq", "analyze")])
    if "problems" in formats and has_math:
        groups.append([("numeric", "apply"), ("numeric", "apply")])
    if "short-answer" in formats or "essay" in formats:
        groups.append([("cloze", "remember"), ("short", "understand"), ("short", "analyze")])
    groups.append([("tf", "understand"), ("cloze", "remember"), ("mcq", "understand")])
    if has_math and not any(t == "numeric" for g in groups for t, _ in g):
        groups.insert(1, [("numeric", "apply")])
    plan: list[tuple[str, str]] = []
    shorts = 0
    i = 0
    while len(plan) < n and any(groups):
        g = groups[i % len(groups)]
        i += 1
        if not g:
            continue
        t, b = g.pop(0)
        if t == "short":
            if shorts >= tier["max_short_per_section"]:
                continue
            shorts += 1
        plan.append((t, b))
    return plan


BLOOM_HELP = {"remember": "recall a fact or definition", "understand": "explain or compare in own words",
              "apply": "use a formula or rule on a new case", "analyze": "break down, find the cause or the error",
              "evaluate": "judge which option is best and why"}


def _question_block(qid: str, qtype: str, bloom: str, covers_hint: str, tier: dict) -> str:
    lines = ["::: question " + qid, "type: " + qtype, "bloom: " + bloom,
             "<!-- " + qtype + " question at the " + bloom.upper() + " level (" + BLOOM_HELP[bloom] + "). " +
             covers_hint + " -->"]
    if qtype == "mcq":
        lines.append("ask: " + fill("the question"))
        for c in "ABCD":
            lines.append("option " + c + ": " + fill("an option; exactly one is correct"))
        lines.append("answer: " + fill("the letter of the correct option: A, B, C or D"))
        lines.append("why: " + fill("why it is correct, with evidence " + CITE))
        for c in "ABCD":
            lines.append("why-not " + c + ": " + fill("why " + c + " is wrong (delete this line for the correct letter)"))
    elif qtype == "tf":
        lines.append("ask: " + fill("a statement the student marks true or false"))
        lines.append("answer: " + fill("true or false"))
        lines.append("why: " + fill("evidence " + CITE))
    elif qtype == "numeric":
        lines.append("ask: " + fill("a calculation question with all numbers and units needed"))
        lines.append("calc: " + fill("the calculation, e.g. q = 250[g] * 4.184[J/(g*degC)] * 15.0[degC] => 15690[J]"))
        lines.append("answer: " + fill("number with unit in brackets, e.g. 15.7[kJ]"))
        lines.append("why: " + fill("the formula or rule used, with evidence " + CITE))
    elif qtype == "cloze":
        lines.append("ask: " + fill("a sentence from the book with the key word(s) replaced by ____"))
        lines.append("answer: " + fill("the missing word(s)"))
        lines.append("why: " + fill("the sentence that contains the answer " + CITE))
    else:
        lines.append("ask: " + fill("a question answered in 1-3 sentences"))
        lines.append("answer: " + fill("the model answer, at most 60 words"))
        lines.append("why: " + fill("evidence " + CITE))
    example_ids = covers_hint.split(":", 1)[-1].strip().rstrip(".")
    if example_ids == "NONE":
        lines.append("covers: NONE")         # nothing in this part to name; the line stays as it is
    elif tier.get("require_covers"):
        lines.append("covers: " + fill("IDs this question tests, e.g. " + example_ids))
    else:
        lines.append("covers: " + opt("IDs tested"))
    lines.append(":::")
    return "\n".join(lines)


def make_section_draft(ws: Workspace, ch: dict, part: dict, tier: dict) -> tuple[str, dict[str, str], str]:
    """Return (draft_text, expected_ids, source_text) for a section part."""
    inv = ws.inventory(ch["id"])
    items = _items_in_part(inv, part)
    lang = ws.config.get("output", {}).get("language")
    book_lang = ws.config.get("book", {}).get("language") or "en"
    lang_differs = bool(lang and lang.split("-")[0] != book_lang.split("-")[0])
    subject = ws.config.get("subject") or "general"
    pages = _part_pages(part)
    expected: dict[str, str] = {}
    first = pages[0] if pages else "?"
    last = pages[-1] if pages else "?"
    out = ["# " + ch["title"] + " — " + part["id"] + " " + part["title"],
           "<!-- ExamScribe draft. Chapter " + ch["id"] + ", section part " + part["id"] + ", pages " + first +
           "–" + last + ". Source: chapters/" + ch["id"] + "/source/" + part["id"] + ".md -->",
           "<!-- Replace every <<FILL ...>>. Delete <<OPTIONAL ...>> lines you do not use. Keep every ::: line and ID. -->",
           "<!-- Cite as " + CITE + " using the page marker above the words in the source file. -->",
           "<!-- If the book does not say something, write UNSURE: <reason> instead of guessing. -->", ""]
    if lang_differs:
        out.insert(5, "<!-- Write your own words in language '" + lang + "'. Quotes stay in the book's language. "
                      "Keep term-original: exactly as given. -->")
    ai_line = None
    if tier["ai_fields"]:
        f0 = tier["ai_fields"][0]
        ai_line = f0 + ": " + opt(AI_FIELD_LABELS[f0].lower() + " (no citation; shown as AI-added)")
    terms = [it for it in items if it["kind"] == "term"]
    los = [it for it in inv["items"] if it["kind"] == "objective" and it.get("section") == part["section"]]
    for it in items:
        k = it["kind"]
        if k == "term":
            expected[it["id"]] = "concept"
            ctx = (it.get("context") or "")[:220]
            hint = "first bold use on p." + str(it.get("page")) + ': "' + ctx + '"'
            if it.get("glossary_only"):
                hint = ("glossary entry (p." + str(it.get("page")) + '): "' + ctx[:200] +
                        '" — find where the body text explains it')
            lines = ["::: concept " + it["id"], "term: " + it["display"], "<!-- hint: " + hint + " -->"]
            if lang_differs:
                lines.append("term-original: " + it["text"])
            lines += ["definition: " + fill("the book" + APOS + "s defining sentence copied exactly, as " + CITE3),
                      "plain: " + fill("one or two simple sentences, then " + CITE)]
            if lang_differs:
                lines.append("definition-translation: " + opt("translation of the definition, then " + CITE3))
            lines += ["why: " + opt("why it matters or why it is true, then " + CITE3),
                      "example: " + opt("an example the book gives, then " + CITE3),
                      "misconception: " + opt("Wrong: <typical mistake> | Right: <what the book says> " + CITE3)]
            if ai_line:
                lines.append(ai_line)
            lines.append(":::")
            out.append("\n".join(lines))
        elif k == "equation":
            expected[it["id"]] = "formula"
            img = (" Picture of the printed formula: " + it["image"] + ".") if it.get("image") else ""
            lines = ["::: formula " + it["id"],
                     "<!-- hint: the book prints (p." + str(it.get("page")) + "): " + it.get("text", "") +
                     "   (text extraction can garble symbols; subscripts appear as _x, superscripts as ^x)." + img + " -->"]
            if it.get("context_before"):
                lines.append('<!-- introduced by: "' + it["context_before"][:200] + '" -->')
            lines += ["name: " + fill("what the formula is for"),
                      "latex: " + fill("the formula in LaTeX with the book" + APOS + "s symbols, e.g. q = m c \\Delta T"),
                      "where: " + fill("symbol = meaning (unit); ... then " + CITE3),
                      "holds-when: " + fill("conditions the book states, then " + CITE3 + " (or UNSURE: not stated)"),
                      "source: " + fill('[p.N: "the sentence or line that gives the formula"]'),
                      "check: " + opt("calculator form, e.g. q = m * c * dT"),
                      "rearrange: " + opt("another form, e.g. dT = q / (m * c)"),
                      ":::"]
            out.append("\n".join(lines))
        elif k == "example":
            expected[it["id"]] = "worked-example"
            lines = ["::: worked-example " + it["id"],
                     "<!-- hint: Example " + str(it.get("number")) + " on p." + str(it.get("page")) + ': "' +
                     (it.get("text") or "")[:260] + '" -->',
                     "title: " + (it.get("title") or fill("short title")),
                     "source: " + fill("Example " + str(it.get("number")) + ' [p.N: "its first words"]'),
                     "problem: " + fill("the problem in short, then " + CITE3),
                     "step: " + fill("first solution step (numbers must be in the problem or a calc: line)"),
                     "step: " + opt("next step"),
                     "calc: " + opt("each computation, e.g. dT = 35.0[degC] - 20.0[degC] => 15.0[degC]"),
                     "calc: " + opt("next computation"),
                     "result: " + fill("the book" + APOS + "s final answer, then " + CITE3),
                     ":::"]
            out.append("\n".join(lines))
        elif k in ("figure", "table"):
            expected[it["id"]] = "figure"
            img = (" Image: " + it["image"] + ".") if it.get("image") else ""
            lines = ["::: figure " + it["id"],
                     "<!-- caption (p." + str(it.get("page")) + "): " + (it.get("caption") or "")[:240] + img + " -->",
                     "what: " + fill("what it shows, then " + '[p.N: "words from the caption or text"]'),
                     "look-for: " + opt("a detail worth noticing, then " + CITE3), ":::"]
            out.append("\n".join(lines))
    extra = SUBJECT_EXTRAS.get(subject)
    if extra and items:
        kind, prefix = extra
        bid = prefix + "-" + part["id"] + "-1"
        tmpl = {"process": ["name: " + opt("name of a multi-step process in this section"),
                            "step: " + opt("step 1 " + CITE3), "step: " + opt("step 2 " + CITE3)],
                "timeline": ["name: " + opt("what the events have in common"),
                             "event: " + opt("date | event " + CITE3), "event: " + opt("date | event " + CITE3)],
                "rule": ["name: " + opt("rule name"), "rule: " + opt("the rule " + CITE3),
                         "element: " + opt("an element " + CITE3)],
                "trace": ["ask: " + opt("What does this code print?"), "lang: " + opt("python"),
                          "output: " + opt("exact output"), "why: " + opt("explanation " + CITE3)]}[kind]
        out.append("\n".join(["<!-- OPTIONAL block: delete it entirely if the section has no " + kind + ". -->",
                              "::: " + kind + " " + bid] + tmpl + [":::"]))
    has_math = any(it["kind"] in ("equation", "example") for it in items)
    plan = question_plan(ws, tier, len(items), has_math)
    lo_ids = ", ".join(lo["id"] for lo in los[:4])
    term_ids = ", ".join(t["id"] for t in terms[:3])
    eq_ids = ", ".join(it["id"] for it in items if it["kind"] == "equation")
    other_ids = ", ".join(it["id"] for it in items if it["kind"] in ("figure", "table", "example"))
    # a part without key terms, objectives or equations: its questions cover NONE (there is nothing to name)
    cover_hint = "Possible covers: " + (", ".join(x for x in (lo_ids, term_ids, eq_ids, other_ids) if x) or "NONE")
    if los:
        out.append("<!-- Learning objectives of this section (every one should be tested by some question):\n" +
                   "\n".join("     " + lo["id"] + ": " + lo["text"] for lo in los) + "\n-->")
    for i, (qt, bl) in enumerate(plan, start=1):
        qid = "Q-" + part["id"] + "-" + str(i).zfill(2)
        expected[qid] = "question"
        out.append(_question_block(qid, qt, bl, cover_hint, tier))
    text = "\n\n".join(out) + "\n"
    header = "# Source: " + part["id"] + " " + part["title"] + " (chapter " + ch["id"] + ": " + ch["title"] + ")"
    source = render_source(ws, part["pairs"], header)
    return text, expected, source


CONTRAST = re.compile(r"\b(whereas|unlike|in contrast|while|but|versus|vs\.?|compared with|differs?|opposite|"
                      r"outside|instead|rather than)\b", re.I)
PREFIX_PAIRS = (("endo", "exo"), ("hyper", "hypo"), ("homo", "hetero"), ("intra", "inter"), ("pro", "eu"),
                ("mito", "meio"), ("oxid", "reduc"), ("ana", "cata"), ("in", "ex"), ("im", "ex"), ("pre", "post"))


def compare_candidates(ws: Workspace, ch: dict, inv: dict, limit: int | None = None) -> list[tuple[str, str, str]]:
    """Pairs of terms students confuse, strongest evidence first:
    1. the book contrasts them in one sentence ('whereas', 'unlike', ...)
    2. opposite prefixes (endo-/exo-, hyper-/hypo-, ...)
    3. same head word, different modifier (kinetic energy / potential energy)
    4. one name nested in the other (heat capacity / specific heat capacity)"""
    from .common import split_sentences
    terms = [it for it in inv["items"] if it["kind"] == "term"]
    if limit is None:
        limit = 3 if len(terms) <= 8 else 4
    contrasted: set[tuple[str, str]] = set()
    for sec in ch["sections"]:
        if sec["kind"] != "content":
            continue
        for _, p in section_paragraphs(ws, sec):
            for s in split_sentences(p["text"]):
                m = CONTRAST.search(s)
                if not m:
                    continue
                low = s.lower()
                hits = []
                for t in terms:
                    for mm in re.finditer(r"\b" + re.escape(t["text"].lower()) + r"s?\b", low):
                        hits.append((mm.start(), t["id"]))
                hits.sort()
                # drop a term that is only part of a longer term mentioned at the same place
                before = [h for h in hits if h[0] < m.start()]
                after = [h for h in hits if h[0] > m.start()]
                if before and after:
                    pair = (before[-1][1], after[0][1])
                elif len(after) >= 2 and m.start() < 3:       # "Unlike X, ... Y ..."
                    pair = (after[0][1], after[1][1])
                else:
                    continue
                if pair[0] != pair[1]:
                    contrasted.add(tuple(sorted(pair)))
    out: list[tuple[int, str, str, str]] = []
    for i, a in enumerate(terms):
        for b in terms[i + 1:]:
            ta, tb = a["text"].lower(), b["text"].lower()
            wa, wb = ta.split(), tb.split()
            cands = []
            if tuple(sorted((a["id"], b["id"]))) in contrasted:
                cands.append((1, "contrasted in the book"))
            for x, y in PREFIX_PAIRS:
                if (ta.startswith(x) and tb.startswith(y)) or (ta.startswith(y) and tb.startswith(x)):
                    if wa[1:] == wb[1:] or len(x) >= 3:
                        cands.append((0, "opposite prefixes"))
            if len(wa) == len(wb) >= 2 and wa[-1] == wb[-1] and wa != wb:
                cands.append((2, "same kind, different type"))
            short, long_ = (wa, wb) if len(wa) < len(wb) else (wb, wa)
            if len(short) >= 2 and len(short) < len(long_) and " ".join(short) in " ".join(long_):
                cands.append((3, "one name inside the other"))
            if cands:
                rank, reason = min(cands)
                out.append((rank, a["id"], b["id"], reason))
    out.sort()
    uniq, used = [], {}
    for rank, a, b, reason in out:
        # avoid three comparisons that all involve the same term
        if used.get(a, 0) >= 2 or used.get(b, 0) >= 2:
            continue
        used[a] = used.get(a, 0) + 1
        used[b] = used.get(b, 0) + 1
        uniq.append((a, b, reason))
    return uniq[:limit]


def make_chapter_draft(ws: Workspace, ch: dict, tier: dict) -> tuple[str, dict[str, str], str]:
    inv = ws.inventory(ch["id"])
    cid = ch["id"]
    expected = {"overview:" + cid: "overview", "must-know:" + cid: "must-know", "map:" + cid: "map"}
    formats = ws.config.get("exam", {}).get("formats") or []
    summary = [it for it in inv["items"] if it["kind"] == "summary"]
    ids = [it for it in inv["items"] if it["kind"] in ("term", "equation")]
    out = ["# " + ch["title"] + " — chapter overview blocks",
           "<!-- ExamScribe chapter draft for " + cid + ". Use the source file chapters/" + cid +
           "/source/chapter.md. Every claim needs " + CITE + ". -->", ""]
    intro = inv.get("intro") or {}
    out.append("\n".join([
        "::: overview " + cid,
        "<!-- chapter intro (p." + str(intro.get("page", "?")) + '): "' + (intro.get("text") or "")[:300] + '" -->',
        "answers: " + fill("the questions this chapter answers, then " + CITE3),
        "big-picture: " + fill("how it connects to other chapters or the course, then " + CITE3),
        ":::"]))
    sum_lines = "\n".join("     " + s["id"] + " (p." + str(s["page"]) + "): " + s["text"] for s in summary) or \
        "     (the book has no summary)"
    out.append("\n".join([
        "<!-- The book's own summary. EVERY item below must be covered by a point ending with (covers: SUM-...):\n" +
        sum_lines + "\n-->",
        "::: must-know " + cid,
        "point: " + fill("must-know fact " + CITE3 + " (covers: SUM-...)"),
        "point: " + fill("must-know fact " + CITE3 + " (covers: SUM-...)"),
        "point: " + fill("must-know fact " + CITE3 + " (covers: SUM-...)"),
        "point: " + fill("must-know fact " + CITE3 + " (covers: SUM-...)"),
        "point: " + opt("more points as needed (max 12)"),
        ":::"]))
    id_lines = "\n".join("     " + it["id"] + ": " + (it.get("display") or it.get("text") or "") for it in ids)
    out.append("\n".join([
        "<!-- IDs you can use in the map:\n" + id_lines + "\n-->",
        "::: map " + cid,
        "link: " + fill("T-a -> T-b | how they relate " + CITE3),
        "link: " + fill("T-a -> EQ-x | relation " + CITE3),
        "link: " + fill("another link"),
        "link: " + opt("more links"),
        ":::"]))
    for i, (a, b, reason) in enumerate(compare_candidates(ws, ch, inv), start=1):
        bid = "CMP-" + cid + "-" + str(i).zfill(2)
        expected[bid] = "compare"
        out.append("\n".join([
            "<!-- candidate pair (" + reason + "). If they are not really confusable, keep the block and write "
            "skip: <reason> -->",
            "::: compare " + bid, "items: " + a + " | " + b,
            "row: " + fill("aspect | fact about the first " + CITE3 + " | fact about the second " + CITE3),
            "row: " + fill("another aspect | ... | ..."), ":::"]))
    if "problems" in formats:
        expected["strategy:" + cid] = "strategy"
        out.append("\n".join(["::: strategy " + cid,
                              "row: " + fill("when you see ... | do ... " + CITE3),
                              "row: " + fill("when you see ... | do ... " + CITE3), ":::"]))
    if "essay" in formats:
        bid = "OUT-" + cid + "-1"
        expected[bid] = "outline"
        out.append("\n".join(["::: outline " + bid, "prompt: " + fill("a likely essay question"),
                              "thesis: " + fill("thesis " + CITE3),
                              "point: " + fill("supporting point " + CITE3),
                              "point: " + fill("supporting point " + CITE3),
                              "counter: " + opt("counterpoint " + CITE3), ":::"]))
    text = "\n\n".join(out) + "\n"
    pairs = []
    for sec in [{"start": ch["start"], "end": ch["sections"][0]["start"] if ch["sections"] else ch["end"]}] + \
            list(ch["sections"]):
        pairs.extend(section_paragraphs(ws, sec))
    seen, uniq = set(), []
    for pg, p in sorted(pairs, key=lambda x: (x[0]["index"], x[1]["y0"])):
        k = (pg["index"], p["y0"], p["x0"])
        if k not in seen:
            seen.add(k)
            uniq.append((pg, p))
    source = render_source(ws, uniq, "# Source: chapter " + cid + " " + ch["title"] + " (whole chapter)")
    return text, expected, source
