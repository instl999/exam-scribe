"""The state machine behind `next` and `check`.

A model never has to remember the workflow. `next` performs every deterministic
step it can (inventory, skeletons, worksheets, builds) and stops at the first
task that needs a model or the user, printing a self-contained task card:
role, goal, exact files, rules, and the command that must print PASS.
`check` validates that task, counts attempts, and on PASS prints the next card.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import verify as V
from .citations import QuoteIndex
from .common import CLI, REFS_DIR, ESError, Workspace, estimate_tokens, file_hash, read_json, read_text, write_text
from .config import REQUIRED_INTAKE, get_key
from .esm import PLACEHOLDER_RE, autofix, parse
from .lint import LintContext, lint_notes, lint_worksheet, restore_readonly
from .skeleton import make_chapter_draft, make_section_draft, section_parts
from .tiers import tier_params

LINE = "=" * 78


@dataclass
class Task:
    id: str
    kind: str
    role: str
    goal: str
    chapter: str | None = None
    edit: Path | None = None
    read: list[tuple[Path, str]] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    body: str = ""
    fresh: bool = False
    progress: str = ""
    worksheet: str | None = None
    extra: dict = field(default_factory=dict)


def _q(p: Path | str) -> str:
    return f'"{p}"'


def cmd(ws: Workspace, *args: str) -> str:
    return " ".join(["python", _q(CLI)] + [args[0], _q(ws.root)] + list(args[1:]))


# =============================================================================== task cards

WRITER_RULES = [
    "Replace every <<FILL ...>>. Delete <<OPTIONAL ...>> lines you do not use. Keep every ::: line and ID.",
    "End every claim with [p.N: \"exact words\"]: {qmin}-{qmax} words copied exactly from the source file, where N "
    "is the number in the ======== PAGE N ======== marker above those words.",
    "definition: holds ONLY the book's defining sentence, as one citation, copied exactly.",
    "Never invent a number. Put every computed number on a calc: line; the script recomputes it.",
    "Say only what the cited words say: no added reasons, contrasts ('rather than ...') or wider scope. If the book "
    "does not say something, write UNSURE: <reason>. A guess is worse than UNSURE.",
    "Questions: exactly one correct answer, answerable from this section. Explain each wrong mcq option.",
    "Do not add ✅ ⚠️ \U0001f4a1 symbols, and do not add new concept/formula blocks.",
    "Never delete a block to get past a check: fill it, or keep it and add skip: <reason>. Edit the draft only with "
    "your file-editing tool, never with shell commands (on Windows they destroy non-English text); if the draft is "
    "damaged, run the restore-draft command.",
]


def _language_rule(ws: Workspace) -> str:
    """Which language the writer's own words are in (the card and skeleton are in English; the notes may not be)."""
    from .lang import lang_name
    notes = get_key(ws.config, "output.language") or (ws.config.get("book") or {}).get("language") or "en"
    return (f"Write your own words (plain, why, examples, questions, options, explanations) in {lang_name(notes)}, "
            f"the language the student reads. Quotes stay exactly as the book writes them.")

CHECKER_RULES = [
    "Judge ONLY from the context line of each block. What you know about the subject does not count.",
    "SUPPORTED only if the context says the same thing: same numbers, signs, direction and conditions.",
    "Right idea but a condition or qualifier is missing or changed (e.g. 'at constant pressure', 'always') = PARTIAL.",
    "The claim adds something the context does not say (an extra reason, a contrast such as 'rather than ...', a "
    "wider scope) = PARTIAL, even when the rest is right.",
    "For SUPPORTED, copy the supporting words from the context into span: (at least 3 words).",
    "Otherwise write one sentence in problem: saying what is wrong.",
    "Some claims are planted false claims that test attention. Missing one means the whole batch is redone.",
    "Do not change claim: or context: lines.",
]

FRESH_NOTE = ("FRESH CONTEXT: if you can start a subagent or a new chat, give it this whole card and let it do the "
              "task. Otherwise do it yourself, but do not open the notes drafts: use only the worksheet.")


def render_card(ws: Workspace, t: Task) -> str:
    tier = tier_params(ws.tier)
    attempts = ws.state.get("attempts", {}).get(t.id, 0)
    out = [LINE, f"TASK  {t.id}" + (f"      {t.progress}" if t.progress else "") + f"      tier: {ws.tier}",
           f"ROLE  {t.role}" + ("  (fresh context)" if t.fresh else "")]
    if t.fresh:
        out.append(f"      {FRESH_NOTE}")
    out.append(f"GOAL  {t.goal}")
    if t.body:
        out.append("")
        out.append(t.body.rstrip())
    if t.read or t.edit:
        out.append("")
    for i, (p, note) in enumerate(t.read):
        out.append(("READ  " if i == 0 else "      ") + f"{p}" + (f"   ({note})" if note else ""))
    if t.edit:
        out.append(f"EDIT  {t.edit}")
    if t.rules:
        out.append("")
        out.append("RULES")
        for i, r in enumerate(t.rules, start=1):
            out.append(f"  {i}. " + r.format(qmin=tier["quote_min_words"], qmax=tier["quote_max_words"]))
    if t.kind not in ("done", "run-ingest", "run-ocr", "need-ocr-engine", "confirm-outline"):
        out.append("")
        out.append("DONE WHEN this command prints PASS:")
        out.append("  " + cmd(ws, "check"))
        if t.kind in ("write-section", "write-chapter", "fix"):
            left = tier["max_attempts"] - attempts
            if left > 0:
                out.append(f"If it prints FAIL, fix exactly the listed problems and run it again "
                           f"(attempt {attempts + 1} of {tier['max_attempts']}).")
            else:
                out.append("All attempts are used. To mark what still fails as UNSURE for a human to review, run:")
                out.append("  " + cmd(ws, "check", "--accept-flags"))
        if t.kind in ("write-section", "write-chapter"):
            out.append("Exact format of any block:  " + cmd(ws, "format").replace(_q(ws.root), "").rstrip() + " <kind>")
            out.append("Find where words appear:    " + cmd(ws, "find", '"some words"'))
    out.append(LINE)
    return "\n".join(out)


# =============================================================================== chapter state helpers

def _cs(ws: Workspace, ch: str) -> dict:
    return ws.state.setdefault("chapters", {}).setdefault(ch, {})


