"""Shared test helpers: sample book, ready workspaces, fixture drafts, and an oracle checker."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("EXAMSCRIBE_SKILL") or ROOT / "exam-scribe")      # another copy can be tested
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
os.environ.setdefault("EXAMSCRIBE_TODAY", "2026-09-27")

BOOK = ROOT / "tests" / "fixtures" / "out" / "sample-textbook.pdf"
TRUTH = Path(str(BOOK) + ".truth.json")
DRAFTS = ROOT / "tests" / "fixtures" / "drafts"


def ensure_book() -> Path:
    if not BOOK.exists() or not TRUTH.exists():
        import make_book
        make_book.build(BOOK)
    return BOOK


def truth() -> dict:
    ensure_book()
    return json.loads(TRUTH.read_text(encoding="utf-8"))


def new_workspace(tier: str = "strict", formats: str = "mcq,problems,short-answer"):
    """A workspace that has passed intake and plan confirmation (next task: first write-section)."""
    ensure_book()
    import dev_setup
    tmp = Path(tempfile.mkdtemp(prefix="examscribe-test-"))
    return dev_setup.make(tmp / "ws", tier=tier, formats=formats, book=BOOK)


def cleanup(ws) -> None:
    shutil.rmtree(ws.root.parent, ignore_errors=True)


def install_draft(ws, chapter: str, name: str) -> Path:
    src = DRAFTS / chapter / name
    dst = ws.draft_dir(chapter) / name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return dst


def oracle_fill(ws, lazy: bool = False) -> str:
    """Fill the current worksheet like a perfect checker (or a lazy one that marks everything SUPPORTED)."""
    from examscribe_lib import verify as V
    from examscribe_lib.esm import parse
    from examscribe_lib.pipeline import compute_next
    task = compute_next(ws)
    assert task.kind in ("verify-claims", "verify-formulas", "solve", "reconcile"), task.id
    keys = json.loads((ws.verify_dir(task.chapter) / ".keys.json").read_text(encoding="utf-8"))
    k = keys[task.worksheet]
    h = lambda bid: hashlib.sha256((k["salt"] + bid).encode()).hexdigest()[:16]
    lines = task.edit.read_text(encoding="utf-8").split("\n")
    doc = parse("\n".join(lines))
    qs = {q.hash: q for q in V.extract_questions(ws, task.chapter)}
    for b in doc.blocks:
        canary = (h(b.id) in k.get("canary", {})) and not lazy
        ctx = re.sub(r"^\[p\.[^\]]*\]\s*", "", b.value("context"))
        span = " ".join(ctx.split()[:7])
        if b.kind == "claim":
            fill = {"verdict": "NOT_SUPPORTED" if canary else "SUPPORTED", "span": "NONE" if canary else span,
                    "problem": "The context does not say this." if canary else ""}
        elif b.kind == "formula-check":
            fill = {"verdict": "MISMATCH" if canary else "MATCH",
                    "problem": "The formula differs from the book." if canary else ""}
        elif b.kind == "solve":
            q = qs[k["real"][h(b.id)]]
            blk = next(x for x in parse((ws.root / q.file).read_text(encoding="utf-8")).blocks if x.id == q.block_id)
            fill = {"answer": q.answer, "evidence": span, "only-one-correct": "yes",
                    "calc": [c.value for c in blk.all("calc")]}
        else:
            fill = {"judgement": "KEY_WRONG" if canary else "SAME", "reason": "Decided from the context line."}
        for i in range(b.line, b.end_line or b.line):
            key = lines[i - 1].split(":", 1)[0].strip()
            if key == "calc":
                lines[i - 1] = "\n".join(f"calc: {c}" for c in fill.get("calc", []))
            elif key in fill:
                lines[i - 1] = f"{key}: {fill[key]}" if fill[key] else ""
    task.edit.write_text("\n".join(lines), encoding="utf-8")
    return task.id


SIMPLE_TEXT = {  # (question, why a wrong option is wrong, why the right one is right) per notes language
    "de": ("Welche Aussage stimmt laut Buch?", "Das steht so nicht im Buch.", "Das Buch sagt genau das."),
    "zh": ("根据课本，哪一项是正确的？", "课本中没有这样说。", "课本就是这样说的。"),
    "fr": ("Quelle affirmation est exacte d'après le livre ?", "Le livre ne dit pas cela.", "Le livre le dit ainsi."),
    "ko": ("교과서에 따르면 옳은 것은?", "교과서에는 그렇게 나와 있지 않다.", "교과서에 그렇게 나와 있다."),
    "en": ("Which statement matches the book?", "The book does not say this.", "The book says exactly this."),
}


def oracle_write_section(path: Path, lang: str, term_of: dict[str, str]) -> None:
    """Fill a section skeleton from the book's own sentences (for pipeline tests in any language): definitions
    from the hints, shortened definitions as plain claims, the caption for the figure, and questions whose wrong
    options are mutated definitions. `term_of` maps a definition sentence to its term."""
    from examscribe_lib.mutate import mutate_claim
    q, reason_wrong, reason_right = SIMPLE_TEXT.get(lang, SIMPLE_TEXT["en"])
    cjk = lang in ("zh", "ja")

    def shorten(s: str) -> str:
        if cjk:
            return s[: max(6, int(len(s) * 0.7))].rstrip("，、,") + "。"
        words = s.rstrip(".").split()
        return " ".join(words[: max(4, int(len(words) * 0.7))]).rstrip(",") + "."
    text = "\n".join(l for l in path.read_text(encoding="utf-8").split("\n") if "<<OPTIONAL" not in l)
    concepts = re.findall(r"::: concept (\S+)\n[^\n]*\n<!-- hint: first bold use on p\.(\S+): \"(.*)\" -->", text)
    for cid, page, sent in concepts:
        cite = f'[p.{page}: "{sent}"]'
        text = re.sub(rf"(::: concept {re.escape(cid)}\n(?:.*\n)*?)definition: <<FILL[^\n]*>>",
                      lambda m: m.group(1) + f"definition: {cite}", text, count=1)
        text = re.sub(rf"(::: concept {re.escape(cid)}\n(?:.*\n)*?)plain: <<FILL[^\n]*>>",
                      lambda m: m.group(1) + f"plain: {shorten(sent)} {cite}", text, count=1)
    fm = re.search(r"<!-- caption \(p\.(\S+)\): (.*?)\s*Image:", text)
    if fm:
        body = re.sub(r"^\S+\s*\d+\.\d+\s*", "", fm.group(2).rstrip(". "))
        text = re.sub(r"what: <<FILL[^\n]*>>", lambda _m: f'what: {body} [p.{fm.group(1)}: "{body}"]', text)
    cid1, p1, s1 = concepts[0]
    wrong: list[str] = []
    for sentence in [s for _, _, s in concepts]:            # false variants of the definitions, then other ones
        for seed in range(30):
            mut = mutate_claim(sentence, sentence, [], seed, lang=lang)
            if mut and mut[0] not in wrong and mut[0] != s1:
                wrong.append(mut[0])
    wrong += [s for _, _, s in concepts[1:]]
    assert len(wrong) >= 3, wrong
    term1 = term_of[s1]
    parts = text.split("::: question ")
    for i in range(1, len(parts)):
        b = parts[i]
        typ = re.search(r"type: (\w+)", b).group(1)
        why = f'why: {reason_right} [p.{p1}: "{s1}"]'
        if typ == "mcq":
            b = re.sub(r"ask: <<FILL[^\n]*>>", f"ask: {q}", b)
            for letter, opt in zip("ABCD", [s1] + wrong[:3]):
                b = re.sub(rf"option {letter}: <<FILL[^\n]*>>", lambda _m, o=opt, l=letter: f"option {l}: {o}", b)
            b = re.sub(r"answer: <<FILL[^\n]*>>", "answer: A", b)
            b = re.sub(r"why-not A: <<FILL[^\n]*>>\n", "", b)
            for letter in "BCD":
                b = re.sub(rf"why-not {letter}: <<FILL[^\n]*>>", f"why-not {letter}: {reason_wrong}", b)
        elif typ == "cloze":
            b = re.sub(r"ask: <<FILL[^\n]*>>", lambda _m: "ask: " + s1.replace(term1, "____", 1), b)
            b = re.sub(r"answer: <<FILL[^\n]*>>", lambda _m: f"answer: {term1}", b)
        elif typ == "tf":
            b = re.sub(r"ask: <<FILL[^\n]*>>", lambda _m: f"ask: {s1}", b)
            b = re.sub(r"answer: <<FILL[^\n]*>>", "answer: true", b)
        b = re.sub(r"why: <<FILL[^\n]*>>", lambda _m: why, b)
        parts[i] = re.sub(r"covers: <<FILL[^\n]*>>", f"covers: {cid1}", b)
    path.write_text("::: question ".join(parts), encoding="utf-8")


CHECK_OUTPUTS: list[str] = []


def drive(ws, max_steps: int = 200, lazy_first: bool = False) -> list[str]:
    """Run the whole pipeline with fixture drafts and the oracle. Returns the list of task ids seen;
    every `check` output is collected in CHECK_OUTPUTS."""
    from examscribe_lib.pipeline import check, compute_next
    seen = []
    CHECK_OUTPUTS.clear()
    lazy_done = not lazy_first
    for _ in range(max_steps):
        task = compute_next(ws)
        seen.append(task.id)
        if task.kind == "done":
            return seen
        if task.kind in ("write-section", "write-chapter"):
            install_draft(ws, task.chapter, task.edit.name)
        elif task.kind in ("verify-claims", "verify-formulas", "solve", "reconcile"):
            oracle_fill(ws, lazy=not lazy_done and task.kind == "verify-claims")
            if not lazy_done and task.kind == "verify-claims":
                res = check(ws)
                assert not res.ok and "planted false claim" in res.text, res.text[:300]
                lazy_done = True
                continue
        elif task.kind == "notify":
            pass
        else:
            raise AssertionError(f"unexpected task {task.id}")
        res = check(ws)
        CHECK_OUTPUTS.append(res.text)
        assert res.ok or task.kind == "notify", res.text[:2000]
    raise AssertionError("pipeline did not finish")
