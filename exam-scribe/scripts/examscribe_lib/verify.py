"""Independent verification: claim checks with canaries, formula checks, blind solving, reconciliation.

Nothing the writer produces is trusted until a separate pass confirms it:
  1. claims    every cited claim is judged against the book text around its quote.
               Planted false claims (canaries) measure whether the checker reads carefully;
               a batch in which any canary is marked SUPPORTED is thrown away and redone.
  2. formulas  every LaTeX transcription is compared with the printed formula.
  3. solve     every question is answered without seeing the key; disagreements and
               short answers go to
  4. reconcile the checker sees key vs. its own answer and judges (with a wrong-key canary).
Anything still disputed after the fix rounds is shown with a warning marker, never hidden.
"""
from __future__ import annotations

import random
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from . import calc as calcmod
from .citations import QuoteIndex
from .common import (ESError, Workspace, key_of, read_json, read_text, rel, sha, word_count, write_json, write_text)
from .esm import Block, citations, covers, is_unsure, parse, strip_citations
from .lint import _split_cells, block_key
from .mutate import mismatched_context, mutate_claim, mutate_latex
from .schema import LETTERS, SCHEMAS

CLAIM_FIELDS_SKIP = {"source"}


@dataclass
class Claim:
    id: str
    chapter: str
    file: str
    line: int
    block_id: str
    block_kind: str
    field: str
    kind: str
    text: str
    pages: list[str]
    quotes: list[str]
    context: str
    loc: str
    exactness: str = "exact"


@dataclass
class QItem:
    hash: str
    chapter: str
    file: str
    line: int
    block_id: str
    type: str
    ask: str
    options: dict[str, str]
    answer: str
    accept: list[str]
    tolerance: str
    context: str
    why: str


def draft_files(ws: Workspace, ch: str) -> list[Path]:
    d = ws.draft_dir(ch)
    if not d.exists():
        return []
    files = sorted(p for p in d.glob("*.md") if p.name != "chapter.md")
    if (d / "chapter.md").exists():
        files.append(d / "chapter.md")
    return files


def _names(ws: Workspace) -> dict[str, str]:
    out = {}
    for iid, it in ws.all_inventory_items().items():
        out[iid] = it.get("display") or it.get("text") or it.get("caption") or iid
    return out


def extract_claims(ws: Workspace, ch: str, qindex: QuoteIndex | None = None) -> list[Claim]:
    qi = qindex or QuoteIndex(ws)
    names = _names(ws)
    claims: list[Claim] = []
    for path in draft_files(ws, ch):
        doc = parse(read_text(path), path)
        for blk in doc.blocks:
            schema = SCHEMAS.get(blk.kind)
            if schema is None or schema.worksheet or blk.get("skip"):
                continue
            occ: dict[str, int] = {}
            for f in blk.fields:
                fs = next((x for x in schema.fields if x.key == f.key), None)
                if fs is None or not fs.claim or f.key in CLAIM_FIELDS_SKIP:
                    continue
                n = occ.get(f.key, 0)
                occ[f.key] = n + 1
                v = f.value.strip()
                if not v or is_unsure(v):
                    continue
                pieces: list[tuple[str, list]] = []
                if fs.cite == "cells":
                    cells = _split_cells(v)
                    items = [x.strip() for x in _split_cells(blk.value("items"))] if blk.kind == "compare" else []
                    for ci, cell in enumerate(cells[1:]):
                        cites = citations(cell)
                        if not cites:
                            continue
                        who = names.get(items[ci], items[ci]) if ci < len(items) else ""
                        label = f"{who} — {cells[0]}" if who else cells[0]
                        if blk.kind == "strategy":
                            label = f"When you see: {cells[0]}"
                        pieces.append((f"{label}: {strip_citations(cell)}", cites))
                elif fs.key == "definition":
                    cites = citations(v)
                    term = blk.value("term-original") or blk.value("term")
                    if cites:
                        pieces.append((f'The book defines "{term}" as: "{cites[0].quote}"', cites))
                elif fs.key == "misconception":
                    m = re.match(r"^\s*wrong\s*:\s*(?P<w>.+?)\s*\|\s*right\s*:\s*(?P<r>.+)$", v, re.I | re.S)
                    if m:
                        pieces.append((strip_citations(m.group("r")), citations(m.group("r"))))
                elif blk.kind == "map" and f.key == "link":
                    m = re.match(r"^\s*(?P<a>\S+)\s*->\s*(?P<b>\S+)\s*\|\s*(?P<rel>.+)$", v)
                    if m:
                        pieces.append((f"{names.get(m.group('a'), m.group('a'))} → "
                                       f"{names.get(m.group('b'), m.group('b'))}: {strip_citations(m.group('rel'))}",
                                       citations(m.group("rel"))))
                elif blk.kind == "timeline":
                    parts = [p.strip() for p in strip_citations(v).split("|", 1)]
                    pieces.append((": ".join(parts), citations(v)))
                elif blk.kind == "chain":
                    pieces.append((strip_citations(v).replace("->", "leads to"), citations(v)))
                else:
                    text = strip_citations(v)
                    if blk.kind == "question" and f.key == "why":
                        text = f"{text}"
                    if word_count(text) < 2:
                        continue
                    pieces.append((text, citations(v)))
                for pi, (text, cites) in enumerate(pieces):
                    if not cites or not text.strip():
                        continue
                    ctx_parts, pages, quotes, exactness = [], [], [], "exact"
                    for c in cites[:3]:
                        res = qi.check(c.page, c.quote)
                        if not res.ok:
                            exactness = "failed"
                            continue
                        if res.status == "approx":
                            exactness = "approx"
                        pages.append(c.page)
                        quotes.append(c.quote)
                        _add_context(ctx_parts, f"[p.{c.page}] {res.context}")
                    if not ctx_parts:
                        continue
                    loc = f"{rel(path, ws.root)}#{block_key(blk)}#{f.key}#{n}#{pi}"
                    cid = "C" + sha(f"{loc}|{text}|{'|'.join(quotes)}", 10)
                    claims.append(Claim(cid, ch, rel(path, ws.root), f.line, blk.id, blk.kind, f.key, fs.claim, text,
                                        pages, quotes, " … ".join(ctx_parts), loc, exactness))
    return claims