def _parts(ws: Workspace, ch: dict) -> list[dict]:
    """Section parts for a chapter; created once (with source files and skeletons) and then kept stable."""
    cs = _cs(ws, ch["id"])
    tier = tier_params(ws.tier)
    if "parts" not in cs:
        parts = section_parts(ws, ch, tier)
        if tier["whole_chapter_tasks"]:
            total = sum(estimate_tokens(" ".join(p["text"] for _, p in pt["pairs"])) for pt in parts)
            if total <= tier["max_source_tokens"] and len(parts) > 1:
                merged = {"id": ch["id"] + "-all", "section": None, "title": ch["title"], "part": None,
                          "pairs": [x for pt in parts for x in pt["pairs"]], "sections": [pt["section"] for pt in parts]}
                parts = [merged]
        cs["parts"] = []
        cs["expected"] = {}
        for pt in parts:
            if pt.get("sections"):
                text, expected, source = _merged_draft(ws, ch, pt, tier)
            else:
                text, expected, source = make_section_draft(ws, ch, pt, tier)
            src = ws.chapter_dir(ch["id"]) / "source" / f"{pt['id']}.md"
            dft = ws.draft_dir(ch["id"]) / f"{pt['id']}.md"
            write_text(src, source)
            if not dft.exists():
                write_text(dft, text)
            cs["parts"].append({"id": pt["id"], "title": pt["title"], "tokens": estimate_tokens(source)})
            cs["expected"][pt["id"]] = expected
        ws.save_state()
    return cs["parts"]


def _merged_draft(ws: Workspace, ch: dict, pt: dict, tier: dict):
    texts, expected, sources = [], {}, []
    for sid in pt["sections"]:
        sub = [p for p in section_parts(ws, ch, dict(tier, max_source_tokens=10 ** 9)) if p["section"] == sid][0]
        t, e, s = make_section_draft(ws, ch, sub, tier)
        texts.append(t)
        expected.update(e)
        sources.append(s)
    return "\n\n".join(texts), expected, "\n\n".join(sources)


def _chapter_draft(ws: Workspace, ch: dict) -> Path:
    cs = _cs(ws, ch["id"])
    path = ws.draft_dir(ch["id"]) / "chapter.md"
    if "chapter_expected" not in cs or not path.exists():
        text, expected, source = make_chapter_draft(ws, ch, tier_params(ws.tier))
        write_text(ws.chapter_dir(ch["id"]) / "source" / "chapter.md", source)
        if not path.exists():
            write_text(path, text)
        cs["chapter_expected"] = expected
        ws.save_state()
    return path


def _passed(cs: dict, key: str, path: Path) -> bool:
    return cs.get("passed", {}).get(key) == file_hash(path)


def lint_ctx(ws: Workspace, ch: str, mode: str, expected: dict, qindex: QuoteIndex | None = None) -> LintContext:
    tier = tier_params(ws.tier)
    inv = ws.inventory(ch)
    all_items = ws.all_inventory_items()
    known = set(all_items)
    for p in V.draft_files(ws, ch):
        for b in parse(read_text(p)).blocks:
            known.add(b.id)
    lang = ws.config.get("output", {}).get("language")
    book_lang = ws.config.get("book", {}).get("language") or "en"
    return LintContext(
        ws=ws, tier=tier, mode=mode, chapter=ch, expected=expected, known_ids=known,
        chapter_ids={it["id"] for it in inv["items"] if it["kind"] in ("term", "equation", "figure", "table", "example")},
        summary_ids=[it["id"] for it in inv["items"] if it["kind"] == "summary"],
        term_texts={it["id"]: it["text"] for it in inv["items"] if it["kind"] == "term"},
        min_questions=min(3, tier["questions_per_section"]),
        lang_differs=bool(lang and lang.split("-")[0] != book_lang.split("-")[0]),
        qindex=qindex or QuoteIndex(ws), notes_lang=lang or book_lang)


# =============================================================================== next

def compute_next(ws: Workspace, peek: bool = False) -> Task:
    """The current task. With peek=True nothing is consumed (a pending 'chapter ready' notice stays pending)."""
    st = ws.state
    cfg = ws.config
    if not st.get("stages", {}).get("ingest", {}).get("done"):
        return Task("run-ingest", "run-ingest", "runner", "Extract the book (text, pages, outline, figures).",
                    body="Run this command (usually seconds; up to a minute or two for a very big book):\n  " +
                         cmd(ws, "ingest") + "\nThen run:\n  " + cmd(ws, "next") + "\n" + NO_PDF_NOTE)
    if not st["stages"].get("inventory", {}).get("done"):
        from .inventory import build_inventory
        build_inventory(ws)
        ws.reload()
    if not get_key(cfg, "intake.done"):
        return _ocr_step(ws, before_intake=True) or _intake_task(ws)
    t = _ocr_step(ws, before_intake=False)
    if t is not None:
        return t
    if ws.state.get("outline_review"):
        return _outline_review_task(ws)
    from .materials import pending_material_task
    mt = pending_material_task(ws)
    if mt:
        return mt
    if not st.get("plan_confirmed"):
        from .priority import plan_summary
        return Task("confirm-plan", "confirm-plan", "talk to the user", "Show the study plan and get the user's OK.",
                    body="Show the user this plan (you may shorten it), ask whether it is right, apply any changes they "
                         "want with `config set`, then run:\n  " + cmd(ws, "plan", "--confirm") + "\n\n" +
                         plan_summary(ws))
    chapters = _chapter_order(ws)
    for i, ch in enumerate(chapters, start=1):
        t = _chapter_next(ws, ch, f"chapter {i} of {len(chapters)}", peek)
        if t is not None:
            return t
    from .build import build_all
    info = build_all(ws)
    return Task("done", "done", "talk to the user", "Everything is built and checked. Report to the user.",
                body=info["message"])


NO_PDF_NOTE = ("Do not open or read the book PDF yourself (no PDF reader, no page images): the scripts extract it "
               "much faster, and quotes are checked against their text.")


