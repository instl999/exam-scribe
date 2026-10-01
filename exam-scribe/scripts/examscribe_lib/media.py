"""Pictures made only when a chapter needs them: figure/table crops, printed-equation crops and page renders.

Rendering every figure and equation of a 600-page book at extraction time is slow and mostly wasted when the
exam covers a few chapters. Instead, the first time a chapter is worked on (and before every build) the pictures
for that chapter are made; later calls find the files and only link them.
"""
from __future__ import annotations

from pathlib import Path

from .common import Workspace, read_json, write_json
from .ingest import PDF_LIKE

try:
    import pymupdf
except ImportError:  # pragma: no cover
    pymupdf = None

DOUBTFUL = {"scanned-no-text", "garbled", "math-heavy", "extraction-error", "ocr"}
MAX_PAGE_RENDERS = 60


class _Book:
    """Opens the PDF on first use only (most calls have nothing to render)."""

    def __init__(self, path: Path):
        self.path = path
        self.doc = None

    def page(self, index: int):
        if self.doc is None:
            self.doc = pymupdf.open(str(self.path))
        return self.doc[index]


def _crop(book: _Book, index: int, rect: list[float], out: Path, dpi: int) -> bool:
    try:
        page = book.page(index)
        r = pymupdf.Rect(*rect) & page.rect
        if r.is_empty:
            return False
        out.parent.mkdir(parents=True, exist_ok=True)
        page.get_pixmap(dpi=dpi, clip=r).save(str(out))
        return True
    except Exception:  # pragma: no cover - a broken page must not stop the pipeline
        return False


def ensure_chapter_media(ws: Workspace, ch: dict) -> int:
    """Make the missing pictures for one chapter and link them in figures.json and the chapter inventory.
    Returns how many pictures were rendered."""
    book_path = ws.root / ws.config["book"]["file"]
    if pymupdf is None or book_path.suffix.lower() not in PDF_LIKE:
        return 0
    book = _Book(book_path)
    lo, hi = ch["start"]["page"], ch["end"]["page"]
    made = 0

    # figures and tables
    fig_path = ws.source_dir / "figures.json"
    figures = read_json(fig_path, []) or []
    changed = False
    for f in figures:
        if not (lo <= f["page_index"] <= hi) or not f.get("crop"):
            continue
        rel = f"source/figures/{f['id']}.png"
        if not (ws.root / rel).exists():
            if not _crop(book, f["page_index"], f["crop"], ws.root / rel, 150):
                continue
            made += 1
        if f.get("image") != rel:
            f["image"] = rel
            changed = True
    if changed:
        write_json(fig_path, figures)
    images = {f["id"]: f["image"] for f in figures if f.get("image")}

    # equations (and figure links) in the chapter inventory
    inv_path = ws.inventory_path(ch["id"])
    inv = read_json(inv_path, None)
    if inv:
        inv_changed = False
        for it in inv.get("items", []):
            if it["kind"] in ("figure", "table"):
                img = images.get(it["id"])
                if img and it.get("image") != img:
                    it["image"] = img
                    inv_changed = True
            elif it["kind"] == "equation" and it.get("bbox") and it.get("page_index") is not None:
                rel = f"source/equations/{it['id']}.png"
                if not (ws.root / rel).exists():
                    x0, y0, x1, y1 = it["bbox"]
                    if not _crop(book, it["page_index"], [x0 - 12, y0 - 5, x1 + 12, y1 + 5], ws.root / rel, 170):
                        continue
                    made += 1
                if it.get("image") != rel:
                    it["image"] = rel
                    inv_changed = True
        if inv_changed:
            write_json(inv_path, inv)

    # renders of doubtful pages, so a person or a vision model can compare; only pages of the exam scope, and
    # never more than MAX_PAGE_RENDERS per chapter (any other page: `page <ws> <label> --image`)
    ranges = ws.scope_ranges()
    doubtful = [p for p in ws.pages[lo:hi + 1] if set(p.get("flags") or []) & DOUBTFUL and
                (not ranges or any(a <= p["index"] <= b for a, b in ranges))]
    for page in doubtful[:MAX_PAGE_RENDERS]:
        out = ws.page_images_dir / f"p{page['index'] + 1:04d}.png"
        if not out.exists():
            try:
                out.parent.mkdir(parents=True, exist_ok=True)
                book.page(page["index"]).get_pixmap(dpi=110).save(str(out))
                made += 1
            except Exception:  # pragma: no cover
                pass
    return made