def _merge_windows(a: str, b: str) -> str | None:
    """The union of two windows of one text when the end of one is the start of the other."""
    for x, y in ((a, b), (b, a)):
        for n in range(min(len(x), len(y)), 19, -1):
            if x.endswith(y[:n]):
                return x + y[n:]
    return None


def _add_context(parts: list[str], ctx: str) -> None:
    """Add a context unless it repeats one already there: two quotes from one paragraph give overlapping windows
    of the same text, and the checker should read it once (as their union)."""
    head = re.match(r"^\[p\.[^\]]*\]\s*", ctx)
    body = ctx[head.end():] if head else ctx
    k = key_of(body)
    for i, prev in enumerate(parts):
        ph = re.match(r"^\[p\.[^\]]*\]\s*", prev)
        pbody = prev[ph.end():] if ph else prev
        pk = key_of(pbody)
        if k in pk:
            return
        if pk in k:
            parts[i] = ctx
            return
        if len(k) >= 40 and len(pk) >= 40 and (k[:40] in pk or pk[:40] in k):
            merged = _merge_windows(pbody, body)
            parts[i] = (prev[:ph.end()] if ph else "") + merged if merged else (ctx if len(k) > len(pk) else prev)
            return
    parts.append(ctx)


def extract_questions(ws: Workspace, ch: str, qindex: QuoteIndex | None = None) -> list[QItem]:
    qi = qindex or QuoteIndex(ws)
    out = []
    for path in draft_files(ws, ch):
        doc = parse(read_text(path), path)
        for blk in doc.of_kind("question"):
            if blk.get("skip"):
                continue
            opts = {c: blk.value(f"option {c}") for c in LETTERS if blk.get(f"option {c}")}
            why = blk.value("why")
            ctx = []
            for c in citations(why)[:2]:
                res = qi.check(c.page, c.quote)
                if res.ok:
                    _add_context(ctx, f"[p.{c.page}] {res.context}")
            payload = "|".join([blk.id, blk.value("type"), blk.value("ask"), *opts.values(), blk.value("answer"),
                                *[f.value for f in blk.all("accept")]])
            out.append(QItem("Q" + sha(payload, 10), ch, rel(path, ws.root), blk.line, blk.id,
                             blk.value("type").lower(), blk.value("ask"), opts, blk.value("answer").strip(),
                             [f.value for f in blk.all("accept")], blk.value("tolerance"), " … ".join(ctx), why))
    return out


# =============================================================================== storage

def _vpath(ws: Workspace, ch: str, name: str) -> Path:
    return ws.verify_dir(ch) / name


def load_verdicts(ws: Workspace, ch: str) -> dict:
    data = read_json(_vpath(ws, ch, "verdicts.json"), None) or {}
    for k in ("claims", "formulas", "questions", "rounds"):
        data.setdefault(k, {})
    return data


def save_verdicts(ws: Workspace, ch: str, data: dict) -> None:
    write_json(_vpath(ws, ch, "verdicts.json"), data)


def _keys(ws: Workspace, ch: str) -> dict:
    return read_json(_vpath(ws, ch, ".keys.json"), None) or {}


def _save_keys(ws: Workspace, ch: str, data: dict) -> None:
    write_json(_vpath(ws, ch, ".keys.json"), data)


def _h(salt: str, bid: str) -> str:
    return sha(salt + bid, 16)