def _ocr_step(ws: Workspace, before_intake: bool) -> Task | None:
    """Scanned pages must be read with OCR before notes can be written. Before the intake questions this is done
    only when the whole book is quick to read (then the chapter list shown to the user is complete); otherwise
    only the pages of the exam scope are read, after the intake."""
    if get_key(ws.config, "ocr.skip"):
        return None
    from .ocr import fmt_duration, no_engine_help, pages_to_ocr, pick_engine
    todo = pages_to_ocr(ws, mode="chapters" if before_intake else "scope")
    if not todo:
        return None
    eng = pick_engine(ws)
    if before_intake and (eng is None or eng.estimate(len(todo), ws) > 150):
        return None
    if eng is None:
        return Task("need-ocr-engine", "need-ocr-engine", "talk to the user",
                    f"{len(todo)} scanned pages of the exam scope cannot be read: no OCR engine. Ask the user.",
                    body=no_engine_help(ws) + "\n\nTell the user this in plain words and do what they choose. Then run:"
                                              "\n  " + cmd(ws, "next"))
    where = "of the book" if before_intake else "in the exam scope"
    est = fmt_duration(eng.estimate(len(todo), ws))
    body = (f"{len(todo)} pages {where} are scans without a text layer. They are read with OCR "
            f"(engine: {eng.name}, {eng.workers} worker(s), about {est}).\n"
            f"Run this command:\n  {cmd(ws, 'ocr')}\n"
            "It prints progress and stops by itself after at most 9 minutes. If it ends with NOT FINISHED, run the "
            "same command again: pages already read are kept.\n"
            "If your command tool has a time limit under 10 minutes, run the command in the background or with a "
            "longer timeout; follow the progress with:\n  " + cmd(ws, "status") + "\n"
            "When it prints OCR DONE, run:\n  " + cmd(ws, "next") + "\n" + NO_PDF_NOTE)
    return Task("run-ocr", "run-ocr", "runner", f"Read {len(todo)} scanned pages with OCR (about {est}).", body=body)


def _outline_review_task(ws: Workspace) -> Task:
    from .outline_edit import outline_text
    body = ("The chapter list was rebuilt from the text read by OCR (the book has no contents in the file), so it is "
            "a guess. Show it to the user (you may shorten it) and ask whether the chapters and sections are right.\n\n" +
            outline_text(ws) + "\n\nIf it is right, run:\n  " + cmd(ws, "outline", "--confirm") +
            "\nIf not, save the corrected list in the same format to a text file (see references/workflow.md, "
            "'Fixing the outline') and run:\n  " + cmd(ws, "outline", "--from-text", "<file>") +
            "\nThen run:\n  " + cmd(ws, "next"))
    return Task("confirm-outline", "confirm-outline", "talk to the user",
                "Get the user's OK on the chapter list found in the OCR text.", body=body)


def _chapter_order(ws: Workspace) -> list[dict]:
    order = ws.state.get("plan", {}).get("order")
    chapters = ws.chapters_in_scope()
    if order:
        idx = {cid: i for i, cid in enumerate(order)}
        chapters = sorted(chapters, key=lambda c: idx.get(c["id"], 999))
    return chapters


def _intake_task(ws: Workspace) -> Task:
    outline = ws.outline
    lines = []
    for c in outline["chapters"]:
        secs = [s for s in c["sections"] if s["kind"] == "content"]
        a = ws.pages[c["start"]["page"]]["label"]
        last = c["end"]["page"] - (1 if c["end"]["y"] <= 100 and c["end"]["page"] > c["start"]["page"] else 0)
        b = ws.pages[min(last, len(ws.pages) - 1)]["label"]
        lines.append(f"   {c['id']:<6} {c['title'][:44]:<44} {len(secs)} sections   pages {a}-{b}")
    other = ", ".join(o["title"] for o in outline.get("other", [])) or "none"
    warn = ""
    if outline.get("needs_review") and outline.get("method") != "fallback":
        warn = ("\nNOTE: the book has no usable table of contents; the chapters above were guessed from headings. "
                "Ask the user to confirm them. To correct them, write an outline file (see references/workflow.md, "
                "'Fixing the outline') and run: " + cmd(ws, "outline", "--from-text", "<file>") + "\n")
    from .ocr import pages_to_ocr
    scanned = pages_to_ocr(ws, mode="chapters") if not get_key(ws.config, "ocr.skip") else []
    if scanned:
        warn += (f"\nNOTE: {len(scanned)} of {len(ws.pages)} pages are scans without text. After these questions only "
                 "the pages on the exam are read with OCR, so ask precisely which chapters or pages the exam covers.\n")
        if outline.get("label_method") == "pdf-index":
            warn += ("NOTE: this scan's printed page numbers are not known yet. Ask for the pages as the user's PDF "
                     "viewer numbers them (1 = the first page of the file), not as printed on the paper.\n")
    if outline.get("method") == "fallback":
        l1, l2 = (("(PDF viewer page numbers:", "1 = first page of the file)")
                  if outline.get("label_method") == "pdf-index" else ("(printed page numbers,", "or PDF page numbers)"))
        q4 = (f"  4. Which pages are on the exam? {l1}\n" + f"     {l2}".ljust(60) +
              "-> scope.pages 45-120, 130-140   and\n" + " " * 60 + "   scope.chapters all")
        q5 = "  5. (No chapter list could be found; it is built after the pages are read.)"
    else:
        q4 = ("  4. Which chapters are on the exam? (list above)".ljust(60) + "-> scope.chapters all   or   ch01,ch02\n" +
              "     Only part of a chapter? Also give the pages:".ljust(60) + "-> scope.pages 45-120")
        q5 = "  5. Does the chapter list above look right?"
    missing = [k for k in REQUIRED_INTAKE if get_key(ws.config, k) in (None, "", [])]
    q8 = f"  8. Language for your notes? (book: {ws.config.get('book', {}).get('language', 'en')})".ljust(60)
    body = f"""Book: "{ws.config.get('title')}" ({len(ws.pages)} pages). Detected chapters:
{chr(10).join(lines)}
   (not treated as chapters: {other})
{warn}
Ask the user these questions in ONE message:
  1. When is the exam?                                      -> exam.date YYYY-MM-DD
  2. Which question formats: multiple choice, short answer,
     problems/calculations, essay?                           -> exam.formats mcq,short-answer,problems,essay
  3. Closed book, open book, or one cheat sheet allowed?     -> exam.book_policy closed|open|cheat-sheet
{q4}
{q5}
  6. Subject area?                                           -> subject general|math-physics|chemistry|
                                                                biology-medicine|history-social|law|
                                                                computer-science|economics-business|languages
  7. How many hours per day can you study?                   -> study.hours_per_day 2
{q8}-> output.language en
  9. Do you have past exam papers, a syllabus, or lecture slides? For each file:
       {cmd(ws, 'add-material', '<file>', '--kind', 'past-paper|syllabus|slides')}

Save every answer:   {cmd(ws, 'config', 'set', '<key>', '<value>')}
Then finish with:    {cmd(ws, 'config', 'set', 'intake.done', 'true')}
If the user says "you decide": formats mcq,short-answer; book_policy closed; chapters all; 2 hours per day;
notes in the book's language; subject from the book's title. Leave exam.date unset if unknown.
Still missing: {', '.join(missing) or 'nothing'}"""
    return Task("intake", "intake", "talk to the user", "Ask the user about the exam, then save the answers.", body=body)


