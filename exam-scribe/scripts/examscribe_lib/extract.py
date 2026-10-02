"""`extract`: a book's text as Markdown, in seconds, without a workspace.

For agents that cannot read PDFs (or would do it slowly, page image by page image): the text layer is read
directly - never OCR a PDF that has text. The output keeps page markers (<!-- page 12 -->, with the book's
printed page numbers), headings (#, ##) and **bold** key terms, so it can also be given to `init` as the book.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from .common import ESError, Workspace, make_temp_dir, write_json, write_text


def _md_para(p: dict) -> str:
    text = p["text"]
    out, pos = "", 0
    for a, b in sorted(p.get("bold") or []):
        if a < pos or b <= a:
            continue
        piece = text[a:b]
        if not piece.strip():
            continue
        out += text[pos:a] + "**" + piece.strip() + "**" + (" " if piece.endswith(" ") else "")
        pos = b
    return out + text[pos:]


def extract_markdown(book: Path, out: Path | None = None, pages: str | None = None, language: str = "en",
                     progress=None) -> dict:
    from .config import resolve_pages
    from .ingest import ingest
    book = book.resolve()
    if not book.exists():
        raise ESError(f"File not found: {book}")
    start = time.perf_counter()
    tmp = make_temp_dir("examscribe-extract-")
    try:
        ws = Workspace(tmp)
        write_json(ws.config_path, {"version": 1, "title": book.stem, "tier": "strict",
                                    "book": {"file": str(book), "language": language}, "scope": {"chapters": None},
                                    "intake": {"done": False}})
        ws.reload()
        summary = ingest(ws, progress=progress)
        ws.reload()
        chosen = None
        if pages:
            r = resolve_pages(ws, pages)
            chosen = {i for a, b in r["ranges"] for i in range(a, b + 1)} if r else None
        body = ws.outline.get("body_size") or 10.0
        parts = [f"<!-- ExamScribe extract of {book.name}: {summary['pages']} pages; page markers show the book's "
                 f"page numbers -->"]
        n_pages = 0
        for page in ws.pages:
            if chosen is not None and page["index"] not in chosen:
                continue
            n_pages += 1
            parts.append(f"\n<!-- page {page['label']} -->\n")
            if "scanned-no-text" in page["flags"]:
                parts.append("*(scanned page without a text layer: run the ExamScribe `ocr` command to read it)*\n")
            for p in page["paras"]:
                if p.get("in_figure"):
                    continue
                if p["heading"]:
                    level = 1 if p["size"] >= 1.45 * body else 2
                    parts.append("#" * level + " " + p["text"].strip() + "\n")
                else:
                    parts.append(_md_para(p) + "\n")
        text = "\n".join(parts).rstrip() + "\n"
        if out is None:
            out = Path.cwd() / (book.stem + ".md")
        write_text(out, text)
        return {"out": str(out), "pages": n_pages, "chars": len(text), "seconds": round(time.perf_counter() - start, 1),
                "reader": summary.get("reader"), "needs_ocr": summary.get("needs_ocr", 0)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
