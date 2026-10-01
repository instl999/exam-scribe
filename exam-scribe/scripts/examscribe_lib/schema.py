"""Block and field definitions shared by the linter, skeletons, renderer, verifier and flashcards.

cite modes:
  none      no citation expected
  required  the value must end with at least one [p.N: "exact words"] citation (or be UNSURE: ...)
  optional  citations allowed and checked if present
  exact     the whole value is ONE citation; the quote itself is the content (definitions)
  cells     "a | b | c" where every non-empty cell after the first carries its own citation
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

QUESTION_TYPES = ("mcq", "tf", "numeric", "cloze", "short")
BLOOM = ("remember", "understand", "apply", "analyze", "evaluate")
VERDICTS = ("SUPPORTED", "PARTIAL", "NOT_SUPPORTED", "CONTRADICTED")
FORMULA_VERDICTS = ("MATCH", "MISMATCH", "CANNOT_TELL")
JUDGEMENTS = ("SAME", "KEY_WRONG", "MINE_WRONG", "AMBIGUOUS")
CONFLICT_VERDICTS = ("CONSISTENT", "DIFFERENT_NOTATION", "CONFLICT", "NOT_RELATED")
LETTERS = "abcd"


@dataclass(frozen=True)
class F:
    key: str
    required: bool = False
    max_count: int | None = 1
    min_count: int = 0
    cite: str = "none"
    kind: str = "text"
    enum: tuple = ()
    max_words: int | None = None
    allow_unsure: bool = True
    claim: str = ""               # claim type contributed to verification ("" = none)
    readonly: bool = False        # worksheets: the script wrote it, the model must not change it
    help: str = ""


@dataclass(frozen=True)
class B:
    kind: str
    id_pattern: str
    fields: tuple
    help: str
    new_ids_allowed: bool = False
    worksheet: bool = False
    id_hint: str = ""
    extra: dict = field(default_factory=dict)


_AI_HELP = {"ai-mnemonic": "AI-added memory aid (all tiers)", "ai-analogy": "AI-added analogy (standard and frontier tiers)",
            "ai-tip": "AI-added exam tip (standard and frontier tiers)", "ai-example": "AI-added extra example (frontier tier)"}


def _ai(key: str) -> F:
    return F(key, max_words=50, help=_AI_HELP[key] + ". Shown with a 'not from the book' label. No citation.")


CONCEPT = B("concept", r"^T-[\w.\-]+$", (
    F("term", required=True, max_words=10, allow_unsure=False, help="The term exactly as the book writes it."),
    F("term-original", max_words=10, allow_unsure=False,
      help="Only when notes are in another language: the term exactly as the book writes it."),
    F("skip", max_words=40, allow_unsure=False,
      help="Only if this is not really a key term (e.g. bold used for emphasis). Give the reason."),
    F("definition", required=True, cite="exact", claim="definition",
      help="The book's own defining sentence, copied exactly, as [p.N: \"...\"]."),
    F("definition-translation", cite="required", claim="translation", max_words=80,
      help="Only when notes are in another language: your translation of the definition, cited."),
    F("plain", required=True, cite="required", max_words=60, claim="fact",
      help="One or two sentences in simple words, ending with a citation."),
    F("why", cite="required", max_words=60, claim="fact", help="Why it matters or why it is true, cited."),
    F("example", max_count=2, cite="required", max_words=60, claim="fact", help="An example from the book, cited."),
    F("misconception", max_count=2, cite="required", max_words=70, claim="misconception",
      help="'Wrong: <mistake students make> | Right: <what the book says> [p.N: \"...\"]'."),
    F("figure", max_count=2, kind="ids", help="ID of a figure or table that illustrates this term."),
    F("cue", max_words=25, help="Optional recall question for this card (default: 'What is <term>?')."),
    _ai("ai-mnemonic"), _ai("ai-analogy"), _ai("ai-tip"), _ai("ai-example"),
), "A key term: definition quoted exactly, explained simply, with evidence.", id_hint="T-<term>")

FORMULA = B("formula", r"^EQ-[\w.\-]+$", (
    F("name", required=True, max_words=12, allow_unsure=False, help="What the formula is for."),
    F("skip", max_words=40, allow_unsure=False, help="Only if this is not a real formula. Give the reason."),
    F("latex", required=True, kind="latex", allow_unsure=False,
      help="The formula in LaTeX, same symbols as the book, e.g. q = m c \\Delta T"),
    F("where", required=True, cite="required", max_words=90, claim="fact",
      help="Each symbol = meaning (unit); separated by ';' and cited."),
    F("holds-when", required=True, cite="required", max_words=45, claim="condition",
      help="Conditions or assumptions the book states, cited. If the book states none: UNSURE: not stated."),
    F("source", required=True, cite="exact", claim="formula-source",
      help="Quote the sentence or line that gives the formula."),
    F("check", kind="formula", help="The formula in calculator syntax, e.g. q = m * c * dT"),
    F("rearrange", max_count=4, kind="formula", help="Rearranged forms in calculator syntax, e.g. dT = q / (m * c)"),
    F("example", cite="required", max_words=60, claim="fact", help="How the book uses it, cited."),
    _ai("ai-tip"), _ai("ai-mnemonic"),
), "A formula: LaTeX, symbols with units, when it holds, and a script-checkable form.", id_hint="EQ-<number>")

WORKED = B("worked-example", r"^WE-[\w.\-]+$", (
    F("title", required=True, max_words=14, allow_unsure=False),
    F("skip", max_words=40, allow_unsure=False, help="Only if this is not a worked example. Give the reason."),
    F("source", required=True, cite="required", claim="fact", help="Where the example is, quoting its first words."),
    F("problem", required=True, cite="required", max_words=90, claim="fact", help="The problem as the book states it."),
    F("step", required=True, max_count=12, min_count=1, cite="optional", max_words=55,
      help="One solution step per line, in order. Numbers must come from the problem or a calc: line."),
    F("calc", max_count=14, kind="calc",
      help="Calculator line: 'dT = 35.0[degC] - 20.0[degC]' or 'q = m * c * dT => 15690[J]'."),
    F("result", required=True, cite="required", claim="result", help="The book's final answer, cited."),
), "A worked example from the book, with every calculation recomputed by the script.", id_hint="WE-<number>")

FIGURE = B("figure", r"^(FIG|TAB)-[\w.\-]+$", (
    F("what", required=True, cite="required", max_words=50, claim="fact", help="What the figure/table shows, cited."),
    F("look-for", max_count=3, cite="required", max_words=40, claim="fact", help="Detail worth noticing, cited."),
    F("skip", max_words=40, allow_unsure=False, help="Only if the figure is decorative. Give the reason."),
), "A figure or table from the book (the image itself is cropped from the PDF).", id_hint="FIG-<number>")

QUESTION = B("question", r"^Q-[\w.\-]+$", (
    F("type", required=True, kind="enum", enum=QUESTION_TYPES, allow_unsure=False),
    F("bloom", required=True, kind="enum", enum=BLOOM, allow_unsure=False),
    F("skip", max_words=40, allow_unsure=False, help="Only if the section cannot support another question."),
    F("ask", required=True, max_words=90, allow_unsure=False, help="The question. Cloze: include ____ for the blank."),
    *[F(f"option {c}", max_words=30, allow_unsure=False) for c in LETTERS],
    F("answer", required=True, kind="answer", allow_unsure=False,
      help="mcq: A-D; tf: true/false; numeric: number[unit]; cloze: the missing word(s); short: <=60 words."),
    F("accept", max_count=4, max_words=20, help="Other acceptable answers (cloze/short)."),
    F("tolerance", help="numeric only, e.g. 1% (default: rounding of the stated answer)."),
    F("why", required=True, cite="required", max_words=70, claim="answer",
      help="Why the answer is right, with the book's evidence."),
    *[F(f"why-not {c}", max_words=40, cite="optional", allow_unsure=False) for c in LETTERS],
    F("calc", max_count=10, kind="calc", help="numeric: the calculation that produces the answer."),
    F("covers", kind="ids", help="IDs this question tests (LO-..., T-..., EQ-...)."),
), "A self-test question with a verified answer key.", new_ids_allowed=True, id_hint="Q-<section>-<nn>")

COMPARE = B("compare", r"^CMP-[\w.\-]+$", (
    F("items", required=True, kind="pair", allow_unsure=False,
      help="The two things compared: 'T-endothermic-process | T-exothermic-process' (IDs or names)."),
    F("row", required=True, max_count=8, min_count=2, cite="cells", max_words=70, claim="compare",
      help="'aspect | fact about first [p.N: \"...\"] | fact about second [p.N: \"...\"]'"),
    F("skip", max_words=40, allow_unsure=False),
), "A side-by-side table of two easily confused ideas.", new_ids_allowed=True, id_hint="CMP-<chapter>-<nn>")

MAP = B("map", r"^ch[\w.\-]+$", (
    F("link", required=True, max_count=24, min_count=3, cite="required", kind="link", claim="relation",
      help="'T-a -> T-b | how they relate [p.N: \"...\"]' using IDs from this chapter."),
), "A concept map: each arrow is a cited claim.", id_hint="<chapter id>")

MUST_KNOW = B("must-know", r"^ch[\w.\-]+$", (
    F("point", required=True, max_count=12, min_count=4, cite="required", max_words=45, claim="fact",
      help="A must-know fact, cited, ending with (covers: SUM-...) for the summary items it covers."),
), "The chapter's must-know list, checked against the book's own summary.", id_hint="<chapter id>")

OVERVIEW = B("overview", r"^ch[\w.\-]+$", (
    F("answers", required=True, cite="required", max_words=60, claim="fact",
      help="The questions this chapter answers, cited (use the intro or objectives)."),
    F("big-picture", required=True, cite="required", max_words=70, claim="fact",
      help="How the chapter fits the course, cited."),
), "One-screen overview used in the course map.", id_hint="<chapter id>")

PROCESS = B("process", r"^PR-[\w.\-]+$", (
    F("name", required=True, max_words=12, allow_unsure=False),
    F("step", required=True, max_count=14, min_count=2, cite="required", max_words=45, claim="fact"),
), "An ordered process (biology pathways, lab procedures, mechanisms).", new_ids_allowed=True, id_hint="PR-<nn>")

TIMELINE = B("timeline", r"^TL-[\w.\-]+$", (
    F("name", required=True, max_words=12, allow_unsure=False),
    F("event", required=True, max_count=20, min_count=2, cite="required", kind="dated", max_words=45, claim="fact",
      help="'1789 | what happened [p.N: \"...\"]'"),
), "Dated events in order.", new_ids_allowed=True, id_hint="TL-<nn>")

CAUSE = B("chain", r"^CAUSE-[\w.\-]+$", (
    F("name", required=True, max_words=12, allow_unsure=False),
    F("link", required=True, max_count=12, min_count=1, cite="required", kind="arrow", max_words=45, claim="relation",
      help="'cause -> effect [p.N: \"...\"]'"),
), "Cause-and-effect chain.", new_ids_allowed=True, id_hint="CAUSE-<nn>")

RULE = B("rule", r"^RU-[\w.\-]+$", (
    F("name", required=True, max_words=12, allow_unsure=False),
    F("rule", required=True, cite="required", max_words=70, claim="fact"),
    F("element", max_count=10, cite="required", max_words=45, claim="fact"),
    F("exception", max_count=6, cite="required", max_words=45, claim="fact"),
    F("case", max_count=6, cite="required", max_words=45, claim="fact"),
), "A legal or formal rule with elements, exceptions and cases.", new_ids_allowed=True, id_hint="RU-<nn>")

TRACE = B("trace", r"^TR-[\w.\-]+$", (
    F("ask", required=True, max_words=40, allow_unsure=False),
    F("lang", required=True, allow_unsure=False),
    F("output", required=True, allow_unsure=False, help="Exact output. Use \\n for line breaks."),
    F("why", required=True, cite="required", max_words=60, claim="answer"),
), "A code-tracing exercise (code goes in one fenced block).", new_ids_allowed=True, id_hint="TR-<nn>")

STRATEGY = B("strategy", r"^ch[\w.\-]+$", (
    F("row", required=True, max_count=10, min_count=2, cite="cells", max_words=60, claim="strategy",
      help="'when you see ... | what to do [p.N: \"...\"]'"),
), "Problem-solving strategy table.", id_hint="<chapter id>")

OUTLINE = B("outline", r"^OUT-[\w.\-]+$", (
    F("prompt", required=True, max_words=40, allow_unsure=False),
    F("thesis", required=True, cite="required", max_words=45, claim="fact"),
    F("point", required=True, max_count=8, min_count=2, cite="required", max_words=45, claim="fact"),
    F("counter", max_count=2, cite="required", max_words=45, claim="fact"),
), "An essay answer outline.", new_ids_allowed=True, id_hint="OUT-<nn>")

# ---------------------------------------------------------------- worksheets
CLAIM_CHECK = B("claim", r"^V-[0-9a-f]{6,}$", (
    F("claim", required=True, readonly=True),
    F("context", required=True, readonly=True),
    F("verdict", required=True, kind="enum", enum=VERDICTS, allow_unsure=False),
    F("span", required=True, allow_unsure=False,
      help="Exact words copied from CONTEXT that support the claim, or NONE."),
    F("problem", allow_unsure=False, help="If not SUPPORTED: what is wrong, in one sentence."),
), "Verify one claim against the book text.", worksheet=True)

FORMULA_CHECK = B("formula-check", r"^VF-[0-9a-f]{6,}$", (
    F("latex", required=True, readonly=True),
    F("book-line", required=True, readonly=True),
    F("image", readonly=True),
    F("verdict", required=True, kind="enum", enum=FORMULA_VERDICTS, allow_unsure=False),
    F("problem", allow_unsure=False),
), "Check a LaTeX transcription against the book's formula.", worksheet=True)

SOLVE = B("solve", r"^S-[0-9a-f]{6,}$", (
    F("type", required=True, readonly=True),
    F("question", required=True, readonly=True),
    *[F(f"option {c}", readonly=True) for c in LETTERS],
    F("context", required=True, readonly=True),
    F("answer", required=True, allow_unsure=False),
    F("only-one-correct", kind="enum", enum=("yes", "no"), allow_unsure=False),
    F("evidence", required=True, allow_unsure=False, help="Exact words from CONTEXT that decide the answer."),
    F("calc", max_count=10, kind="calc"),
), "Answer a question without seeing the key.", worksheet=True)

RECONCILE = B("reconcile", r"^R-[0-9a-f]{6,}$", (
    F("question", required=True, readonly=True),
    F("key-answer", required=True, readonly=True),
    F("your-answer", required=True, readonly=True),
    F("context", required=True, readonly=True),
    F("judgement", required=True, kind="enum", enum=JUDGEMENTS, allow_unsure=False),
    F("reason", required=True, allow_unsure=False, max_words=60),
), "Compare an answer key with an independent answer.", worksheet=True)

PAST_Q = B("map-question", r"^PQ-[\w.\-]+$", (
    F("question", required=True, readonly=True),
    F("candidates", required=True, readonly=True),
    F("pick", required=True, kind="ids", allow_unsure=False, help="1-3 IDs from CANDIDATES, or NONE."),
    F("reason", required=True, max_words=40, allow_unsure=False),
), "Map a past exam question to book sections.", worksheet=True)

CONFLICT = B("conflict", r"^CF-[\w.\-]+$", (
    F("term", required=True, readonly=True),
    F("book", required=True, readonly=True),
    F("slides", required=True, readonly=True),
    F("verdict", required=True, kind="enum", enum=CONFLICT_VERDICTS, allow_unsure=False),
    F("explain", required=True, max_words=50, allow_unsure=False),
), "Compare the instructor's material with the book.", worksheet=True)

SCOPE = B("scope-item", r"^SY-[\w.\-]+$", (
    F("syllabus", required=True, readonly=True),
    F("candidates", required=True, readonly=True),
    F("pick", required=True, kind="ids", allow_unsure=False, help="Section IDs from CANDIDATES, or NONE."),
), "Map a syllabus line to book sections.", worksheet=True)

SCHEMAS: dict[str, B] = {b.kind: b for b in (
    CONCEPT, FORMULA, WORKED, FIGURE, QUESTION, COMPARE, MAP, MUST_KNOW, OVERVIEW, PROCESS, TIMELINE, CAUSE, RULE,
    TRACE, STRATEGY, OUTLINE, CLAIM_CHECK, FORMULA_CHECK, SOLVE, RECONCILE, PAST_Q, CONFLICT, SCOPE)}

NOTE_KINDS = tuple(k for k, b in SCHEMAS.items() if not b.worksheet)


def spec(kind: str, key: str) -> F | None:
    b = SCHEMAS.get(kind)
    if not b:
        return None
    for f in b.fields:
        if f.key == key:
            return f
    return None


def format_help(kind: str) -> str:
    b = SCHEMAS.get(kind)
    if b is None:
        return f"Unknown block kind '{kind}'. Known: {', '.join(SCHEMAS)}"
    out = [f"::: {kind} {b.id_hint or '<ID>'}", f"<!-- {b.help} -->"]
    for f in b.fields:
        if f.readonly:
            out.append(f"{f.key}: (written by the script, do not change)")
            continue
        need = "required" if f.required else "optional"
        cnt = "" if f.max_count == 1 else f", up to {f.max_count} lines" + (f", at least {f.min_count}" if f.min_count else "")
        cite = {"required": ", must end with [p.N: \"exact words\"]", "exact": ", exactly one citation, nothing else",
                "cells": ", every cell after the first cited", "optional": ", citations allowed"}.get(f.cite, "")
        enum = f" one of: {' | '.join(f.enum)}" if f.enum else ""
        words = f", max {f.max_words} words" if f.max_words else ""
        out.append(f"{f.key}: <{need}{cnt}{cite}{words}{enum}>  {f.help}".rstrip())
    out.append(":::")
    return "\n".join(out)


ID_RE = re.compile(r"\b(?:T|EQ|WE|FIG|TAB|LO|SUM|Q|CMP|PR|TL|CAUSE|RU|TR|OUT)-[\w.\-]*\w")