def _chapter_next(ws: Workspace, ch: dict, progress: str, peek: bool = False) -> Task | None:
    cid = ch["id"]
    cs = _cs(ws, cid)
    tier = tier_params(ws.tier)
    if not peek:                          # `status` only looks; pictures are made when the chapter is worked on
        from .media import ensure_chapter_media
        ensure_chapter_media(ws, ch)      # figure/equation pictures, made only for chapters that are studied
    parts = _parts(ws, ch)
    # 0. drafts edited after they passed (usually during a fix task): re-check them quietly
    _relint_changed(ws, ch, cs, parts)
    # 1. section drafts
    for i, pt in enumerate(parts, start=1):
        path = ws.draft_dir(cid) / f"{pt['id']}.md"
        if not _passed(cs, pt["id"], path):
            src = ws.chapter_dir(cid) / "source" / f"{pt['id']}.md"
            read = [(src, f"the book text for this task, ~{pt['tokens']} tokens"),
                    (REFS_DIR / "examples" / "section-example.md", "a finished example: copy its style")]
            profile = REFS_DIR / "subjects" / f"{ws.config.get('subject') or 'general'}.md"
            if profile.exists():
                read.append((profile, "what matters most in this subject (short)"))
            return Task(f"write-section:{cid}:{pt['id']}", "write-section", "writer",
                        f"Write study notes for section {pt['id']} \"{pt['title']}\" by filling the draft, using ONLY "
                        "the book text in the source file.", chapter=cid, edit=path, read=read,
                        rules=[_language_rule(ws)] + WRITER_RULES, progress=f"{progress} · section {i} of {len(parts)}",
                        extra={"part": pt["id"]})
    # 2. chapter draft
    cpath = _chapter_draft(ws, ch)
    if not _passed(cs, "chapter", cpath):
        return Task(f"write-chapter:{cid}", "write-chapter", "writer",
                    f"Write the chapter-level blocks for {cid} \"{ch['title']}\": overview, must-know list (covering "
                    "the book's summary), concept map, and comparison tables.", chapter=cid, edit=cpath,
                    read=[(ws.chapter_dir(cid) / "source" / "chapter.md", "the whole chapter text"),
                          (REFS_DIR / "examples" / "chapter-example.md", "a finished example: copy its style")],
                    rules=[_language_rule(ws)] + WRITER_RULES[:2] + [
                        "must-know: every SUM- item listed in the comment must appear in some (covers: ...).",
                        "map: link: lines use only IDs from the comment above the map block.",
                        "compare: if the two items are not really confusable, keep the block and add skip: <reason>."] +
                    WRITER_RULES[4:5] + WRITER_RULES[6:], progress=progress)
    # 3. open worksheets first (a regenerated or half-done batch)
    keys = read_json(ws.verify_dir(cid) / ".keys.json", {}) or {}
    for name in sorted(keys):
        if name.startswith("claims-"):
            return _verify_claims_task(ws, cid, name, progress)
    for name in sorted(keys):
        if name == "formulas" and "salt" in keys[name]:
            return _formula_task(ws, cid, progress)
    for name in sorted(keys):
        if name.startswith("solve-"):
            return _solve_task(ws, cid, name, progress)
    if "reconcile" in keys and "salt" in keys["reconcile"]:
        return _reconcile_task(ws, cid, progress)
    # 4. new worksheets for anything unverified
    names = V.make_claim_batches(ws, cid, tier)
    if names:
        return _verify_claims_task(ws, cid, names[0], progress)
    if V.make_formula_batch(ws, cid):
        return _formula_task(ws, cid, progress)
    names = V.make_solve_batches(ws, cid, tier)
    if names:
        return _solve_task(ws, cid, names[0], progress)
    if V.make_reconcile_batch(ws, cid, tier):
        return _reconcile_task(ws, cid, progress)
    # 5. fixes
    fixes = V.fix_list(ws, cid, tier)
    if any(fixes.values()):
        return _fix_task(ws, ch, fixes, progress)
    # 6. build this chapter and tell the user
    from .build import build_chapter
    h = _drafts_hash(ws, cid)
    if cs.get("built_hash") != h:
        info = build_chapter(ws, cid)
        cs["built_hash"] = h
        cs["built_info"] = info
        cs["notified"] = False
        ws.save_state()
    if not cs.get("notified"):
        if peek:
            return Task(f"notify:{cid}", "notify", "talk to the user", "Tell the user a chapter is ready.")
        cs["notified"] = True
        ws.save_state()
        info = cs.get("built_info", {})
        nxt = compute_next(ws)
        body = ("Tell the user now (they can start studying this chapter while you continue):\n"
                f"  Chapter {cid} \"{ch['title']}\" is ready: {info.get('url', '')}\n"
                f"  {info.get('summary', '')}\n\nThen continue with the next task:\n\n" + render_card(ws, nxt))
        return Task(f"notify:{cid}", "notify", "talk to the user", "Tell the user a chapter is ready.", body=body)
    return None


def _relint_changed(ws: Workspace, ch: dict, cs: dict, parts: list[dict]) -> None:
    """A draft that passed before and was edited since is re-linted here. If it still passes, its new hash is
    recorded and work continues without an extra task; if not, the normal write task will show the errors."""
    passed = cs.get("passed", {})
    targets = [(pt["id"], ws.draft_dir(ch["id"]) / f"{pt['id']}.md", "section", cs.get("expected", {}).get(pt["id"], {}))
               for pt in parts]
    targets.append(("chapter", ws.draft_dir(ch["id"]) / "chapter.md", "chapter", cs.get("chapter_expected", {})))
    changed = False
    for key, path, mode, expected in targets:
        if key not in passed or not path.exists() or passed[key] == file_hash(path):
            continue
        text = read_text(path)
        fixed, _ = autofix(text)
        if fixed != text:
            write_text(path, fixed)
        res = lint_notes(parse(fixed, path), lint_ctx(ws, ch["id"], mode, expected))
        if res.ok:
            passed[key] = file_hash(path)
            changed = True
    if changed:
        ws.state.get("pending_fix", {}).pop(ch["id"], None)
        ws.save_state()


