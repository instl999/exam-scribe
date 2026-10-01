"""Books that arrive as pictures: photos or scans of pages (JPG, PNG, TIFF, ...) or a folder of them.

They are put together into one PDF, in page order, which is then read like any scanned book (OCR of the pages
on the exam). DjVu files are not readable by PyMuPDF; the user gets the command to convert them.
"""
from __future__ import annotations

import re
from pathlib import Path

from .common import ESError

IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif", ".webp", ".jp2", ".jpx", ".pnm", ".pbm",
               ".pgm", ".ppm"}


def _natural(name: str) -> list:
    """'page10.jpg' after 'page9.jpg'."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def page_images(path: Path) -> list[Path]:
    """The page pictures a book path stands for (empty if it is not a picture or a folder of pictures)."""
    if path.is_dir():
        return sorted((p for p in path.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_TYPES),
                      key=lambda p: _natural(p.name))
    if path.is_file() and path.suffix.lower() in IMAGE_TYPES:
        return [path]
    return []


def prepare_book(path: Path, out_pdf: Path) -> Path:
    """Return a readable book file for `path`: the path itself, or a PDF made from its page pictures."""
    if path.suffix.lower() in (".djvu", ".djv"):
        raise ESError("DjVu books cannot be read directly.",
                      "Convert the file to PDF first, e.g. with DjVuLibre: ddjvu -format=pdf book.djvu book.pdf "
                      "(or any DjVu-to-PDF converter), then use the PDF.")
    images = page_images(path)
    if not images:
        if path.is_dir():
            raise ESError(f"The folder {path} has no page pictures or book file.",
                          "Give a PDF (or EPUB, text, Markdown), a picture of a page, or a folder of page pictures.")
        return path
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover
        raise ESError("Books made of pictures need PyMuPDF.", "Run: python -m pip install pymupdf") from exc
    doc = pymupdf.open()
    bad = []
    for img_path in images:
        try:
            img = pymupdf.open(str(img_path))            # a multi-page TIFF gives several pages
            doc.insert_pdf(pymupdf.open("pdf", img.convert_to_pdf()))
        except Exception:
            bad.append(img_path.name)
    if not doc.page_count:
        raise ESError(f"None of the pictures could be read ({', '.join(bad[:5])}).",
                      "Use JPG, PNG or TIFF pictures, or a PDF.")
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_pdf), garbage=3, deflate=True)
    if bad:
        print(f"NOTE: {len(bad)} picture(s) could not be read and are left out: {', '.join(bad[:8])}")
    return out_pdf