def _one_line(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


# =============================================================================== claims worksheets

HEADER_CLAIMS = """# Claim check — {ch} batch {n}
<!-- ROLE: independent checker. Judge each claim ONLY by its context line (text copied from the book). -->
<!-- verdict: SUPPORTED = the context clearly says this (numbers, signs and conditions included)
              PARTIAL = partly right, a condition/qualifier is missing or changed, or the claim adds something
                        the context does not say (a reason, a contrast, a wider scope)
              NOT_SUPPORTED = the context does not say this
              CONTRADICTED = the context says the opposite -->
<!-- span: for SUPPORTED, copy the exact supporting words from the context (at least 3 words). Otherwise NONE. -->
<!-- problem: if not SUPPORTED, one sentence saying what is wrong. -->
<!-- Some claims are deliberately false to test attention. Check every word. Do not edit claim: or context: lines. -->
"""


def pending_claims(ws: Workspace, ch: str, claims: list[Claim] | None = None) -> list[Claim]:
    claims = claims if claims is not None else extract_claims(ws, ch)
    v = load_verdicts(ws, ch)["claims"]
    return [c for c in claims if c.id not in v]


def is_verbatim(c: Claim) -> bool:
    """True when the claim simply repeats (almost all of) one of its verified quotes word for word.

    Such a claim says exactly what the book says, so no judgement is needed. Requiring the claim to cover at
    least 90% of the quote stops truncations like "...is created" cut out of "it is not true that energy is created".
    """
    if c.kind == "definition" or c.exactness != "exact":
        return False
    ck = key_of(c.text)
    if len(ck) < 20:
        return False
    return any(ck in (qk := key_of(q)) and len(ck) >= 0.9 * len(qk) for q in c.quotes)


def make_claim_batches(ws: Workspace, ch: str, tier: dict, claims: list[Claim] | None = None) -> list[str]:
    claims = claims if claims is not None else extract_claims(ws, ch)
    pending = pending_claims(ws, ch, claims)
    auto = [c for c in pending if is_verbatim(c)]
    if auto:
        data = load_verdicts(ws, ch)
        for c in auto:
            data["claims"][c.id] = {"verdict": "SUPPORTED", "span": c.quotes[0], "problem": "", "batch": "verbatim",
                                    "auto": True}
        save_verdicts(ws, ch, data)
        pending = [c for c in pending if c not in auto]
    if not pending:
        return []
    keys = _keys(ws, ch)
    existing = sorted(int(m.group(1)) for p in ws.verify_dir(ch).glob("claims-*.md")
                      if (m := re.match(r"claims-(\d+)\.md", p.name))) if ws.verify_dir(ch).exists() else []
    n0 = (existing[-1] if existing else 0) + 1
    files = []
    size = tier["verify_batch"]
    terms = [it["text"] for it in ws.inventory(ch)["items"] if it["kind"] == "term"]
    for bi in range(0, len(pending), size):
        batch = pending[bi: bi + size]
        name = f"claims-{n0 + bi // size:02d}"
        _write_claim_batch(ws, ch, name, batch, claims, terms, tier["canaries_per_batch"], keys, attempt=1)
        files.append(name)
    _save_keys(ws, ch, keys)
    return files


def _other_passages(ws: Workspace, ch: str, rng: random.Random, n: int = 12) -> list[str]:
    """Paragraphs from other chapters (for mismatched-context canaries), formatted like claim contexts."""
    try:
        cur = ws.chapter(ch)
    except ESError:
        return []
    lo, hi = cur["start"]["page"], cur["end"]["page"]
    paras = [(p["label"], para["text"]) for p in ws.pages if not (lo <= p["index"] <= hi)
             for para in p["paras"] if not para["heading"] and len(para["text"]) > 60]
    rng.shuffle(paras)
    return [f"[p.{label}] {text[:600]}" for label, text in paras[:n]]


def _write_claim_batch(ws: Workspace, ch: str, name: str, batch: list[Claim], all_claims: list[Claim],
                       terms: list[str], n_canaries: int, keys: dict, attempt: int) -> None:
    salt = secrets.token_hex(8)
    rng = random.Random(salt)
    items: list[tuple[str, str, str]] = []           # (bid, claim, context)
    real, canary = {}, {}
    for c in batch:
        bid = "V-" + secrets.token_hex(4)
        items.append((bid, c.text, c.context))
        real[_h(salt, bid)] = c.id
    # canaries are made from claims outside this batch first (so a planted claim does not sit next to its original),
    # then, if there are too few (a small chapter), from the batch itself
    outside = [c for c in all_claims if c not in batch]
    inside = list(batch)
    rng.shuffle(outside)
    rng.shuffle(inside)
    lang = (ws.config.get("output") or {}).get("language") or (ws.config.get("book") or {}).get("language") or "en"
    made, used = 0, set()
    for d in outside + inside:
        if made >= n_canaries:
            break
        mut = mutate_claim(d.text, d.context, terms, seed=rng.randint(0, 10 ** 6), lang=lang)
        if not mut or mut[0] in used:
            continue
        used.add(mut[0])
        bid = "V-" + secrets.token_hex(4)
        items.append((bid, mut[0], d.context))
        canary[_h(salt, bid)] = mut[1]
        made += 1
    # still too few (claims with nothing safe to change): a real claim next to an unrelated passage from another
    # part of the book is a planted false item in any language
    if made < n_canaries:
        pool = list(dict.fromkeys(c.context for c in all_claims if c.context)) + _other_passages(ws, ch, rng)
        for d in outside + inside:
            if made >= n_canaries:
                break
            ctx = mismatched_context(d.text, [c for c in pool if c != d.context], rng)
            if not ctx:
                continue
            bid = "V-" + secrets.token_hex(4)
            items.append((bid, d.text, ctx))
            canary[_h(salt, bid)] = "mismatch"
            made += 1
    rng.shuffle(items)
    blocks, originals = [], {}
    for bid, claim, ctx in items:
        claim1, ctx1 = _one_line(claim), _one_line(ctx)
        originals[bid] = {"claim": claim1, "context": ctx1}
        blocks.append("\n".join([f"::: claim {bid}", f"claim: {claim1}", f"context: {ctx1}",
                                 "verdict: <<FILL: SUPPORTED | PARTIAL | NOT_SUPPORTED | CONTRADICTED>>",
                                 "span: <<FILL: exact words from the context, or NONE>>",
                                 "problem: <<OPTIONAL: what is wrong (only if not SUPPORTED)>>", ":::"]))
    n = name.split("-")[-1]
    write_text(_vpath(ws, ch, f"{name}.md"), HEADER_CLAIMS.format(ch=ch, n=n) + "\n" + "\n\n".join(blocks) + "\n")
    write_json(_vpath(ws, ch, f"{name}.json"), {"kind": "claim", "originals": originals})
    keys[name] = {"salt": salt, "real": real, "canary": canary, "attempt": attempt,
                  "claim_ids": [c.id for c in batch]}


def score_claim_batch(ws: Workspace, ch: str, name: str, tier: dict) -> dict:
    """Returns {'status': passed|rejected|escalated, 'message': ..., 'problems': [claim ids]}."""
    keys = _keys(ws, ch)
    k = keys.get(name)
    if not k:
        raise ESError(f"Unknown worksheet {name}.")
    doc = parse(read_text(_vpath(ws, ch, f"{name}.md")))
    caught, missed = 0, []
    verdicts = {}
    for blk in doc.of_kind("claim"):
        h = _h(k["salt"], blk.id)
        verdict = blk.value("verdict").strip().upper()
        if h in k["canary"]:
            if verdict == "SUPPORTED":
                missed.append(blk.id)
            else:
                caught += 1
        elif h in k["real"]:
            verdicts[k["real"][h]] = {"verdict": verdict, "span": blk.value("span"), "problem": blk.value("problem"),
                                      "batch": name}
    total_canaries = len(k["canary"])
    data = load_verdicts(ws, ch)
    stats = data.setdefault("canary_stats", {"planted": 0, "caught": 0, "rejected_batches": 0})
    stats["planted"] += total_canaries
    stats["caught"] += caught
    if missed:
        stats["rejected_batches"] += 1
        save_verdicts(ws, ch, data)
        claims = {c.id: c for c in extract_claims(ws, ch)}
        batch = [claims[cid] for cid in k["claim_ids"] if cid in claims]
        if k["attempt"] >= tier["max_attempts"]:
            for c in batch:
                data["claims"][c.id] = {"verdict": "UNVERIFIED", "span": "", "batch": name,
                                        "problem": "the checker failed the attention test repeatedly"}
            save_verdicts(ws, ch, data)
            del keys[name]
            _save_keys(ws, ch, keys)
            return {"status": "escalated", "message": f"The checker marked planted false claims as SUPPORTED in "
                    f"{k['attempt']} attempts. These {len(batch)} claims stay marked as unverified for a human to "
                    "check.", "problems": []}
        terms = [it["text"] for it in ws.inventory(ch)["items"] if it["kind"] == "term"]
        _write_claim_batch(ws, ch, name, batch, list(claims.values()), terms, tier["canaries_per_batch"], keys,
                           k["attempt"] + 1)
        _save_keys(ws, ch, keys)
        return {"status": "rejected",
                "message": f"{len(missed)} planted false claim(s) were marked SUPPORTED, so this batch cannot be "
                           "trusted. The worksheet has been regenerated with new items. Check every claim word by "
                           "word against its context: numbers, signs, 'not', and conditions.",
                "problems": []}
    locs = {c.id: c.loc for c in extract_claims(ws, ch)}
    for cid, v in verdicts.items():
        data["claims"][cid] = v
        if v["verdict"] != "SUPPORTED" and cid in locs:
            # one fix round per rejection at the same place; after two, the claim stays flagged for a human
            data["rounds"][locs[cid]] = data["rounds"].get(locs[cid], 0) + 1
    save_verdicts(ws, ch, data)
    del keys[name]
    _save_keys(ws, ch, keys)
    problems = [cid for cid, v in verdicts.items() if v["verdict"] != "SUPPORTED"]
    return {"status": "passed", "message": f"{len(verdicts)} claims judged; {caught}/{total_canaries} planted false "
            f"claims caught; {len(problems)} claim(s) need fixing.", "problems": problems}


# =============================================================================== formula checks

def formula_items(ws: Workspace, ch: str) -> list[dict]:
    inv_items = {it["id"]: it for it in ws.inventory(ch)["items"]}
    out = []
    for path in draft_files(ws, ch):
        doc = parse(read_text(path), path)
        for blk in doc.of_kind("formula"):
            if blk.get("skip") or not blk.value("latex").strip():
                continue
            it = inv_items.get(blk.id, {})
            latex = blk.value("latex").strip()
            out.append({"id": "F" + sha(blk.id + "|" + latex, 10), "block": blk.id, "latex": latex,
                        "book": it.get("text", ""), "image": it.get("image") or "none", "file": rel(path, ws.root),
                        "line": blk.get("latex").line})
    return out


def make_formula_batch(ws: Workspace, ch: str) -> str | None:
    data = load_verdicts(ws, ch)
    items = formula_items(ws, ch)
    pending = [f for f in items if f["id"] not in data["formulas"]]
    if not pending:
        return None
    keys = _keys(ws, ch)
    salt = secrets.token_hex(8)
    rng = random.Random(salt)
    rows, real, canary = [], {}, {}
    for f in pending:
        bid = "VF-" + secrets.token_hex(4)
        rows.append((bid, f["latex"], f["book"], f["image"]))
        real[_h(salt, bid)] = f["id"]
    donor = rng.choice(items)
    mut = mutate_latex(donor["latex"], seed=rng.randint(0, 999))
    if mut:
        bid = "VF-" + secrets.token_hex(4)
        rows.append((bid, mut[0], donor["book"], donor["image"]))
        canary[_h(salt, bid)] = mut[1]
    rng.shuffle(rows)
    originals, blocks = {}, []
    img_root = ws.root
    for bid, latex, book, image in rows:
        img = str((img_root / image).resolve()) if image != "none" else "none"
        originals[bid] = {"latex": latex, "book-line": _one_line(book), "image": img}
        blocks.append("\n".join([f"::: formula-check {bid}", f"latex: {latex}", f"book-line: {_one_line(book)}",
                                 f"image: {img}", "verdict: <<FILL: MATCH | MISMATCH | CANNOT_TELL>>",
                                 "problem: <<OPTIONAL: what differs (only if MISMATCH)>>", ":::"]))
    name = "formulas"
    header = ("# Formula check — " + ch + "\n<!-- Compare each LaTeX formula with the book's formula. book-line is "
              "extracted text (subscripts appear as _x, superscripts as ^x, and symbols can be garbled). If you can see "
              "images, open image: and compare with it. -->\n<!-- MATCH = same formula (same symbols, signs, powers, "
              "fractions). MISMATCH = anything differs. CANNOT_TELL = the book line is too garbled and you cannot see "
              "the image. Some items are deliberately wrong. -->\n")
    write_text(_vpath(ws, ch, f"{name}.md"), header + "\n" + "\n\n".join(blocks) + "\n")
    write_json(_vpath(ws, ch, f"{name}.json"), {"kind": "formula-check", "originals": originals})
    prev = keys.get(name, {})
    keys[name] = {"salt": salt, "real": real, "canary": canary, "attempt": prev.get("attempt", 0) + 1}
    _save_keys(ws, ch, keys)
    return name


def score_formula_batch(ws: Workspace, ch: str, tier: dict) -> dict:
    keys = _keys(ws, ch)
    k = keys.get("formulas")
    doc = parse(read_text(_vpath(ws, ch, "formulas.md")))
    data = load_verdicts(ws, ch)
    missed, verdicts = 0, {}
    for blk in doc.of_kind("formula-check"):
        h = _h(k["salt"], blk.id)
        v = blk.value("verdict").strip().upper()
        if h in k["canary"] and v == "MATCH":
            missed += 1
        elif h in k["real"]:
            verdicts[k["real"][h]] = {"verdict": v, "problem": blk.value("problem")}
    if missed and k["attempt"] < tier["max_attempts"]:
        del keys["formulas"]
        keys["formulas"] = {"attempt": k["attempt"]}
        _save_keys(ws, ch, keys)
        make_formula_batch(ws, ch)
        return {"status": "rejected", "message": "A deliberately wrong formula was marked MATCH. The worksheet was "
                "regenerated; compare every symbol, sign, power and fraction.", "problems": []}
    if missed:
        for fid in k["real"].values():
            verdicts[fid] = {"verdict": "CANNOT_TELL", "problem": "checker failed the attention test"}
    blocks = {f["id"]: f["block"] for f in formula_items(ws, ch)}
    for fid, v in verdicts.items():
        if v["verdict"] == "MISMATCH" and fid in blocks:
            data["rounds"]["F:" + blocks[fid]] = data["rounds"].get("F:" + blocks[fid], 0) + 1
    data["formulas"].update(verdicts)
    save_verdicts(ws, ch, data)
    keys.pop("formulas", None)
    _save_keys(ws, ch, keys)
    problems = [fid for fid, v in verdicts.items() if v["verdict"] == "MISMATCH"]
    return {"status": "passed", "message": f"{len(verdicts)} formulas checked; {len(problems)} mismatch(es).",
            "problems": problems}


# =============================================================================== blind solving

HEADER_SOLVE = """# Blind solve — {ch} batch {n}
<!-- ROLE: independent solver. Answer each question yourself using ONLY its context line. You do not see the key. -->
<!-- mcq: answer with one letter; only-one-correct: yes if exactly one option is right per the context, else no.
     tf: true or false.  numeric: number with unit like 15.7[kJ], and show calc: lines.
     cloze: the missing word(s).  short: 1-3 sentences. -->
<!-- evidence: copy the exact words from the context that decide your answer. Do not edit read-only lines. -->
"""


def pending_questions(ws: Workspace, ch: str, qs: list[QItem] | None = None) -> list[QItem]:
    qs = qs if qs is not None else extract_questions(ws, ch)
    done = load_verdicts(ws, ch)["questions"]
    return [q for q in qs if q.hash not in done or done[q.hash].get("status") == "solve-pending"]


def make_solve_batches(ws: Workspace, ch: str, tier: dict) -> list[str]:
    qs = extract_questions(ws, ch)
    data = load_verdicts(ws, ch)
    pending = [q for q in qs if q.hash not in data["questions"]]
    if not pending:
        return []
    keys = _keys(ws, ch)
    existing = sorted(int(m.group(1)) for p in ws.verify_dir(ch).glob("solve-*.md")
                      if (m := re.match(r"solve-(\d+)\.md", p.name))) if ws.verify_dir(ch).exists() else []
    n0 = (existing[-1] if existing else 0) + 1
    names = []
    size = tier["solve_batch"]
    for bi in range(0, len(pending), size):
        batch = pending[bi: bi + size]
        name = f"solve-{n0 + bi // size:02d}"
        salt = secrets.token_hex(8)
        real, originals, blocks = {}, {}, []
        rng = random.Random(salt)
        rng.shuffle(batch)
        for q in batch:
            bid = "S-" + secrets.token_hex(4)
            real[_h(salt, bid)] = q.hash
            orig = {"type": q.type, "question": _one_line(q.ask), "context": _one_line(q.context) or "(no context)"}
            lines = [f"::: solve {bid}", f"type: {q.type}", f"question: {orig['question']}"]
            for c in LETTERS:
                if c in q.options:
                    orig[f"option {c}"] = _one_line(q.options[c])
                    lines.append(f"option {c.upper()}: {orig[f'option {c}']}")
            lines.append(f"context: {orig['context']}")
            hint = {"mcq": "A, B, C or D", "tf": "true or false", "numeric": "number with unit, e.g. 15.7[kJ]",
                    "cloze": "the missing word(s)", "short": "1-3 sentences"}.get(q.type, "your answer")
            lines.append(f"answer: <<FILL: {hint}>>")
            if q.type == "mcq":
                lines.append("only-one-correct: <<FILL: yes | no>>")
            lines.append("evidence: <<FILL: exact words from the context that decide the answer>>")
            if q.type == "numeric":
                lines.append("calc: <<FILL: the calculation, e.g. q = 250[g] * 4.184[J/(g*degC)] * 15.0[degC] => 15690[J]>>")
            lines.append(":::")
            originals[bid] = orig
            blocks.append("\n".join(lines))
        write_text(_vpath(ws, ch, f"{name}.md"),
                   HEADER_SOLVE.format(ch=ch, n=name.split("-")[-1]) + "\n" + "\n\n".join(blocks) + "\n")
        write_json(_vpath(ws, ch, f"{name}.json"), {"kind": "solve", "originals": originals})
        keys[name] = {"salt": salt, "real": real}
        names.append(name)
    _save_keys(ws, ch, keys)
    return names


def _norm_answer(s: str) -> str:
    s = re.sub(r"\b(the|a|an)\b", " ", s.casefold())
    return key_of(s)


def compare_answer(q: QItem, mine: str) -> bool | None:
    """True/False when a script can decide; None when a judgement is needed (short answers)."""
    mine = mine.strip()
    if q.type == "mcq":
        return mine.upper()[:1] == q.answer.strip().upper()[:1]
    if q.type == "tf":
        return mine.lower().startswith(q.answer.strip().lower()[:1]) and mine.lower()[:1] in ("t", "f")
    if q.type == "numeric":
        try:
            a = calcmod.parse_quantity(q.answer)
            b = calcmod.parse_quantity(mine)
        except calcmod.CalcError:
            return False
        if a.d != b.d:
            return False
        tol = abs(a.v) * 0.01
        if q.tolerance.strip().endswith("%"):
            try:
                tol = max(tol, abs(a.v) * float(q.tolerance.strip()[:-1]) / 100)
            except ValueError:
                pass
        return abs(a.v - b.v) <= tol + 1e-12
    if q.type == "cloze":
        wanted = [q.answer] + q.accept
        return any(_norm_answer(w) == _norm_answer(mine) for w in wanted if w.strip())
    return None


def score_solve_batch(ws: Workspace, ch: str, name: str) -> dict:
    keys = _keys(ws, ch)
    k = keys[name]
    doc = parse(read_text(_vpath(ws, ch, f"{name}.md")))
    qs = {q.hash: q for q in extract_questions(ws, ch)}
    data = load_verdicts(ws, ch)
    agreed, to_reconcile = 0, 0
    for blk in doc.of_kind("solve"):
        qh = k["real"].get(_h(k["salt"], blk.id))
        if not qh or qh not in qs:
            continue
        q = qs[qh]
        mine = blk.value("answer")
        same = compare_answer(q, mine)
        ambiguous = q.type == "mcq" and blk.value("only-one-correct").strip().lower() == "no"
        entry = {"mine": mine.strip(), "evidence": blk.value("evidence"), "batch": name}
        if same is True and not ambiguous:
            entry["status"] = "agreed"
            agreed += 1
        else:
            entry["status"] = "reconcile"
            entry["reason"] = "ambiguous options" if ambiguous else ("short answer" if same is None else "answers differ")
            to_reconcile += 1
        data["questions"][qh] = entry
    save_verdicts(ws, ch, data)
    del keys[name]
    _save_keys(ws, ch, keys)
    return {"status": "passed", "message": f"{agreed} answer keys confirmed; {to_reconcile} need a closer look.",
            "problems": []}


HEADER_RECONCILE = """# Reconcile answers — {ch}
<!-- ROLE: judge. For each question, compare the answer key with the independent answer, using ONLY the context. -->
<!-- judgement: SAME = both answers say the same thing
                KEY_WRONG = the key is wrong, the independent answer is right
                MINE_WRONG = the independent answer is wrong, the key is right
                AMBIGUOUS = the question allows more than one answer or the context does not decide it -->
<!-- reason: one sentence quoting the context. Some items are deliberately wrong keys. -->
"""


def make_reconcile_batch(ws: Workspace, ch: str, tier: dict) -> str | None:
    data = load_verdicts(ws, ch)
    qs = {q.hash: q for q in extract_questions(ws, ch)}
    pending = [(h, e) for h, e in data["questions"].items() if e.get("status") == "reconcile" and h in qs]
    if not pending:
        return None
    keys = _keys(ws, ch)
    salt = secrets.token_hex(8)
    rng = random.Random(salt)
    rows, real, canary = [], {}, {}

    def key_text(q: QItem, ans: str) -> str:
        if q.type == "mcq" and ans.strip().upper()[:1] in "ABCD" and ans.strip():
            letter = ans.strip().upper()[:1]
            return f"{letter}) {q.options.get(letter.lower(), '')}"
        return ans
    for h, e in pending:
        q = qs[h]
        bid = "R-" + secrets.token_hex(4)
        rows.append((bid, q, key_text(q, q.answer), key_text(q, e.get("mine", ""))))
        real[_h(salt, bid)] = h
    agreed = [(h, e) for h, e in data["questions"].items()
              if e.get("status") == "agreed" and h in qs and qs[h].type in ("mcq", "tf")]
    for h, e in rng.sample(agreed, min(tier["reconcile_canaries"], len(agreed))):
        q = qs[h]
        if q.type == "mcq":
            wrong = rng.choice([c.upper() for c in q.options if c.upper() != q.answer.strip().upper()[:1]] or ["A"])
        else:
            wrong = "false" if q.answer.strip().lower().startswith("t") else "true"
        bid = "R-" + secrets.token_hex(4)
        rows.append((bid, q, key_text(q, wrong), key_text(q, q.answer)))
        canary[_h(salt, bid)] = "wrong-key"
    rng.shuffle(rows)
    originals, blocks = {}, []
    for bid, q, key_a, mine in rows:
        opts = " ".join(f"{c.upper()}) {v}" for c, v in q.options.items())
        question = _one_line(q.ask + (f"  Options: {opts}" if opts else ""))
        orig = {"question": question, "key-answer": _one_line(key_a) or "(empty)",
                "your-answer": _one_line(mine) or "(empty)", "context": _one_line(q.context) or "(no context)"}
        originals[bid] = orig
        blocks.append("\n".join([f"::: reconcile {bid}", f"question: {orig['question']}",
                                 f"key-answer: {orig['key-answer']}", f"your-answer: {orig['your-answer']}",
                                 f"context: {orig['context']}", "judgement: <<FILL: SAME | KEY_WRONG | MINE_WRONG | AMBIGUOUS>>",
                                 "reason: <<FILL: one sentence quoting the context>>", ":::"]))
    write_text(_vpath(ws, ch, "reconcile.md"), HEADER_RECONCILE.format(ch=ch) + "\n" + "\n\n".join(blocks) + "\n")
    write_json(_vpath(ws, ch, "reconcile.json"), {"kind": "reconcile", "originals": originals})
    prev = keys.get("reconcile", {})
    keys["reconcile"] = {"salt": salt, "real": real, "canary": canary, "attempt": prev.get("attempt", 0) + 1}
    _save_keys(ws, ch, keys)
    return "reconcile"


def score_reconcile(ws: Workspace, ch: str, tier: dict) -> dict:
    keys = _keys(ws, ch)
    k = keys["reconcile"]
    doc = parse(read_text(_vpath(ws, ch, "reconcile.md")))
    data = load_verdicts(ws, ch)
    qs = {q.hash: q for q in extract_questions(ws, ch)}
    missed, results = 0, {}
    for blk in doc.of_kind("reconcile"):
        h = _h(k["salt"], blk.id)
        j = blk.value("judgement").strip().upper()
        if h in k["canary"]:
            if j in ("SAME", "MINE_WRONG"):
                missed += 1
        elif h in k["real"]:
            results[k["real"][h]] = (j, blk.value("reason"))
    if missed and k["attempt"] < tier["max_attempts"]:
        make_reconcile_batch(ws, ch, tier)
        return {"status": "rejected", "message": "A deliberately wrong answer key was accepted. The worksheet was "
                "regenerated; decide each item from the context, not from the key.", "problems": []}
    problems = []
    blocks = {q.hash: q.block_id for q in qs.values()}
    for h, (j, reason) in results.items():
        e = data["questions"][h]
        if missed:
            e["status"] = "disputed"
            e["reason"] = "judge failed the attention test"
        elif j in ("SAME", "MINE_WRONG"):
            e["status"] = "agreed"
        else:
            e["status"] = "disputed"
            e["reason"] = f"{j}: {reason}"
            problems.append(h)
            key = "Q:" + blocks.get(h, h)
            data["rounds"][key] = data["rounds"].get(key, 0) + 1
    save_verdicts(ws, ch, data)
    keys.pop("reconcile", None)
    _save_keys(ws, ch, keys)
    return {"status": "passed", "message": f"{len(results)} answers judged; {len(problems)} answer key(s) disputed.",
            "problems": problems}


# =============================================================================== fixes

MAX_REJECTIONS = 3     # a place in the notes gets two fix attempts; after the third rejection it stays flagged


def fix_list(ws: Workspace, ch: str, tier: dict) -> dict:
    """Claims, formulas and questions the writer must revise. Rejections are counted per place in the notes
    (not per wording), so rewording the same claim cannot loop forever."""
    data = load_verdicts(ws, ch)
    claims = {c.id: c for c in extract_claims(ws, ch)}
    rounds = data["rounds"]
    out = {"claims": [], "formulas": [], "questions": []}
    for cid, v in data["claims"].items():
        c = claims.get(cid)
        if c is None or v["verdict"] in ("SUPPORTED", "UNVERIFIED"):
            continue
        if rounds.get(c.loc, 0) >= MAX_REJECTIONS:
            continue
        out["claims"].append((c, v))
    fitems = {f["id"]: f for f in formula_items(ws, ch)}
    for fid, v in data["formulas"].items():
        f = fitems.get(fid)
        if f and v["verdict"] == "MISMATCH" and rounds.get("F:" + f["block"], 0) < MAX_REJECTIONS:
            out["formulas"].append((f, v))
    qs = {q.hash: q for q in extract_questions(ws, ch)}
    for qh, e in data["questions"].items():
        q = qs.get(qh)
        if q and e.get("status") == "disputed" and rounds.get("Q:" + q.block_id, 0) < MAX_REJECTIONS:
            out["questions"].append((q, e))
    return out


def give_up(ws: Workspace, ch: str, fixes: dict) -> None:
    """Stop asking for fixes on these items; they stay flagged for a human."""
    data = load_verdicts(ws, ch)
    for c, _ in fixes["claims"]:
        data["rounds"][c.loc] = MAX_REJECTIONS
    for f, _ in fixes["formulas"]:
        data["rounds"]["F:" + f["block"]] = MAX_REJECTIONS
    for q, _ in fixes["questions"]:
        data["rounds"]["Q:" + q.block_id] = MAX_REJECTIONS
    save_verdicts(ws, ch, data)


# =============================================================================== trust

def chapter_trust(ws: Workspace, ch: str) -> dict:
    """Status per claim location, formula block and question block, for rendering and reports.

    ok        verified (quote checked by script AND confirmed by the independent checker)
    warn      disputed, unverified after repeated failures, approximate quote, or doubtful page
    pending   not verified yet
    """
    data = load_verdicts(ws, ch)
    quality = read_json(ws.quality_path, {}).get("pages", {})
    claims = extract_claims(ws, ch)
    out: dict = {"claims": {}, "formulas": {}, "questions": {}, "counts": {"ok": 0, "warn": 0, "pending": 0}}
    for c in claims:
        v = data["claims"].get(c.id)
        reasons = []
        if v is None:
            status = "pending"
        elif v["verdict"] == "SUPPORTED":
            status = "ok"
        else:
            status = "warn"
            reasons.append(v.get("problem") or v["verdict"].lower().replace("_", " "))
        if c.exactness == "approx":
            status = "warn" if status == "ok" else status
            reasons.append("quote matches the book only approximately")
        bad_pages = [p for p in c.pages if set(quality.get(p, [])) & {"garbled", "scanned-no-text"}]
        # OCR text is reliable for words; digits, signs and decimal points are where it slips
        ocr_pages = [p for p in c.pages if "ocr" in quality.get(p, []) and p not in bad_pages]
        if bad_pages and status == "ok":
            status = "warn"
            reasons.append(f"text extraction on p.{', p.'.join(bad_pages)} may be unreliable")
        elif ocr_pages and status == "ok" and re.search(r"\d", c.text):
            status = "warn"
            reasons.append(f"p.{', p.'.join(ocr_pages)} was read by OCR: check the numbers against the printed page")
        out["claims"][c.loc] = {"status": status, "reasons": reasons, "claim": c.text, "pages": c.pages,
                                "block": c.block_id, "field": c.field, "file": c.file, "line": c.line}
        out["counts"][status] += 1
    for f in formula_items(ws, ch):
        v = data["formulas"].get(f["id"])
        status = "pending" if v is None else ("ok" if v["verdict"] == "MATCH" else "warn")
        out["formulas"][f["block"]] = {"status": status, "reason": (v or {}).get("problem") or
                                       ("" if status != "warn" else "could not be confirmed against the printed formula")}
    for q in extract_questions(ws, ch):
        e = data["questions"].get(q.hash)
        if e is None or e.get("status") in ("reconcile",):
            status = "pending"
        elif e.get("status") == "agreed":
            status = "ok"
        else:
            status = "warn"
        out["questions"][q.block_id] = {"status": status, "reason": (e or {}).get("reason", ""), "file": q.file}
    return out