def _drafts_hash(ws: Workspace, cid: str) -> str:
    return "|".join(file_hash(p) or "" for p in V.draft_files(ws, cid))


def _verify_claims_task(ws: Workspace, cid: str, name: str, progress: str) -> Task:
    path = ws.verify_dir(cid) / f"{name}.md"
    return Task(f"verify-claims:{cid}:{name}", "verify-claims", "independent checker",
                "For each claim, decide whether its context (text copied from the book) supports it.", chapter=cid,
                edit=path, read=[(REFS_DIR / "examples" / "verify-example.md", "how a finished worksheet looks")],
                rules=CHECKER_RULES, fresh=True, progress=progress, worksheet=name)


def _formula_task(ws: Workspace, cid: str, progress: str) -> Task:
    return Task(f"verify-formulas:{cid}", "verify-formulas", "independent checker",
                "Compare each LaTeX formula with the formula printed in the book.", chapter=cid,
                edit=ws.verify_dir(cid) / "formulas.md",
                rules=["MATCH only if symbols, signs, powers, fractions and subscripts all agree.",
                       "book-line is extracted text: subscripts appear as _x and superscripts as ^x.",
                       "If you can view images, open the image: file and compare with it.",
                       "CANNOT_TELL if the book line is too garbled and you cannot view the image.",
                       "Some formulas are deliberately wrong to test attention.",
                       "Do not change latex:, book-line: or image: lines."],
                fresh=True, progress=progress, worksheet="formulas")


def _solve_task(ws: Workspace, cid: str, name: str, progress: str) -> Task:
    return Task(f"solve:{cid}:{name}", "solve", "independent solver",
                "Answer each question yourself from its context line. You cannot see the answer key.", chapter=cid,
                edit=ws.verify_dir(cid) / f"{name}.md",
                read=[(REFS_DIR / "examples" / "solve-example.md", "how a finished worksheet looks")],
                rules=["Use ONLY the context line of each question.",
                       "mcq: one letter, and only-one-correct: yes only if exactly one option is right.",
                       "numeric: answer like 15.7[kJ] and show the calc: line (the script checks it).",
                       "evidence: copy the exact words from the context that decide the answer.",
                       "Do not change question:, option, type: or context: lines."],
                fresh=True, progress=progress, worksheet=name)


def _reconcile_task(ws: Workspace, cid: str, progress: str) -> Task:
    return Task(f"reconcile:{cid}", "reconcile", "independent judge",
                "Decide, from the context only, whether each answer key or the independent answer is right.",
                chapter=cid, edit=ws.verify_dir(cid) / "reconcile.md",
                rules=["Decide from the context line only.",
                       "SAME if both answers say the same thing; KEY_WRONG if only the independent answer is right; "
                       "MINE_WRONG if only the key is right; AMBIGUOUS if the question allows several answers.",
                       "Some keys are deliberately wrong to test attention.",
                       "Do not change question:, key-answer:, your-answer: or context: lines."],
                fresh=True, progress=progress, worksheet="reconcile")


def _fix_task(ws: Workspace, ch: dict, fixes: dict, progress: str) -> Task:
    cid = ch["id"]
    lines = []
    n = 0
    for c, v in fixes["claims"]:
        n += 1
        lines.append(f"{n}. {c.file} line {c.line} [{c.block_id}] {c.field}: \"{c.text[:160]}\"\n"
                     f"   checker: {v['verdict']} — {v.get('problem') or 'no reason given'}\n"
                     f"   book text: {c.context[:300]}")
    for f, v in fixes["formulas"]:
        n += 1
        lines.append(f"{n}. {f['file']} line {f['line']} [{f['block']}] latex: {f['latex']}\n"
                     f"   checker: MISMATCH — {v.get('problem') or ''}\n   book prints: {f['book']}"
                     + (f"   (image: {ws.root / f['image']})" if f['image'] != 'none' else ""))
    for q, e in fixes["questions"]:
        n += 1
        lines.append(f"{n}. {q.file} line {q.line} [{q.block_id}] question: \"{q.ask[:140]}\" (key: {q.answer})\n"
                     f"   checker: {e.get('reason', 'answer key disputed')}; independent answer: {e.get('mine', '')}")
    ws.state.setdefault("pending_fix", {})[cid] = {
        "claims": [c.id for c, _ in fixes["claims"]], "formulas": [f["id"] for f, _ in fixes["formulas"]],
        "questions": [q.hash for q, _ in fixes["questions"]]}
    ws.save_state()
    body = ("The independent checks found these problems. For each one, correct the draft line so it matches the book "
            "(better quote, added condition, corrected number or answer), or replace the value with UNSURE: <reason>. "
            "For a disputed question you may also fix the question, or add skip: <reason> to the question block.\n\n"
            + "\n\n".join(lines))
    return Task(f"fix:{cid}", "fix", "writer", f"Fix {n} problem(s) the independent checks found in {cid}.",
                chapter=cid, body=body, progress=progress,
                read=[(ws.draft_dir(cid), "the draft files named above")],
                rules=["Change only the listed lines (and fields in the same block if needed).",
                       "Every changed claim still ends with [p.N: \"exact words\"] copied exactly.",
                       "Do not argue with the checker in the notes: fix the claim, or mark it UNSURE.",
                       _language_rule(ws), WRITER_RULES[-1]])


# =============================================================================== check

@dataclass
class CheckResult:
    ok: bool
    text: str


