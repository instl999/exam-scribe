"""Read a PDF's text layer without PyMuPDF.

PyMuPDF is the fast reader (a 200-page book in about a second) and the only one that makes pictures and runs
OCR. Where it cannot be installed (some sandboxes block pip or compiled packages), text PDFs are still read:

  pdfplumber  fonts, sizes, bold and positions, so the result is close to PyMuPDF's; ~50-150 ms per page.
              Bookmarks and page labels come from pypdfium2, which pdfplumber installs.
  pypdf       plain text per page plus bookmarks and page labels; ~50 ms per page; no bold, no layout.

Either way the book is never OCR'd just because PyMuPDF is missing: a text PDF has its text inside.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .common import ESError


def available() -> str | None:
    """The fallback reader that would be used ("pdfplumber", "pypdf") or None."""
    forced = os.environ.get("EXAMSCRIBE_PDF_READER", "").lower()
    order = [forced] if forced in ("pdfplumber", "pypdf") else ["pdfplumber", "pypdf"]
    for name in order:
        try:
            __import__(name)
            return name
        except Exception:
            continue
    return None


def read_pdf(path: Path, progress=None):
    """(pages as ingest.PageExtract, toc as [[level, title, page_number]]) using the best fallback reader."""
    name = available()
    if name is None:
        raise ESError("No PDF reader is installed.",
                      "Install PyMuPDF (python -m pip install pymupdf). If that is impossible, pdfplumber or pypdf "
                      "also work (slower). Or convert the book to text first (e.g. pdftotext book.pdf book.txt) and "
                      "use the .txt file.")
    if progress:
        progress(f"  PyMuPDF is not available: reading the text layer with {name} (slower, no figure pictures)")
    return _read_pdfplumber(path, progress) if name == "pdfplumber" else _read_pypdf(path, progress)


# ------------------------------------------------------------------------------------------ pdfplumber

def _segments(words: list[dict]) -> list[dict]:
    """Group words into rows (same baseline, within a tolerance) and rows into segments (a wide gap such as a
    column gutter starts a new segment)."""
    def size_of(w: dict) -> float:
        return float(w.get("size") or (w["bottom"] - w["top"]) or 10)
    rows: list[dict] = []
    for w in sorted(words, key=lambda w: ((w["top"] + w["bottom"]) / 2, w["x0"])):
        cy = (w["top"] + w["bottom"]) / 2
        if rows and abs(cy - rows[-1]["cy"]) <= 0.45 * max(size_of(w), rows[-1]["size"]):
            rows[-1]["words"].append(w)
        else:
            rows.append({"cy": cy, "size": size_of(w), "words": [w]})
    segs: list[dict] = []
    for row in rows:
        cur = None
        for w in sorted(row["words"], key=lambda w: w["x0"]):
            size = size_of(w)
            span = {"text": w["text"], "bbox": (w["x0"], w["top"], w["x1"], w["bottom"]), "size": size,
                    "font": w.get("fontname") or "", "flags": 0}
            if cur is not None and w["x0"] - cur["x1"] <= 1.5 * max(size, cur["size"]):
                cur["spans"].append(span)
                cur["x1"] = max(cur["x1"], w["x1"])
                cur["y0"], cur["y1"] = min(cur["y0"], w["top"]), max(cur["y1"], w["bottom"])
                cur["chars"][size] = cur["chars"].get(size, 0) + len(w["text"])
            else:
                cur = {"x0": w["x0"], "x1": w["x1"], "y0": w["top"], "y1": w["bottom"], "size": size,
                       "spans": [span], "chars": {size: len(w["text"])}}
                segs.append(cur)
    for s in segs:
        s["size"] = round(max(s["chars"], key=s["chars"].get), 1)
        del s["chars"]
    return segs


def _pdfium_meta(path: Path, n: int) -> tuple[list, list[str]]:
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(path))
        toc = []
        for b in pdf.get_toc():
            dest = b.get_dest()
            idx = dest.get_index() if dest is not None else None
            if idx is not None:
                toc.append([b.level + 1, b.get_title(), idx + 1])
        labels = [pdf.get_page_label(i) or "" for i in range(n)]
        pdf.close()
        return toc, labels
    except Exception:
        return _pypdf_meta(path, n)


def _read_pdfplumber(path: Path, progress=None):
    import pdfplumber
    from .ingest import PageExtract, _rect_list, lines_from_raw
    pages = []
    with pdfplumber.open(str(path)) as pdf:
        n = len(pdf.pages)
        toc, labels = _pdfium_meta(path, n)
        fonts: dict[str, int] = {}
        per_page_words = []
        for i, page in enumerate(pdf.pages):
            try:
                words = page.extract_words(extra_attrs=["fontname", "size"], keep_blank_chars=False)
            except Exception as exc:  # pragma: no cover - broken page
                words, err = [], str(exc)
            else:
                err = ""
            for w in words:
                fonts[w.get("fontname") or ""] = fonts.get(w.get("fontname") or "", 0) + len(w["text"])
            pe = PageExtract(i, float(page.width), float(page.height))
            pe.pdf_label = labels[i] if i < len(labels) else ""
            pe.error = err
            for img in page.images:
                r = (img["x0"], img["top"], img["x1"], img["bottom"])
                if (r[2] - r[0]) * (r[3] - r[1]) >= 1600:
                    pe.images.append(_rect_list(r))
                    pe.image_area += (r[2] - r[0]) * (r[3] - r[1])
            for rc in page.rects:
                r = (rc["x0"], rc["top"], rc["x1"], rc["bottom"])
                if (r[2] - r[0]) > 2 or (r[3] - r[1]) > 2:
                    pe.drawings.append(_rect_list(r))
            per_page_words.append(words)
            pages.append(pe)
            for release in ("flush_cache", "close"):        # keep memory flat on long books
                if hasattr(page, release):
                    try:
                        getattr(page, release)()
                    except Exception:
                        pass
                    break
            if progress and (i + 1) % 50 == 0:
                progress(f"  read {i + 1} of {n} pages")
        body_font = max(fonts, key=fonts.get) if fonts else None
        for pe, words in zip(pages, per_page_words):
            pe.lines, pe.two_column = lines_from_raw(_segments(words), pe.width, body_font)
            for r in pe.drawings:                       # boxed notes: framed text
                x0, y0, x1, y1 = r
                w, h = x1 - x0, y1 - y0
                if w > 150 and h > 25 and w * h < 0.6 * pe.width * pe.height:
                    inside = [l for l in pe.lines if l["x0"] >= x0 - 2 and l["x1"] <= x1 + 2 and
                              l["y0"] >= y0 - 2 and l["y1"] <= y1 + 2]
                    if inside and sum(len(l["text"]) for l in inside) > 30 and r not in pe.boxes:
                        pe.boxes.append(r)
    return pages, toc


# ------------------------------------------------------------------------------------------ pypdf

def _pypdf_labels(reader) -> list[str]:
    """Page labels only if the PDF defines them (pypdf invents 1, 2, 3 ... otherwise)."""
    try:
        if "/PageLabels" not in reader.trailer["/Root"]:
            return []
        return list(reader.page_labels)
    except Exception:
        return []


def _pypdf_meta(path: Path, n: int) -> tuple[list, list[str]]:
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        return _pypdf_toc(reader), _pypdf_labels(reader)[:n]
    except Exception:
        return [], []


def _pypdf_toc(reader) -> list:
    out = []

    def walk(items, level):
        for it in items:
            if isinstance(it, list):
                walk(it, level + 1)
                continue
            try:
                out.append([level, str(it.title), reader.get_destination_page_number(it) + 1])
            except Exception:
                continue
    try:
        walk(reader.outline, 1)
    except Exception:
        pass
    return out


def _read_pypdf(path: Path, progress=None):
    import pypdf
    from .ingest import PageExtract
    reader = pypdf.PdfReader(str(path))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise ESError("The PDF is password-protected.", "Ask the user for an unlocked copy of the book.")
    labels = _pypdf_labels(reader)
    toc = _pypdf_toc(reader)
    # plain text has no fonts: lines equal to a bookmark title are marked as headings
    titles = {re.sub(r"\s+", "", t).casefold() for _, t, _ in toc}
    pages = []
    n = len(reader.pages)
    for i, page in enumerate(reader.pages):
        box = page.mediabox
        pe = PageExtract(i, float(box.width), float(box.height))
        pe.pdf_label = labels[i] if i < len(labels) else ""
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # pragma: no cover
            text, pe.error = "", str(exc)
        lines = [re.sub(r"\s+", " ", l).strip() for l in text.splitlines()]
        lines = [l for l in lines if l]
        y = 60.0
        for k, line in enumerate(lines):
            width = 5.2 * sum(2 if _WIDE.match(c) else 1 for c in line)
            heading = re.sub(r"\s+", "", line).casefold() in titles
            size = 14.0 if heading else 10.0
            y0 = y
            if k in (0, len(lines) - 1) and re.fullmatch(r"(?:page\s*)?[\divxlcIVXLC]{1,6}", line, re.I):
                y0 = 20.0 if k == 0 else pe.height - 30.0            # a printed page number: header or footer
            pe.lines.append({"x0": 72.0, "x1": 72.0 + min(pe.width - 144, width), "y0": y0, "y1": y0 + size * 1.2,
                             "size": size, "text": line, "bold": [[0, len(line)]] if heading else [], "italic": []})
            y += size * 1.4
        pages.append(pe)
        if progress and (i + 1) % 100 == 0:
            progress(f"  read {i + 1} of {n} pages")
    return pages, toc


_WIDE = re.compile(r"[ᄀ-ᅟ⺀-꓏가-힣豈-﫿︰-﹏＀-｠￠-￦]")


def page_count(path: Path) -> int:
    name = available()
    if name == "pdfplumber":
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            return len(pdf.pages)
    import pypdf
    return len(pypdf.PdfReader(str(path)).pages)
