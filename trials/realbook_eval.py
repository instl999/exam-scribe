"""Run a real book through ExamScribe's extraction stages and summarise what came out, for a human to inspect.

    python realbook_eval.py <book.pdf> <work-folder> [--ocr-pages 1-6] [--language xx] [--chapters 3]

Stages: probe -> init -> ingest -> (OCR of a few pages if the book needs it) -> inventory. Prints timings,
the outline, quality flags, sample paragraphs, key terms, figures/equations/examples per chapter.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.environ.get("EXAMSCRIBE_SCRIPTS") or str(Path(__file__).resolve().parents[1] / "exam-scribe" / "scripts"))
from examscribe_lib.common import setup_console, split_sentences  # noqa: E402

setup_console()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("book")
    ap.add_argument("work")
    ap.add_argument("--ocr-pages", default=None)
    ap.add_argument("--language", default=None)
    ap.add_argument("--chapters", type=int, default=3)
    a = ap.parse_args()
    from examscribe_lib.config import init_workspace
    from examscribe_lib.ingest import ingest
    from examscribe_lib.inventory import build_inventory
    from examscribe_lib.probe import probe_book, probe_text
    book = Path(a.book)
    t = time.perf_counter()
    info = probe_book(book, a.language)
    t_probe = time.perf_counter() - t
    print(probe_text(info))
    print(f"[probe {t_probe:.1f}s]")
    ws_dir = Path(a.work) / ("ws-" + book.stem)
    keep = Path(a.work) / ("ocr-cache-" + book.stem)      # OCR results survive a fresh workspace
    if (ws_dir / "source" / "ocr").is_dir():
        shutil.rmtree(keep, ignore_errors=True)
        shutil.copytree(ws_dir / "source" / "ocr", keep)
    shutil.rmtree(ws_dir, ignore_errors=True)
    lang = a.language or info.get("lang_guess") or "en"
    ws = init_workspace(ws_dir, book, "strict", None, lang)
    if keep.is_dir():
        shutil.copytree(keep, ws_dir / "source" / "ocr", dirs_exist_ok=True)
    t = time.perf_counter()
    s = ingest(ws, progress=None)
    t_ingest = time.perf_counter() - t
    print(f"\n[ingest {t_ingest:.1f}s] pages={s['pages']} labels={s['label_method']} outline={s['outline_method']} "
          f"reader={s.get('reader')} needs_ocr={s['needs_ocr']} figures={s['figures']}")
    if a.ocr_pages:
        from examscribe_lib import ocr as O
        from examscribe_lib.config import resolve_pages
        r = resolve_pages(ws, a.ocr_pages)
        idx = [i for x, y in r["ranges"] for i in range(x, y + 1)]
        eng = O.pick_engine(ws)
        if eng:
            t = time.perf_counter()
            res = O.run_ocr(ws, O.pages_to_ocr(ws, idx) or idx, eng, budget=0, say=None)
            t_ocr = time.perf_counter() - t
            s = ingest(ws)
            print(f"[ocr {eng.name} {len(idx)} pages {t_ocr:.0f}s = {t_ocr / max(1, len(idx)):.1f}s/page; problems "
                  f"{res['problems'][:2]}] outline now: {s['outline_method']}")
        else:
            print("[ocr] no engine")
    ws.reload()
    t = time.perf_counter()
    build_inventory(ws)
    t_inv = time.perf_counter() - t
    ws.reload()
    print(f"[inventory {t_inv:.1f}s]")
    flags = Counter(f for p in ws.pages for f in p["flags"])
    print("flags:", dict(flags))
    outline = ws.outline
    print(f"\nOUTLINE ({outline['method']}): {len(outline['chapters'])} chapters; other: "
          f"{[o['title'][:30] for o in outline.get('other', [])][:8]}")
    for c in outline["chapters"][:40]:
        secs = [x for x in c["sections"] if x["kind"] == "content"]
        ends = [x for x in c["sections"] if x["kind"] == "end"]
        a_ = ws.pages[c["start"]["page"]]["label"]
        print(f"  {c['id']:<7} p.{a_:<6} {c['title'][:50]:<50} {len(secs)} sections, {len(ends)} end parts")
    for c in outline["chapters"][: a.chapters]:
        inv = ws.inventory(c["id"])
        kinds = Counter(it["kind"] for it in inv["items"])
        print(f"\n== {c['id']} {c['title'][:60]}: {dict(kinds)}; exercises {len(inv.get('exercises', []))}")
        for sec in [x for x in c["sections"] if x["kind"] != "other"][:12]:
            print(f"     {sec['kind']:<7} {sec['id']:<12} {sec['title'][:60]}")
        terms = [it for it in inv["items"] if it["kind"] == "term"]
        for it in terms[:12]:
            print(f"     term {it['text'][:28]:<28} p.{it['page']:<5} {it.get('found_by', 'bold'):<10} | {it['context'][:70]}")
        for it in [it for it in inv["items"] if it["kind"] in ("equation", "example", "figure", "table")][:6]:
            print(f"     {it['kind']:<8} {it['id']:<12} {(it.get('text') or it.get('caption') or it.get('title') or '')[:70]}")
    # a sample page from the first chapter's middle
    if outline["chapters"]:
        c = outline["chapters"][0]
        mid = (c["start"]["page"] + min(c["end"]["page"], len(ws.pages) - 1)) // 2
        page = ws.pages[mid]
        print(f"\nSAMPLE p.{page['label']} flags={page['flags']}:")
        for p in page["paras"][:6]:
            print(f"   [{'H' if p['heading'] else ' '}{p['size']}] {p['text'][:160]}")
        sents = split_sentences(page["text"])[:3]
        print("   sentences:", [x[:60] for x in sents])
    print(f"\nTIMINGS probe {t_probe:.1f}s, ingest {t_ingest:.1f}s, inventory {t_inv:.1f}s")


if __name__ == "__main__":
    main()