def check(ws: Workspace, accept_flags: bool = False, only_file: Path | None = None) -> CheckResult:
    if only_file is not None:
        return _check_file(ws, only_file)
    task = compute_next(ws)
    st = ws.state
    attempts = st.setdefault("attempts", {})
    kind = task.kind
    if kind == "done":
        return CheckResult(True, "PASS — nothing left to do.\n\n" + render_card(ws, task))
    if kind == "run-ingest":
        return CheckResult(False, "FAIL — the book has not been extracted yet.\n\n" + render_card(ws, task))
    if kind == "run-ocr":
        return CheckResult(False, "FAIL — scanned pages still need OCR. " + task.goal + "\n\n" + render_card(ws, task))
    if kind == "need-ocr-engine":
        return CheckResult(False, "FAIL — no OCR engine yet; the user has to choose an option.\n\n" +
                           render_card(ws, task))
    if kind == "confirm-outline":
        return CheckResult(False, "NOT YET — the chapter list needs the user's OK first.\n\n" + render_card(ws, task))
    if kind == "notify":
        return CheckResult(True, "PASS\n\n" + render_card(ws, compute_next(ws)))
    if kind == "intake":
        missing = [k for k in REQUIRED_INTAKE if get_key(ws.config, k) in (None, "", [])]
        if missing or not get_key(ws.config, "intake.done"):
            return CheckResult(False, "FAIL — still missing: " + (", ".join(missing) or "intake.done") +
                               "\n\n" + render_card(ws, task))
        return _pass(ws, task)
    if kind == "confirm-plan":
        return CheckResult(False, "NOT YET — the study plan needs the user's OK first. Current task:\n\n" +
                           render_card(ws, task))
    if kind == "map-material":
        from .materials import check_material_task
        ok, msg = check_material_task(ws, task)
        if not ok:
            attempts[task.id] = attempts.get(task.id, 0) + 1
            ws.save_state()
            return CheckResult(False, msg)
        return _pass(ws, task, msg)
    if kind in ("write-section", "write-chapter"):
        return _check_write(ws, task, accept_flags)
    if kind in ("verify-claims", "verify-formulas", "solve", "reconcile"):
        return _check_worksheet(ws, task)
    if kind == "fix":
        return _check_fix(ws, task, accept_flags)
    return CheckResult(False, f"Unknown task kind {kind}.")


def _pass(ws: Workspace, task: Task, msg: str = "") -> CheckResult:
    ws.state.setdefault("attempts", {}).pop(task.id, None)
    ws.save_state()
    nxt = compute_next(ws)
    head = "PASS" + (f" — {msg}" if msg else "")
    return CheckResult(True, head + "\n\nNext task:\n" + render_card(ws, nxt))


def _format_issues(ws: Workspace, path: Path, issues, attempt: int, max_attempts: int, limit: int = 25) -> str:
    order = {"format": 0, "evidence": 1, "coverage": 2}
    errs = sorted([i for i in issues if i.level == "error"], key=lambda i: (order.get(i.category, 3), i.line))
    warns = [i for i in issues if i.level == "warn"]
    out = [f"FAIL — {len(errs)} problem(s) in {path} (attempt {attempt} of {max_attempts})"]
    for n, i in enumerate(errs[:limit], start=1):
        where = f"line {i.line} " if i.line else ""
        blk = f"[{i.block}] " if i.block else ""
        out.append(f"  {n}. {where}{blk}{i.message}")
        if i.hint:
            out.append(f"     Fix: {i.hint}")
    if len(errs) > limit:
        out.append(f"  ... and {len(errs) - limit} more. Fix these first, then check again.")
    if warns:
        out.append(f"Warnings (not blocking): " + "; ".join(f"line {w.line}: {w.message}" for w in warns[:6]))
    out.append("Then run the same check command again.")
    return "\n".join(out)


def draft_damage(text: str) -> str | None:
    """Why a draft looks destroyed rather than merely wrong: text saved in the wrong encoding (Windows PowerShell 5.1
    writes the ANSI code page, so Chinese becomes '????'), or no ::: blocks left at all."""
    from .ingest import garble_ratio
    if "�" in text:
        return "it contains replacement characters (�): the text was saved in the wrong encoding"
    if len(re.findall(r"\?{3,}", text)) >= 2:
        return "runs of '???' stand where the text was: the file was saved in the wrong encoding"
    if garble_ratio(text) > 0.05:
        return "the text is garbled (letters such as 'Ã¤Ã¶'): the file was saved in the wrong encoding"
    if not re.search(r"^:::\s*\S", text, re.M):
        return "it has no ':::' blocks left"
    return None


def restore_draft(ws: Workspace) -> str:
    """Put the current write task's draft back to the skeleton the scripts made; the old file is kept as .bak."""
    import shutil
    task = compute_next(ws)
    if task.kind not in ("write-section", "write-chapter") or task.edit is None:
        raise ESError(f"The current task ({task.id}) has no draft to restore.",
                      "Only the drafts of write-section and write-chapter tasks can be restored.")
    ch = ws.chapter(task.chapter)
    tier = tier_params(ws.tier)
    if task.kind == "write-chapter":
        text = make_chapter_draft(ws, ch, tier)[0]
    else:
        part_id = task.extra["part"]
        parts = section_parts(ws, ch, tier)
        pt = next((p for p in parts if p["id"] == part_id), None)
        if pt is None:                               # a whole-chapter task (frontier tier)
            merged = {"id": part_id, "sections": [p["section"] for p in parts]}
            text = _merged_draft(ws, ch, merged, tier)[0]
        else:
            text = make_section_draft(ws, ch, pt, tier)[0]
    path = task.edit
    backup = path.with_name(path.name + ".bak")
    if path.exists():
        shutil.copyfile(path, backup)
    write_text(path, text)
    restores = ws.state.setdefault("restores", {})
    if not restores.get(task.id):                    # the first restore gives the fresh draft fresh attempts
        ws.state.setdefault("attempts", {}).pop(task.id, None)
    restores[task.id] = restores.get(task.id, 0) + 1
    ws.save_state()
    return (f"Restored {path} to the draft the scripts made" + (f" (your version: {backup.name})" if backup.exists()
                                                                   else "") +
            ". Fill it in again with your file editor, then run:\n  " + cmd(ws, "check"))


