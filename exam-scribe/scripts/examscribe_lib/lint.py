"""The linter: every rule a draft must pass, with a precise fix for each problem.

Errors are grouped by category:
  format    the file does not follow the block/field rules
  evidence  a quote, number, calculation or answer does not check out against the book
  coverage  something from the inventory is missing
Weak models fix problems one message at a time, so every message names the line,
the block, what is wrong, and exactly what to do.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import calc as calcmod
from .citations import QuoteIndex, claim_numbers, page_numbers, unsupported_numbers
from .common import Workspace, build_key, canon_number, key_of, number_groups, numbers_in, word_count
from .esm import (CITE_RE, PLACEHOLDER_RE, TRUST_MARKS, Block, Doc, Issue, citations, covers, is_unsure,
                  strip_citations)
from .schema import LETTERS, SCHEMAS, F, spec
from .tiers import AI_FIELD_LABELS

CHAPTER_KINDS = {"map", "must-know", "overview", "strategy"}
DASH_CELLS = {"", "-", "—", "–", "n/a", "na", "none"}


@dataclass
class LintContext:
    ws: Workspace
    tier: dict
    mode: str = "section"                        # section | chapter
    chapter: str | None = None
    expected: dict[str, str] = field(default_factory=dict)      # id -> kind that must exist
    known_ids: set[str] = field(default_factory=set)            # every inventory ID in the book
    chapter_ids: set[str] = field(default_factory=set)          # IDs defined in this chapter
    summary_ids: list[str] = field(default_factory=list)        # SUM- ids that must-know must cover
    term_texts: dict[str, str] = field(default_factory=dict)    # T- id -> book term
    min_questions: int = 3
    lang_differs: bool = False
    qindex: QuoteIndex | None = None
    notes_lang: str = ""                                        # the language the student reads the notes in


# Notes in these languages can be recognised by their script: prose without a single letter of it (but with English
# words) was written in the wrong language. Notes in Latin-script languages are not checked this way.
_NOTES_SCRIPT = {"zh": "[㐀-鿿]", "ja": "[぀-ヿ㐀-鿿]", "ko": "[가-힯]",
                 "ru": "[Ѐ-ӿ]", "uk": "[Ѐ-ӿ]", "bg": "[Ѐ-ӿ]", "sr": "[Ѐ-ӿ]",
                 "el": "[Ͱ-Ͽ]", "ar": "[؀-ۿ]", "fa": "[؀-ۿ]", "he": "[֐-׿]",
                 "hi": "[ऀ-ॿ]", "mr": "[ऀ-ॿ]", "ne": "[ऀ-ॿ]", "th": "[฀-๿]"}
_LANG_NAME = {"zh": "Chinese", "ja": "Japanese", "ko": "Korean", "ru": "Russian", "uk": "Ukrainian",
              "bg": "Bulgarian", "sr": "Serbian", "el": "Greek", "ar": "Arabic", "fa": "Persian", "he": "Hebrew",
              "hi": "Hindi", "mr": "Marathi", "ne": "Nepali", "th": "Thai"}
_NOT_PROSE = {"term", "term-original", "skip", "cue", "accept", "answer", "lang", "output", "covers", "figure"}


@dataclass
class LintResult:
    issues: list[Issue]
    stats: dict

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors


def _err(issues: list[Issue], line: int, block: Block | None, code: str, msg: str, hint: str,
         category: str = "format", level: str = "error") -> None:
    issues.append(Issue(line, code, msg, hint, level=level, block=block.id if block else "", category=category))


def _field_spec(kind: str, key: str) -> F | None:
    return spec(kind, key)


def _check_quote(ctx: LintContext, issues: list[Issue], blk: Block, f_line: int, key: str, cite, exact: bool,
                 max_words: int | None = None) -> str | None:
    """Validate one citation; returns the page label on success."""
    q = ctx.qindex
    t = ctx.tier
    words = word_count(cite.quote)
    mx = max_words or t["quote_max_words"]
    if words > mx:
        _err(issues, f_line, blk, "quote-long", f"{key}: the quote has {int(words)} words (max {mx}).",
             "Quote only the words that support the claim.", "evidence")
    res = q.check(cite.page, cite.quote, min_words=t["quote_min_words"], approx=t["approx_match"])
    if res.status == "exact":
        return cite.page
    if res.status == "approx":
        if exact:
            _err(issues, f_line, blk, "quote-inexact",
                 f"{key}: the quote is close to p.{cite.page} but not exact ({int(res.score * 100)}% match).",
                 f'Copy these words exactly: "{res.closest}"', "evidence")
            return None
        _err(issues, f_line, blk, "quote-approx", f"{key}: quote nearly matches p.{cite.page} "
             f"({int(res.score * 100)}%).", f'The book says: "{res.closest}". Copying it exactly removes this warning.',
             "evidence", level="warn")
        return cite.page
    if res.status == "wrong-page":
        _err(issues, f_line, blk, "quote-wrong-page",
             f"{key}: this quote is on p.{', p.'.join(res.found_pages)}, not p.{cite.page}.",
             f"Change the citation to [p.{res.found_pages[0]}: \"...\"] (use the page marker above the quote in the "
             "source file).", "evidence")
        return None
    if res.status == "bad-page":
        extra = f" The quote appears on p.{res.found_pages[0]}." if res.found_pages else ""
        _err(issues, f_line, blk, "quote-bad-page", f"{key}: there is no page '{cite.page}'.{extra}",
             "Use the page number from the ======== PAGE n ======== marker above the quote.", "evidence")
        return None
    if res.status == "too-short":
        _err(issues, f_line, blk, "quote-short", f"{key}: the quote is too short to identify ({cite.quote!r}).",
             f"Quote at least {t['quote_min_words']} consecutive words from the book.", "evidence")
        return None
    hint = (f'Closest text on p.{cite.page}: "{res.closest}". Copy the words exactly from the source file.'
            if res.closest and res.score >= 0.5 else
            f"These words are not on p.{cite.page}. Search the source file for the sentence you mean and copy it "
            "exactly, or write UNSURE: <reason> if the book does not say this.")
    _err(issues, f_line, blk, "quote-not-found", f"{key}: quote not found on p.{cite.page}.", hint, "evidence")
    return None


def _calc_numbers(blk: Block) -> set[str]:
    nums: set[str] = set()
    lines = [f.value for f in blk.all("calc")]
    for f in blk.all("calc"):
        nums.update(numbers_in(f.value.replace("[", " ").replace("]", " ")))
    if lines:
        for r in calcmod.run_calc_lines(lines):
            if r.value is not None:
                for k in range(1, 7):
                    nums.add(canon_number(f"{r.value.v:.{k}g}"))
    # a question's explanation may restate the values given in the question (the problem statement of a
    # worked example is NOT added: its numbers must be checked against the book like any other claim)
    f = blk.get("ask")
    if f:
        nums.update(numbers_in(strip_citations(f.value)))
    return nums


def _check_numbers(ctx: LintContext, issues: list[Issue], blk: Block, f_line: int, key: str, claim: str,
                   pages: list[str], allowed_extra: set[str]) -> None:
    nums = claim_numbers(claim)
    if not nums:
        return
    allowed = page_numbers(ctx.ws, pages) | allowed_extra
    missing = unsupported_numbers(nums, allowed)
    if missing:
        where = ", ".join(f"p.{p}" for p in pages) or "the cited page"
        _err(issues, f_line, blk, "number-unsupported",
             f"{key}: the number(s) {', '.join(missing)} do not appear on {where}.",
             "Copy numbers exactly as the book prints them, or compute them on a calc: line in this block.",
             "evidence")


def _cited_value(ctx: LintContext, issues: list[Issue], blk: Block, f, fspec: F, allowed_numbers: set[str],
                 stats: dict) -> None:
    value = f.value
    cites = citations(value)
    claim = strip_citations(value)
    if fspec.key == "misconception":
        m = re.match(r"^\s*wrong\s*:\s*(?P<w>.+?)\s*\|\s*right\s*:\s*(?P<r>.+)$", value, re.I | re.S)
        if not m:
            _err(issues, f.line, blk, "misconception-format", "misconception: use 'Wrong: ... | Right: ... [p.N: \"...\"]'.",
                 "Say the typical mistake after 'Wrong:' and what the book says after 'Right:', with a citation.")
            return
        claim = strip_citations(m.group("r"))
        cites = citations(m.group("r"))
    if fspec.cite == "exact":
        if len(cites) != 1 or strip_citations(value):
            _err(issues, f.line, blk, "exact-cite",
                 f"{f.key}: must be exactly one citation and nothing else, like [p.12: \"the book's sentence\"].",
                 "Copy the book's sentence into the quotation marks. Put explanations in other fields.")
            return
        page = _check_quote(ctx, issues, blk, f.line, f.key, cites[0], exact=True,
                            max_words=ctx.tier["definition_max_words"])
        if page and fspec.key == "definition":
            term = blk.value("term-original") or blk.value("term")
            tk = key_of(term)
            qk = key_of(cites[0].quote)
            stem = tk[:-1] if tk.endswith("s") and len(tk) > 4 else tk
            if stem and stem not in qk:
                _err(issues, f.line, blk, "definition-term",
                     f"definition: the quote does not mention '{term}'.",
                     "Quote the sentence that defines the term and names it (for example 'X is ...').", "evidence")
        stats["claims"] += 1
        return
    if fspec.cite in ("required",) and not cites:
        _err(issues, f.line, blk, "no-citation", f"{f.key}: needs a citation at the end: [p.N: \"exact words\"].",
             "Find the sentence in the source file that supports this and copy a few of its words exactly, or write "
             "UNSURE: <reason> if the book does not support it.", "evidence")
        return
    if fspec.cite == "required" and not claim and fspec.key not in ("source", "result"):
        _err(issues, f.line, blk, "no-claim", f"{f.key}: write the point in your own words before the citation.",
             "Put a short explanation first, then the [p.N: \"...\"] evidence.")
    if fspec.max_words and word_count(claim) > fspec.max_words:
        _err(issues, f.line, blk, "too-long", f"{f.key}: {int(word_count(claim))} words (max {fspec.max_words}).",
             "Shorten it. Short notes are easier to review.")
    pages = []
    for c in cites:
        p = _check_quote(ctx, issues, blk, f.line, f.key, c, exact=False)
        if p:
            pages.append(p)
    if pages:
        _check_numbers(ctx, issues, blk, f.line, f.key, claim, pages, allowed_numbers)
    stats["claims"] += 1


def _cells(ctx: LintContext, issues: list[Issue], blk: Block, f, allowed_numbers: set[str], stats: dict,
           min_cells: int = 2) -> None:
    parts = _split_cells(f.value)
    if len(parts) < min_cells:
        _err(issues, f.line, blk, "cells", f"{f.key}: expected {' | '.join(['...'] * max(min_cells, 2))} (cells "
             "separated by |).", "Keep each row on one line with ' | ' between cells.")
        return
    for cell in parts[1:]:
        if cell.strip().casefold() in DASH_CELLS:
            continue
        cites = citations(cell)
        if not cites:
            _err(issues, f.line, blk, "cell-citation", f"{f.key}: the cell '{cell.strip()[:40]}' has no citation.",
                 "End every filled cell with [p.N: \"exact words\"], or write — if the book says nothing.", "evidence")
            continue
        pages = [p for c in cites if (p := _check_quote(ctx, issues, blk, f.line, f.key, c, exact=False))]
        if pages:
            _check_numbers(ctx, issues, blk, f.line, f.key, strip_citations(cell), pages, allowed_numbers)
        stats["claims"] += 1


def _split_cells(value: str) -> list[str]:
    """Split on | that are outside citations."""
    parts, buf, depth = [], "", 0
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(0, depth - 1)
        if ch == "|" and depth == 0:
            parts.append(buf.strip())
            buf = ""
        else:
            buf += ch
        i += 1
    parts.append(buf.strip())
    return parts


def _latex_ok(s: str) -> str | None:
    if "$" in s:
        return "remove the $ signs; the LaTeX goes in without delimiters"
    depth = 0
    for ch in s:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return "a '}' has no matching '{'"
    if depth:
        return "a '{' is not closed"
    if s.count("(") != s.count(")"):
        return "parentheses are not balanced"
    return None


def block_key(blk: Block) -> str:
    """Chapter-level blocks share the chapter ID, so they are keyed by kind as well."""
    return f"{blk.kind}:{blk.id}" if blk.kind in CHAPTER_KINDS else blk.id


def lint_notes(doc: Doc, ctx: LintContext) -> LintResult:
    issues: list[Issue] = list(doc.issues)
    stats = {"claims": 0, "unsure": 0, "skipped": 0, "expected": len(ctx.expected), "questions": 0,
             "short": 0, "bloom": set(), "blocks": len(doc.blocks)}
    t = ctx.tier
    seen: dict[str, Block] = {}
    for no, line in enumerate(doc.lines, start=1):
        if any(ch in line for ch in TRUST_MARKS):
            _err(issues, no, None, "trust-mark", "Trust markers (✅ ⚠️ 💡) are added by the scripts, not by you.",
                 "Delete the symbol.")
        if PLACEHOLDER_RE.search(line):
            m = PLACEHOLDER_RE.search(line)
            what = "OPTIONAL line" if m.group(1) == "OPTIONAL" else "placeholder"
            _err(issues, no, None, "placeholder", f"An unfilled {what} is left: {line.strip()[:70]}",
                 "Replace <<FILL ...>> with real content. Delete <<OPTIONAL ...>> lines you do not use.")
    for blk in doc.blocks:
        schema = SCHEMAS.get(blk.kind)
        if schema is None or schema.worksheet:
            _err(issues, blk.line, blk, "unknown-kind", f"Unknown block kind '{blk.kind}'.",
                 f"Use one of: {', '.join(k for k, b in SCHEMAS.items() if not b.worksheet)}.")
            continue
        if ctx.mode == "section" and blk.kind in CHAPTER_KINDS:
            _err(issues, blk.line, blk, "wrong-file", f"'{blk.kind}' blocks belong in the chapter file, not a section.",
                 "Remove this block; the chapter task will ask for it.")
        bkey = block_key(blk)
        if bkey in seen:
            _err(issues, blk.line, blk, "duplicate-id", f"The ID {blk.id} is used twice (also line {seen[bkey].line}).",
                 "Give new blocks a new ID; do not copy an existing ID.")
            continue
        seen[bkey] = blk
        if not re.match(schema.id_pattern, blk.id):
            _err(issues, blk.line, blk, "bad-id", f"'{blk.id}' is not a valid ID for a {blk.kind} block.",
                 f"IDs for {blk.kind} blocks look like {schema.id_hint}. Keep the IDs from the draft.")
        exp_kind = ctx.expected.get(bkey)
        if exp_kind and exp_kind != blk.kind:
            _err(issues, blk.line, blk, "kind-changed", f"{blk.id} must be a '{exp_kind}' block, not '{blk.kind}'.",
                 f"Change the opening line back to '::: {exp_kind} {blk.id}'.")
        if exp_kind is None and not schema.new_ids_allowed:
            if blk.kind in CHAPTER_KINDS and ctx.chapter and blk.id == ctx.chapter:
                pass
            else:
                _err(issues, blk.line, blk, "unknown-id",
                     f"{blk.id} is not in the draft. You cannot invent new {blk.kind} blocks.",
                     "Delete this block, or use one of the blocks already in the draft.")
        _lint_block(blk, ctx, issues, stats)

    for bkey, kind in ctx.expected.items():
        if bkey not in seen:
            bid = bkey.split(":", 1)[1] if ":" in bkey else bkey
            _err(issues, 0, None, "block-missing", f"The {kind} block {bid} was deleted.",
                 f"Put '::: {kind} {bid}' back. If it truly does not belong, keep it and add 'skip: <reason>'.",
                 "coverage")
    # ratios and minimums
    exp_n = max(1, len([b for b in ctx.expected.values() if b in ("concept", "formula", "worked-example", "figure")]))
    if stats["skipped"] / exp_n > t["max_skip_ratio"] and stats["skipped"] > 1:
        _err(issues, 0, None, "too-many-skips", f"{stats['skipped']} of {exp_n} inventory blocks are skipped "
             f"(max {int(t['max_skip_ratio'] * 100)}%).", "Skip only items that are clearly not key content.",
             "coverage")
    if stats["claims"] and stats["unsure"] / max(1, stats["claims"] + stats["unsure"]) > t["max_unsure_ratio"] \
            and stats["unsure"] > 2:
        _err(issues, 0, None, "too-many-unsure", f"{stats['unsure']} fields are UNSURE.",
             "Re-read the source file: most answers are in it. Use UNSURE only when the book really does not say.",
             "coverage")
    if ctx.mode == "section" and any(k == "question" for k in ctx.expected.values()):
        if stats["questions"] < ctx.min_questions:
            _err(issues, 0, None, "few-questions", f"Only {stats['questions']} usable questions (need "
                 f"{ctx.min_questions}).", "Fill the question blocks; each needs an answer and cited evidence.",
                 "coverage")
        if stats["questions"] >= 3 and len(stats["bloom"]) < 2:
            _err(issues, 0, None, "one-level", "All questions test the same level.",
                 "Mix levels: e.g. one 'remember', one 'understand', one 'apply'.", "coverage")
        if stats["short"] > t["max_short_per_section"]:
            _err(issues, 0, None, "too-many-short", f"{stats['short']} short-answer questions (max "
                 f"{t['max_short_per_section']}).", "Change some to mcq, tf, cloze or numeric: those can be "
                 "checked automatically.")
    # must-know coverage of the book's own summary
    mk = [b for b in doc.blocks if b.kind == "must-know"]
    if ctx.mode == "chapter" and mk and ctx.summary_ids:
        covered = set()
        for f in mk[0].all("point"):
            covered.update(covers(f.value))
        missing = [s for s in ctx.summary_ids if s not in covered]
        if missing:
            _err(issues, mk[0].line, mk[0], "summary-uncovered",
                 f"must-know does not cover the book's summary items: {', '.join(missing)}.",
                 "Add or extend points and end each with (covers: SUM-...). The summary items are listed in the "
                 "comment above the block.", "coverage")
    stats["bloom"] = sorted(stats["bloom"])
    return LintResult(issues, stats)


def _lint_block(blk: Block, ctx: LintContext, issues: list[Issue], stats: dict) -> None:
    schema = SCHEMAS[blk.kind]
    t = ctx.tier
    keys = blk.keys()
    skip = blk.get("skip")
    if skip is not None:
        if word_count(skip.value) < 3 or PLACEHOLDER_RE.search(skip.value):
            _err(issues, skip.line, blk, "skip-reason", "skip: give a real reason (at least 3 words).",
                 "Example: 'skip: bold is used for emphasis here, not a term'.")
        stats["skipped"] += 1
        return
    allowed_numbers = _calc_numbers(blk)
    # unknown / repeated / missing fields
    counts: dict[str, int] = {}
    for f in blk.fields:
        counts[f.key] = counts.get(f.key, 0) + 1
        fs = _field_spec(blk.kind, f.key)
        if fs is None:
            allowed = ", ".join(x.key for x in schema.fields if not x.readonly)
            _err(issues, f.line, blk, "unknown-field", f"'{f.key}' is not a field of {blk.kind} blocks.",
                 f"Allowed fields: {allowed}.")
            continue
        if f.key.startswith("ai-") and f.key not in t["ai_fields"]:
            _err(issues, f.line, blk, "ai-not-allowed", f"'{f.key}' ({AI_FIELD_LABELS.get(f.key, 'AI extra')}) is "
                 "not allowed in this tier.", "Delete this line. Stick to what the book says.")
            continue
        if f.key == "term-original" and not ctx.lang_differs:
            _err(issues, f.line, blk, "not-needed", "term-original is only used when notes are in another language.",
                 "Delete this line.", level="warn")
    for fs in schema.fields:
        n = counts.get(fs.key, 0)
        if fs.required and n == 0:
            _err(issues, blk.line, blk, "missing-field", f"{blk.kind} {blk.id} is missing '{fs.key}:'.",
                 f"Add a line '{fs.key}: ...'. {fs.help}".strip())
        if fs.max_count and n > fs.max_count:
            _err(issues, blk.line, blk, "too-many", f"'{fs.key}' appears {n} times (max {fs.max_count}).",
                 "Keep the most useful ones.")
        if fs.min_count and 0 < n < fs.min_count:
            _err(issues, blk.line, blk, "too-few", f"'{fs.key}' needs at least {fs.min_count} lines (has {n}).",
                 f"Add more '{fs.key}:' lines. {fs.help}".strip(), "coverage")
    if ctx.lang_differs and blk.kind == "concept" and not blk.get("term-original"):
        _err(issues, blk.line, blk, "term-original", "Notes are in another language: add 'term-original:' with the "
             "term exactly as the book writes it.", "The exam uses the book's terms.")
    if blk.kind == "concept" and ctx.term_texts.get(blk.id):
        want = ctx.term_texts[blk.id]
        got = blk.value("term-original") or blk.value("term")
        if key_of(got) != key_of(want) and key_of(want) not in key_of(got):
            _err(issues, blk.line, blk, "term-changed", f"term: must be the book's term '{want}' (found '{got}').",
                 "Keep the term exactly as in the draft.")
    if blk.kind == "concept":
        # "in plain words" that only repeats the definition teaches nothing (and is what a fill-in script produces)
        defs, plain = citations(blk.value("definition")), blk.get("plain")
        if defs and plain is not None and plain.value.strip() and not is_unsure(plain.value):
            said, quote = key_of(strip_citations(plain.value)), key_of(defs[0].quote)
            if said and quote and len(said) >= 0.8 * len(quote) and _similarity(said, quote) >= 0.9:
                _err(issues, plain.line, blk, "plain-copies-definition",
                     "plain: repeats the book's definition almost word for word.",
                     "Explain it the way you would to a student, in shorter and simpler words of your own, then cite "
                     "the book's words it rests on.")
    # per-field checks
    for f in blk.fields:
        fs = _field_spec(blk.kind, f.key)
        if fs is None or (f.key.startswith("ai-") and f.key not in t["ai_fields"]):
            continue
        v = f.value.strip()
        if not v:
            _err(issues, f.line, blk, "empty", f"'{f.key}:' is empty.", "Fill it in or delete the line (if optional).")
            continue
        if PLACEHOLDER_RE.search(v):
            continue    # reported once per line above
        if is_unsure(v):
            if not fs.allow_unsure:
                _err(issues, f.line, blk, "unsure-not-allowed", f"'{f.key}' cannot be UNSURE.", fs.help)
            elif word_count(v[6:].lstrip(": ")) < 3:
                _err(issues, f.line, blk, "unsure-reason", f"{f.key}: say why you are unsure (at least 3 words).",
                     "Example: 'UNSURE: the book gives no condition for this formula'.")
            else:
                stats["unsure"] += 1
            continue
        if fs.max_words and fs.cite not in ("required", "exact", "cells") and word_count(v) > fs.max_words:
            _err(issues, f.line, blk, "too-long", f"{f.key}: {int(word_count(v))} words (max {fs.max_words}).",
                 "Shorten it.")
        script = _NOTES_SCRIPT.get((ctx.notes_lang or "").lower().split("-")[0])
        if script and fs.kind == "text" and fs.cite != "exact" and f.key not in _NOT_PROSE:
            prose = strip_citations(v)
            if len(re.findall(r"[A-Za-z]{2,}", prose)) >= 4 and not re.search(script, prose):
                name = _LANG_NAME.get(ctx.notes_lang.lower().split("-")[0], ctx.notes_lang)
                _err(issues, f.line, blk, "notes-language", f"{f.key}: this is written in English, but the notes are "
                     f"in {name}.", f"Write it in {name}; quotes in [p.N: \"...\"] stay exactly as in the book.")
        if fs.kind == "enum":
            if v.lower() not in [e.lower() for e in fs.enum]:
                _err(issues, f.line, blk, "bad-enum", f"{f.key}: '{v}' is not allowed.", f"Use one of: {', '.join(fs.enum)}.")
            continue
        if fs.kind == "latex":
            prob = _latex_ok(v)
            if prob:
                _err(issues, f.line, blk, "latex", f"latex: {prob}.", "Write plain LaTeX such as q = m c \\Delta T.")
            continue
        if fs.kind == "formula":
            try:
                if not re.match(r"^\s*[A-Za-z_]\w*\s*=(?!=)", v):
                    raise calcmod.CalcError("it must look like 'name = expression'")
                names = set(re.findall(r"[A-Za-z_]\w*", v.split("=", 1)[1])) - set(calcmod.FUNCS) - set(calcmod.CONSTS)
                calcmod.evaluate(v.split("=", 1)[1], {n: calcmod.Q(1.7) for n in names})
            except calcmod.CalcError as exc:
                _err(issues, f.line, blk, "formula-syntax", f"{f.key}: {exc}.",
                     "Use calculator syntax: q = m * c * dT (use * for multiply, ^ for powers, sqrt() for roots).",
                     "evidence")
            continue
        if fs.kind == "ids":
            ids = [x for x in re.split(r"[,\s]+", v) if x]
            bad = [x for x in ids if x not in ctx.known_ids and x.upper() != "NONE"]
            if bad:
                _err(issues, f.line, blk, "unknown-ref", f"{f.key}: unknown ID(s) {', '.join(bad)}.",
                     "Use IDs that appear in the draft comments or the inventory (e.g. LO-2.1-1, T-heat, EQ-2.1).")
            continue
        if fs.kind == "pair":
            if len(_split_cells(v)) != 2:
                _err(issues, f.line, blk, "pair", "items: name exactly two things separated by ' | '.",
                     "Example: items: T-endothermic-process | T-exothermic-process")
            continue
        if fs.kind == "calc":
            continue    # checked together below
        if fs.kind == "answer":
            continue    # checked with the question rules below
        if fs.kind == "link":
            m = re.match(r"^\s*(?P<a>\S+)\s*->\s*(?P<b>\S+)\s*\|\s*(?P<rel>.+)$", v)
            if not m:
                _err(issues, f.line, blk, "link-format", "link: use 'T-a -> T-b | relation [p.N: \"...\"]'.",
                     "Both ends must be IDs from this chapter.")
                continue
            for end in (m.group("a"), m.group("b")):
                if end not in ctx.chapter_ids:
                    _err(issues, f.line, blk, "link-id", f"link: '{end}' is not an ID from this chapter.",
                         "Use T-/EQ- IDs listed in the comment above the map block.")
        if fs.kind == "dated" and not re.match(r"^\s*[^|]{1,40}\|\s*\S", v):
            _err(issues, f.line, blk, "dated-format", "event: use 'date | what happened [p.N: \"...\"]'.", "")
            continue
        if fs.kind == "arrow" and "->" not in strip_citations(v):
            _err(issues, f.line, blk, "arrow-format", "link: use 'cause -> effect [p.N: \"...\"]'.", "")
            continue
        if fs.cite == "cells":
            _cells(ctx, issues, blk, f, allowed_numbers, stats, 2 if blk.kind == "strategy" else 3)
            continue
        if fs.cite in ("required", "exact"):
            _cited_value(ctx, issues, blk, f, fs, allowed_numbers, stats)
            continue
        if fs.cite == "optional" and citations(v):
            pages = [p for c in citations(v) if (p := _check_quote(ctx, issues, blk, f.line, f.key, c, exact=False))]
            if pages:
                _check_numbers(ctx, issues, blk, f.line, f.key, strip_citations(v), pages, allowed_numbers)
        elif fs.cite == "optional" and blk.kind == "worked-example" and f.key == "step":
            nums = claim_numbers(v)
            src_pages = [c.page for x in ("source", "problem", "result") if blk.get(x) for c in citations(blk.value(x))]
            allowed = allowed_numbers | page_numbers(ctx.ws, src_pages)
            missing = unsupported_numbers(nums, allowed)
            if missing:
                _err(issues, f.line, blk, "number-unsupported",
                     f"step: the number(s) {', '.join(missing)} are not in the example or any calc: line.",
                     "Put every computed number on a calc: line so the script can recompute it.", "evidence")
    # calc lines (shared variables, in order)
    calc_fields = blk.all("calc")
    comma = [f for f in calc_fields if re.search(r"\d,\d", f.value)]
    for f in comma:
        _err(issues, f.line, blk, "calc-comma", "calc: numbers on calc: lines need a decimal point and no thousands "
             "separator.", "Write 4.184 (not 4,184) and 15690 (not 15,690), even if the book prints them with commas; "
             "the claim text may keep the book's form.", "format")
    if calc_fields and not comma:
        for f, r in zip(calc_fields, calcmod.run_calc_lines([c.value for c in calc_fields])):
            if not r.ok:
                _err(issues, f.line, blk, "calc", f"calc: {r.message}.",
                     "Fix the numbers, units or the stated result. Units go in brackets: 250[g], 4.184[J/(g*degC)].",
                     "evidence")
    # formula consistency
    if blk.kind == "formula" and blk.get("check"):
        for f in blk.all("rearrange"):
            ok, msg = calcmod.formula_consistent(blk.value("check"), f.value)
            if not ok:
                _err(issues, f.line, blk, "rearrange", f"rearrange: {msg}.",
                     "Re-derive it from the check: formula, or delete the line.", "evidence")
    # numbers written into the LaTeX must be printed in the book's formula or on the cited source page
    if blk.kind == "formula" and blk.get("latex") and not is_unsure(blk.value("latex")):
        latex = blk.value("latex")
        plain = re.sub(r"\\[A-Za-z]+", " ", latex)
        plain = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"\1 \2", plain)
        nums = number_groups(re.sub(r"[{}_^]", " ", plain))
        if nums:
            inv_text = next((it.get("text", "") for it in ctx.ws.inventory(ctx.chapter)["items"] if it["id"] == blk.id), "")
            src_pages = [c.page for c in citations(blk.value("source"))]
            allowed = set(numbers_in(inv_text)) | page_numbers(ctx.ws, src_pages) | {"1", "2"}
            bad = unsupported_numbers(nums, allowed)
            if bad:
                _err(issues, blk.get("latex").line, blk, "latex-number",
                     f"latex: the number(s) {', '.join(bad)} are not in the book's formula.",
                     "Copy the formula exactly as printed (see the hint comment and the formula image).", "evidence")
    # numeric questions: the values used in calc: must be the ones given in the question (or book constants)
    if blk.kind == "question" and blk.value("type").lower() == "numeric" and blk.all("calc"):
        given = set(numbers_in(blk.value("ask"))) | page_numbers(ctx.ws, [c.page for c in citations(blk.value("why"))])
        used = [canon_number(m.group("num")) for f in blk.all("calc")
                for m in calcmod.QTY_RE.finditer(f.value.split("=>")[0])]
        stray = [n for n in used if n not in given]
        if stray:
            _err(issues, blk.all("calc")[0].line, blk, "calc-not-in-question",
                 f"calc: the value(s) {', '.join(stray)} are not given in the question.",
                 "Every value the student needs must be in ask: (or be a constant printed on the cited page).",
                 "evidence")
    if blk.kind == "worked-example" and blk.all("calc"):
        pages = [c.page for k in ("source", "problem", "result") for c in citations(blk.value(k))]
        given = page_numbers(ctx.ws, pages) | set(numbers_in(" ".join(strip_citations(f.value) for f in blk.all("step"))))
        used = [canon_number(m.group("num")) for f in blk.all("calc")
                for m in calcmod.QTY_RE.finditer(f.value.split("=>")[0])]
        stray = [n for n in used if n not in given]
        if stray:
            _err(issues, blk.all("calc")[0].line, blk, "calc-not-in-example",
                 f"calc: the value(s) {', '.join(stray)} do not appear in the example or its steps.",
                 "Use the numbers printed in the book's example.", "evidence")
    if blk.kind == "question":
        _lint_question(blk, ctx, issues, stats)
    if blk.kind == "trace":
        _lint_trace(blk, ctx, issues)


def _lint_trace(blk: Block, ctx: LintContext, issues: list[Issue]) -> None:
    if not (blk.code or "").strip():
        _err(issues, blk.line, blk, "trace-code", "trace blocks need the code in one fenced block (```python ... ```).", "")
        return
    if not ctx.ws.config.get("checks", {}).get("run_code"):
        return
    lang = (blk.value("lang") or blk.code_lang or "").lower()
    if lang not in ("python", "py", "python3"):
        return
    import subprocess
    import sys as _sys
    try:
        run = subprocess.run([_sys.executable, "-I", "-c", blk.code], capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        _err(issues, blk.code_line or blk.line, blk, "trace-timeout", "the code did not finish within 5 seconds.",
             "Use a short example that terminates.", "evidence")
        return
    got = (run.stdout or "").rstrip("\n")
    want = blk.value("output").replace("\\n", "\n").rstrip("\n")
    if run.returncode != 0:
        _err(issues, blk.code_line or blk.line, blk, "trace-error",
             f"the code raised an error: {(run.stderr or '').strip().splitlines()[-1:] or ['?']}",
             "Fix the code so it runs, or say in output: what error it raises and why.", "evidence")
    elif got != want:
        _err(issues, blk.line, blk, "trace-output", f"output: running the code prints {got!r}, not {want!r}.",
             "Copy the real output (use \\n for line breaks).", "evidence")


def _lint_question(blk: Block, ctx: LintContext, issues: list[Issue], stats: dict) -> None:
    t = ctx.tier
    qtype = blk.value("type").lower()
    ans = blk.get("answer")
    stats["questions"] += 1
    if blk.value("bloom"):
        stats["bloom"].add(blk.value("bloom").lower())
    if qtype == "short":
        stats["short"] += 1
    if t.get("require_covers") and not blk.get("covers"):
        nothing = not any(k.rsplit(":", 1)[-1].startswith(("T-", "EQ-")) for k in ctx.expected)
        _err(issues, blk.line, blk, "covers", "question needs 'covers:' with the IDs it tests.",
             "Add the line 'covers: NONE' (this part has no key terms or equations)." if nothing else
             "Example: covers: LO-2.2-2, EQ-2.1")
    elif t.get("require_covers") and blk.value("covers").strip().upper() == "NONE" and \
            any(k.rsplit(":", 1)[-1].startswith(("T-", "EQ-")) for k in ctx.expected) and ctx.mode == "section":
        _err(issues, blk.line, blk, "covers", "covers: NONE is only for parts without key terms or equations.",
             "Name the IDs this question tests (the concept and formula blocks of this draft).")
    if ans is None or not ans.value.strip() or PLACEHOLDER_RE.search(ans.value):
        return
    a = ans.value.strip()
    opts = {c: blk.get(f"option {c}") for c in LETTERS}
    if qtype == "mcq":
        present = [c for c, o in opts.items() if o is not None and o.value.strip()]
        if len(present) != 4:
            _err(issues, blk.line, blk, "mcq-options", f"mcq needs exactly 4 options (option A to option D); found "
                 f"{len(present)}.", "Write four options, one correct and three plausible wrong ones.")
        if a.upper() not in ("A", "B", "C", "D"):
            _err(issues, ans.line, blk, "mcq-answer", "answer: for mcq write only the letter A, B, C or D.",
                 "Example: answer: B")
        else:
            texts = [key_of(o.value) for o in opts.values() if o is not None]
            if len(set(texts)) != len(texts):
                _err(issues, blk.line, blk, "mcq-duplicate", "two options say the same thing.", "Make every option different.")
            for c in LETTERS:
                if c.upper() != a.upper() and opts.get(c) is not None and blk.get(f"why-not {c}") is None:
                    _err(issues, blk.line, blk, "why-not", f"add 'why-not {c.upper()}:' explaining why option "
                         f"{c.upper()} is wrong.", "One short sentence each; cite the book if you can.")
            if blk.get(f"why-not {a.lower()}") is not None:
                _err(issues, blk.get(f"why-not {a.lower()}").line, blk, "why-not-correct",
                     f"why-not {a.upper()} explains the CORRECT option.", "Remove it or fix the answer letter.")
    else:
        extra = [o for o in opts.values() if o is not None]
        if extra:
            _err(issues, extra[0].line, blk, "options-not-mcq", f"options are only for mcq questions (type is {qtype}).",
                 "Delete the option lines or change type to mcq.")
    if qtype == "tf" and a.lower() not in ("true", "false"):
        _err(issues, ans.line, blk, "tf-answer", "answer: for tf write true or false.", "")
    if qtype == "numeric":
        try:
            want = calcmod.parse_quantity(a)
        except calcmod.CalcError:
            _err(issues, ans.line, blk, "numeric-answer", "answer: write a number with its unit, like 15.7[kJ].", "")
            return
        cf = blk.all("calc")
        if not cf:
            _err(issues, blk.line, blk, "numeric-calc", "numeric questions need calc: lines that compute the answer.",
                 "Example: calc: q = 250[g] * 4.184[J/(g*degC)] * 15.0[degC] => 15690[J]")
            return
        res = calcmod.run_calc_lines([c.value for c in cf])
        last = next((r for r in reversed(res) if r.value is not None), None)
        if last is not None and all(r.ok for r in res):
            if last.value.d != want.d:
                _err(issues, ans.line, blk, "numeric-units", f"answer: units differ from the calculation "
                     f"({calcmod.dims_name(last.value.d)}).", "Use the unit the calculation produces.", "evidence")
            else:
                tol_txt = blk.value("tolerance").strip()
                num = re.match(r"\s*([-+]?[\d.,]+(?:[eE][-+]?\d+)?)", a)
                factor = want.v / float(num.group(1).replace(",", "")) if num and float(num.group(1).replace(",", "")) else 1
                tol = calcmod.rounding_tolerance(num.group(1)) * abs(factor) if num else 0
                if tol_txt.endswith("%"):
                    try:
                        tol = max(tol, abs(want.v) * float(tol_txt[:-1]) / 100)
                    except ValueError:
                        pass
                if abs(last.value.v - want.v) > tol * 1.0001 + 1e-12:
                    _err(issues, ans.line, blk, "numeric-mismatch", f"answer {a} does not match the calculation "
                         f"({last.value.v / factor:.5g}).", "Fix the answer or the calc lines.", "evidence")
    if qtype == "cloze":
        if not re.search(r"_{3,}", blk.value("ask")):
            _err(issues, blk.line, blk, "cloze-blank", "cloze: the ask line needs a blank written as ____.", "")
        if word_count(a) > 6:
            _err(issues, ans.line, blk, "cloze-long", "cloze: the missing part should be 1-6 words.", "")
        why = blk.get("why")
        if why is not None:
            ev = " ".join(c.quote for c in citations(why.value))
            options = [a] + [f.value for f in blk.all("accept")]
            if ev and not any(key_of(o) and key_of(o) in key_of(ev) for o in options):
                _err(issues, ans.line, blk, "cloze-evidence", "cloze: the answer does not appear in the quoted evidence.",
                     "Quote the sentence that contains the missing word(s).", "evidence")
    if qtype == "short" and word_count(a) > 60:
        _err(issues, ans.line, blk, "short-long", "short answers must be at most 60 words.", "")


# ------------------------------------------------------------------------------ worksheets

def restore_readonly(text: str, originals: dict[str, dict[str, str]]) -> tuple[str, int]:
    """Put back read-only worksheet lines (claim, context, question, options ...) that were changed or deleted.
    The script wrote them and keeps the originals, so a slip there (a retyped quote mark, a line lost while
    editing the answers below it) is repaired instead of failed: nobody can retype a long context exactly."""
    from .esm import parse as parse_esm
    doc = parse_esm(text)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    inserts: dict[int, list[str]] = {}
    fixed = 0
    for blk in doc.blocks:
        orig = originals.get(blk.id)
        if not orig:
            continue
        for key, val in orig.items():
            f = blk.get(key)
            if f is None:
                inserts.setdefault(blk.line, []).append(f"{key}: {val}")
                fixed += 1
            elif f.value.strip() != val.strip():
                lines[f.line - 1] = f"{key}: {val}"
                fixed += 1
    for at in sorted(inserts, reverse=True):
        lines[at:at] = inserts[at]
    return "\n".join(lines), fixed


def lint_worksheet(doc: Doc, originals: dict[str, dict[str, str]], kind: str, qindex: QuoteIndex | None = None,
                   extra: dict | None = None) -> LintResult:
    """Worksheets: read-only fields must be unchanged; answers must be well-formed and grounded."""
    issues: list[Issue] = list(doc.issues)
    stats = {"items": 0}
    seen = set()
    spans: dict[str, list[Block]] = {}       # SUPPORTED spans, to catch one span pasted under many claims
    for no, line in enumerate(doc.lines, start=1):
        if PLACEHOLDER_RE.search(line):
            _err(issues, no, None, "placeholder", f"Unfilled: {line.strip()[:70]}", "Replace every <<FILL ...>>.")
    for blk in doc.blocks:
        schema = SCHEMAS.get(blk.kind)
        if schema is None or blk.kind != kind:
            _err(issues, blk.line, blk, "unknown-kind", f"Only '{kind}' blocks belong in this worksheet.",
                 "Do not add or rename blocks.")
            continue
        if blk.id not in originals:
            _err(issues, blk.line, blk, "unknown-id", f"{blk.id} is not part of this worksheet.", "Do not add blocks.")
            continue
        seen.add(blk.id)
        stats["items"] += 1
        orig = originals[blk.id]
        for key, val in orig.items():
            f = blk.get(key)
            if f is None or f.value.strip() != val.strip():
                _err(issues, f.line if f else blk.line, blk, "readonly", f"'{key}' was changed or deleted.",
                     "Read-only fields must stay exactly as the script wrote them. Restore it.")
        for fs in schema.fields:
            if fs.readonly:
                continue
            f = blk.get(fs.key)
            if fs.required and (f is None or not f.value.strip()):
                _err(issues, blk.line, blk, "missing-field", f"{blk.id}: fill in '{fs.key}:'.", fs.help)
                continue
            if f is None:
                continue
            v = f.value.strip()
            if fs.kind == "enum" and v.upper() not in [e.upper() for e in fs.enum]:
                _err(issues, f.line, blk, "bad-enum", f"{fs.key}: '{v}' is not allowed.", f"Use one of: {', '.join(fs.enum)}.")
        ctx_text = orig.get("context", "")
        if kind == "claim":
            verdict = blk.value("verdict").strip().upper()
            span = blk.value("span").strip()
            if verdict == "SUPPORTED":
                if span.upper() == "NONE" or word_count(span) < 3:
                    _err(issues, blk.line, blk, "span", f"{blk.id}: SUPPORTED needs a span of at least 3 words copied "
                         "from CONTEXT.", "Copy the exact words that support the claim.")
                elif key_of(span) not in key_of(ctx_text):
                    _err(issues, blk.get("span").line, blk, "span-not-in-context",
                         f"{blk.id}: the span is not in CONTEXT.", "Copy the words exactly from the context line.")
                elif not shares_words(span, orig.get("claim", "")):
                    _err(issues, blk.get("span").line, blk, "span-unrelated",
                         f"{blk.id}: the span shares no words with the claim, so it cannot be what supports it.",
                         "Copy the words of the context that say what this claim says. If no words do, the verdict "
                         "is not SUPPORTED.")
                else:
                    spans.setdefault(key_of(span), []).append(blk)
            elif verdict in ("PARTIAL", "NOT_SUPPORTED", "CONTRADICTED"):
                if word_count(blk.value("problem")) < 3:
                    _err(issues, blk.line, blk, "problem", f"{blk.id}: say what is wrong in 'problem:' (a sentence).", "")
        elif kind == "formula-check":
            if blk.value("verdict").upper() in ("MISMATCH",) and word_count(blk.value("problem")) < 3:
                _err(issues, blk.line, blk, "problem", f"{blk.id}: describe the mismatch in 'problem:'.", "")
        elif kind == "solve":
            qtype = orig.get("type", "")
            a = blk.value("answer").strip()
            if qtype == "mcq":
                if a.upper() not in ("A", "B", "C", "D"):
                    _err(issues, blk.get("answer").line if blk.get("answer") else blk.line, blk, "mcq-answer",
                         f"{blk.id}: answer with one letter A-D.", "")
                if blk.value("only-one-correct").strip().lower() not in ("yes", "no"):
                    _err(issues, blk.line, blk, "only-one", f"{blk.id}: fill 'only-one-correct: yes' or 'no'.", "")
            elif qtype == "tf" and a.lower() not in ("true", "false"):
                _err(issues, blk.line, blk, "tf-answer", f"{blk.id}: answer true or false.", "")
            elif qtype == "numeric":
                try:
                    calcmod.parse_quantity(a)
                except calcmod.CalcError:
                    _err(issues, blk.line, blk, "numeric-answer", f"{blk.id}: answer as a number with unit, like 15.7[kJ].", "")
                cf = blk.all("calc")
                if cf:
                    for f, r in zip(cf, calcmod.run_calc_lines([c.value for c in cf])):
                        if not r.ok:
                            _err(issues, f.line, blk, "calc", f"calc: {r.message}.", "Fix the calculation.")
            ev = blk.value("evidence").strip()
            if ev and ev.upper() != "NONE" and key_of(ev) not in key_of(ctx_text):
                _err(issues, blk.get("evidence").line, blk, "evidence-not-in-context",
                     f"{blk.id}: the evidence is not copied from CONTEXT.", "Copy the exact words from the context line.")
        elif kind == "reconcile":
            if word_count(blk.value("reason")) < 4:
                _err(issues, blk.line, blk, "reason", f"{blk.id}: give a one-sentence reason.", "")
        elif kind in ("map-question", "scope-item"):
            cand_ids = set(re.findall(r"\b(?:[\d]+(?:\.\d+)+|ch\d+[\w\-]*|T-[\w.\-]*\w|EQ-[\w.\-]*\w|LO-[\w.\-]*\w)",
                                      orig.get("candidates", "")))
            picks = [p for p in re.split(r"[,\s]+", blk.value("pick")) if p]
            bad = [p for p in picks if p.upper() != "NONE" and p not in cand_ids]
            if bad:
                _err(issues, blk.line, blk, "pick", f"{blk.id}: {', '.join(bad)} not in CANDIDATES.",
                     "Pick only from the candidate list, or write NONE.")
        elif kind == "conflict":
            if word_count(blk.value("explain")) < 3:
                _err(issues, blk.line, blk, "explain", f"{blk.id}: explain your verdict in one sentence.", "")
    for bid in originals:
        if bid not in seen:
            _err(issues, 0, None, "block-missing", f"Worksheet item {bid} was deleted.", "Restore it and fill it in.")
    for same in spans.values():
        if len(same) > MAX_SAME_SPAN:
            for blk in same[MAX_SAME_SPAN:]:
                _err(issues, blk.get("span").line, blk, "span-repeated",
                     f"{blk.id}: the same span is given for {len(same)} claims.",
                     "Each claim needs the words of its context that say what that claim says.")
    return LintResult(issues, stats)


# ------------------------------------------------------------------------ evidence that is really about the claim

MAX_SAME_SPAN = 3
_STOPWORDS = set("""the and for that with this from are was were has have had not but its into than then they their
them which when what also can may such these those been being will would should could there here each other more most
some any all one two its his her our your about over under between while where who whom whose does did done very
""".split())
_CJK_RUN = re.compile(r"[぀-ヿ㐀-鿿가-힯]+")
_WORD_RE = re.compile(r"[^\W\d_]{3,}")
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _units(text: str) -> set[str]:
    """Content units of a text: words of 3+ letters (minus common function words), numbers, and pairs of
    Chinese/Japanese/Korean characters (those scripts do not separate words)."""
    import unicodedata
    t = unicodedata.normalize("NFKC", text or "").lower()
    out: set[str] = set()
    for run in _CJK_RUN.findall(t):
        out.update(run[i:i + 2] for i in range(len(run) - 1))
    rest = _CJK_RUN.sub(" ", t)
    out.update(w for w in _WORD_RE.findall(rest) if w not in _STOPWORDS)
    out.update(_NUM_RE.findall(t))
    return out


def shares_words(a: str, b: str) -> bool:
    """True when two texts share a content word, number or character pair; long words also match when one contains
    the other or they share a 5-letter stem ("energies"/"energy", "Erhaltung"/"Energieerhaltung")."""
    import os.path
    ua, ub = _units(a), _units(b)
    if ua & ub:
        return True
    la = [w for w in ua if len(w) >= 5 and not w[0].isdigit()]
    lb = [w for w in ub if len(w) >= 5 and not w[0].isdigit()]
    return any(x in y or y in x or len(os.path.commonprefix([x, y])) >= 5 for x in la for y in lb)


def _similarity(a: str, b: str) -> float:
    import difflib
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