def _check_write(ws: Workspace, task: Task, accept_flags: bool) -> CheckResult:
    cid = task.chapter
    cs = _cs(ws, cid)
    tier = tier_params(ws.tier)
    path = task.edit
    text = read_text(path)
    damage = draft_damage(text)
    if damage:
        return CheckResult(False, f"FAIL — {path} looks damaged: {damage}.\n"
                                  f"  Fix: put the script's draft back with\n    {cmd(ws, 'restore-draft')}\n"
                                  "  and fill it in again with your file-editing tool. Never rewrite drafts with shell "
                                  "commands (Set-Content, Out-File, echo >): on Windows they destroy non-English text.")
    fixed, notes = autofix(text)
    if fixed != text:
        write_text(path, fixed)
    doc = parse(fixed, path)
    if task.kind == "write-section":
        expected = cs["expected"][task.extra["part"]]
        mode, key = "section", task.extra["part"]
    else:
        expected = cs["chapter_expected"]
        mode, key = "chapter", "chapter"
    res = lint_notes(doc, lint_ctx(ws, cid, mode, expected))
    attempts = ws.state.setdefault("attempts", {})
    note = ("Auto-fixed: " + "; ".join(notes) + "\n") if notes else ""
    if res.ok:
        cs.setdefault("passed", {})[key] = file_hash(path)
        cs.setdefault("stats", {})[key] = {k: v for k, v in res.stats.items()}
        ws.save_state()
        warn = [i for i in res.issues if i.level == "warn"]
        msg = f"{res.stats['claims']} cited claims, {res.stats['questions']} questions" + \
              (f", {len(warn)} warning(s)" if warn else "")
        r = _pass(ws, task, msg)
        return CheckResult(True, note + r.text)
    n = attempts.get(task.id, 0) + 1
    attempts[task.id] = n
    ws.save_state()
    if accept_flags and n > tier["max_attempts"]:
        flagged = accept_with_flags(path, doc, res.issues)
        # blocks the writer deleted come back as explicit skips, so the report shows what the notes leave out
        missing = [i for i in res.issues if i.code == "block-missing"]
        if missing:
            stubs = []
            for i in missing:
                m = re.match(r"The (\S+) block (\S+) was deleted", i.message)
                if m:
                    stubs.append(f"::: {m.group(1)} {m.group(2)}\nskip: deleted by the writer, so not covered in "
                                 f"these notes; check it in the book\n:::")
                    flagged.append(f"{m.group(2)}: deleted by the writer (not covered)")
            write_text(path, read_text(path).rstrip("\n") + "\n\n" + "\n\n".join(stubs) + "\n")
        doc2 = parse(read_text(path), path)
        res2 = lint_notes(doc2, lint_ctx(ws, cid, mode, expected))
        blocking = [i for i in res2.errors if i.category == "format"]
        if not blocking:
            cs.setdefault("passed", {})[key] = file_hash(path)
            cs.setdefault("flags", {})[key] = flagged
            ws.save_state()
            r = _pass(ws, task, f"accepted with {len(flagged)} item(s) marked UNSURE for human review")
            return CheckResult(True, note + r.text)
        return CheckResult(False, note + _format_issues(ws, path, res2.issues, n, tier["max_attempts"]))
    body = _format_issues(ws, path, res.issues, n, tier["max_attempts"])
    if sum(1 for i in res.issues if i.code in ("unknown-id", "block-missing", "kind-changed")) >= 3:
        body += ("\nThe draft's blocks no longer match the ones the script made. Put them back with\n  " +
                 cmd(ws, "restore-draft") + "\n(your version is kept as a .bak file), then fill the blocks in.")
    if n >= tier["max_attempts"]:
        body += ("\nThat was the last regular attempt. Fix what you can, then run:\n  " +
                 cmd(ws, "check", "--accept-flags") + "\nto mark whatever still fails as UNSURE for a human to review.")
    return CheckResult(False, note + body)


def accept_with_flags(path: Path, doc, issues) -> list[str]:
    """Turn remaining problems into explicit UNSURE / skip markers so the pipeline can continue honestly."""
    from .schema import SCHEMAS
    lines = read_text(path).split("\n")
    flagged: list[str] = []
    by_line: dict[int, list] = {}
    for i in issues:
        if i.level == "error" and i.line:
            by_line.setdefault(i.line, []).append(i)
    block_at = {}
    for b in doc.blocks:
        for ln in range(b.line, (b.end_line or b.line) + 1):
            block_at[ln] = b
    skip_blocks: set[int] = set()
    drop: set[int] = set()
    for ln, iss in by_line.items():
        b = block_at.get(ln)
        raw = lines[ln - 1] if ln - 1 < len(lines) else ""
        m = re.match(r"^(\s*)([A-Za-z][\w -]*?):\s?(.*)$", raw)
        if b is None:
            drop.add(ln)
            continue
        schema = SCHEMAS.get(b.kind)
        if m and ln != b.line:
            key = m.group(2).strip().lower()
            fs = next((f for f in schema.fields if f.key == key), None) if schema else None
            if "<<OPTIONAL" in raw:
                drop.add(ln)
                continue
            if fs is not None and fs.allow_unsure and not fs.readonly:
                reason = iss[0].code
                lines[ln - 1] = f"{key}: UNSURE: could not be verified automatically ({reason})"
                flagged.append(f"{b.id}.{key}: {iss[0].message}")
                continue
        skip_blocks.add(b.line)
        flagged.append(f"{b.id}: {iss[0].message}")
    for b in doc.blocks:
        if b.line in skip_blocks and not b.get("skip"):
            lines[b.line - 1] = lines[b.line - 1] + "\nskip: could not be completed and verified automatically"
    # placeholders left anywhere
    out = []
    for i, raw in enumerate(lines, start=1):
        if i in drop:
            continue
        if "<<OPTIONAL" in raw:
            continue
        if "<<FILL" in raw:
            m = re.match(r"^(\s*)([A-Za-z][\w -]*?):", raw)
            key = m.group(2).strip().lower() if m else ""
            out.append(f"{key}: UNSURE: not filled" if key else "")
            flagged.append(f"{key or 'line'} {i}: left unfilled")
            continue
        out.append(raw)
    write_text(path, "\n".join(out))
    return flagged


def _check_worksheet(ws: Workspace, task: Task) -> CheckResult:
    cid = task.chapter
    tier = tier_params(ws.tier)
    name = task.worksheet
    meta = read_json(ws.verify_dir(cid) / f"{name}.json", {})
    path = task.edit
    text = read_text(path)
    fixed, notes = autofix(text)
    fixed, n_ro = restore_readonly(fixed, meta.get("originals", {}))
    if n_ro:
        notes.append(f"put back {n_ro} read-only line(s) that were changed (never edit claim/context/question lines)")
    if fixed != text:
        write_text(path, fixed)
    doc = parse(fixed, path)
    res = lint_worksheet(doc, meta.get("originals", {}), meta.get("kind"))
    attempts = ws.state.setdefault("attempts", {})
    note = ("Auto-fixed: " + "; ".join(notes) + "\n") if notes else ""
    if not res.ok:
        n = attempts.get(task.id, 0) + 1
        attempts[task.id] = n
        ws.save_state()
        return CheckResult(False, note + _format_issues(ws, path, res.issues, n, tier["max_attempts"]))
    if task.kind == "verify-claims":
        out = V.score_claim_batch(ws, cid, name, tier)
    elif task.kind == "verify-formulas":
        out = V.score_formula_batch(ws, cid, tier)
    elif task.kind == "solve":
        out = V.score_solve_batch(ws, cid, name)
    else:
        out = V.score_reconcile(ws, cid, tier)
    if out["status"] == "rejected":
        attempts[task.id] = attempts.get(task.id, 0) + 1
        ws.save_state()
        return CheckResult(False, note + "FAIL — " + out["message"] + "\n\n" + render_card(ws, compute_next(ws)))
    log = ws.state.setdefault("log", [])
    log.append({"task": task.id, "result": out["message"]})
    return CheckResult(True, note + _pass(ws, task, out["message"]).text)


def _check_fix(ws: Workspace, task: Task, accept_flags: bool) -> CheckResult:
    cid = task.chapter
    cs = _cs(ws, cid)
    tier = tier_params(ws.tier)
    pending = ws.state.get("pending_fix", {}).get(cid, {})
    # all drafts must still pass the linter
    problems = []
    for path in V.draft_files(ws, cid):
        text = read_text(path)
        fixed, _ = autofix(text)
        if fixed != text:
            write_text(path, fixed)
        doc = parse(fixed, path)
        if path.name == "chapter.md":
            expected, mode, key = cs["chapter_expected"], "chapter", "chapter"
        else:
            key = path.stem
            expected, mode = cs["expected"].get(key, {}), "section"
        res = lint_notes(doc, lint_ctx(ws, cid, mode, expected))
        if res.ok:
            cs.setdefault("passed", {})[key] = file_hash(path)
        else:
            problems.append(_format_issues(ws, path, res.issues, 1, 1, limit=10))
    claims_now = {c.id for c in V.extract_claims(ws, cid)}
    forms_now = {f["id"] for f in V.formula_items(ws, cid)}
    qs_now = {q.hash for q in V.extract_questions(ws, cid)}
    unchanged = [x for x in pending.get("claims", []) if x in claims_now] + \
                [x for x in pending.get("formulas", []) if x in forms_now] + \
                [x for x in pending.get("questions", []) if x in qs_now]
    attempts = ws.state.setdefault("attempts", {})
    if problems or unchanged:
        n = attempts.get(task.id, 0) + 1
        attempts[task.id] = n
        ws.save_state()
        if accept_flags and n > tier["max_attempts"] and not problems:
            V.give_up(ws, cid, V.fix_list(ws, cid, tier))
            ws.state.get("pending_fix", {}).pop(cid, None)
            ws.save_state()
            return _pass(ws, task, "remaining disputed items stay marked for human review")
        msg = "FAIL — "
        if unchanged:
            msg += f"{len(unchanged)} listed item(s) are unchanged. Change each one or mark it UNSURE.\n"
        if problems:
            msg += "\n".join(problems)
        return CheckResult(False, msg + "\n\n" + render_card(ws, task))
    ws.state.get("pending_fix", {}).pop(cid, None)
    ws.save_state()
    return _pass(ws, task, "fixes accepted; the changed items will be re-checked")


def _check_file(ws: Workspace, path: Path) -> CheckResult:
    """Lint any draft file on demand (used by humans and by `check --file`)."""
    path = path.resolve()
    cid = path.parent.parent.name
    cs = _cs(ws, cid)
    fixed, notes = autofix(read_text(path))
    doc = parse(fixed, path)
    if path.name == "chapter.md":
        expected, mode = cs.get("chapter_expected", {}), "chapter"
    else:
        expected, mode = cs.get("expected", {}).get(path.stem, {}), "section"
    res = lint_notes(doc, lint_ctx(ws, cid, mode, expected))
    if res.ok:
        return CheckResult(True, f"PASS — {path}")
    return CheckResult(False, _format_issues(ws, path, res.issues, 1, 1))


# =============================================================================== status

def status_text(ws: Workspace) -> str:
    st = ws.state
    lines = [f"ExamScribe workspace: {ws.root}", f"Book: {ws.config.get('title')}   tier: {ws.tier}"]
    if not st.get("stages", {}).get("ingest", {}).get("done"):
        return "\n".join(lines + ["Stage: book not extracted yet."])
    lines.append(f"Intake: {'done' if get_key(ws.config, 'intake.done') else 'not done'}   "
                 f"Plan: {'confirmed' if st.get('plan_confirmed') else 'not confirmed'}")
    from .ocr import ocr_status
    oc = ocr_status(ws)
    if oc["scanned"]:
        lines.append(f"OCR: {oc['done']} of {oc['scanned']} scanned pages " +
                     ("in the exam scope " if get_key(ws.config, "intake.done") else "") + "read" +
                     (" (skipped by setting ocr.skip)" if get_key(ws.config, "ocr.skip") else ""))
    for ch in ws.chapters_in_scope():
        cs = st.get("chapters", {}).get(ch["id"], {})
        parts = cs.get("parts", [])
        passed = sum(1 for p in parts if cs.get("passed", {}).get(p["id"]))
        tr = None
        if ws.verify_dir(ch["id"]).exists():
            try:
                tr = V.chapter_trust(ws, ch["id"])["counts"]
            except Exception:
                tr = None
        vt = f"verified {tr['ok']}, flagged {tr['warn']}, pending {tr['pending']}" if tr else "not verified yet"
        built = "built" if cs.get("built_hash") else ""
        lines.append(f"  {ch['id']:<6} {ch['title'][:40]:<40} sections {passed}/{len(parts) or '?'}  "
                     f"chapter-blocks {'ok' if cs.get('passed', {}).get('chapter') else '-'}  {vt}  {built}")
    try:
        t = compute_next(ws, peek=True)
        lines.append(f"Next task: {t.id} — {t.goal}")
    except ESError as exc:
        lines.append(f"Next task: blocked ({exc})")
    return "\n".join(lines)
