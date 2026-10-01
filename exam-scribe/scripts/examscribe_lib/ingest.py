"""Stage 1: extract the book into page records, an outline, figures, and quality flags.

Outputs (inside the workspace):
  source/pages.jsonl   one record per page: label, reading-order paragraphs, flags
  source/outline.json  chapters and sections with page/y boundaries
  source/figures.json  figures/tables with captions and crop rectangles (pictures are made later, per chapter,
                       by media.py; page renders of doubtful pages too)
  source/quality.json  per-page extraction problems (scanned, garbled, math-heavy, ...) and pages needing OCR

Extraction is one pass per page (text + a cheap drawing log), run in parallel processes for big books.
Pages without a text layer get their text from OCR (ocr.py), cached per page in source/ocr/.
"""
from __future__ import annotations

import os
import re
import shutil
import statistics
from collections import Counter
from pathlib import Path

from . import lang as L
from .common import (CLI, ESError, Workspace, fix_ligatures, key_of, read_json, word_count, write_json,
                     write_jsonl,
                     write_text)

try:  # PyMuPDF is required for PDF/EPUB input; plain text/Markdown works without it.
    import pymupdf
except ImportError:  # pragma: no cover
    pymupdf = None

PDF_LIKE = {".pdf", ".epub", ".mobi", ".fb2", ".xps", ".cbz", ".svg"}
TEXT_LIKE = {".txt", ".md", ".markdown"}

CAPTION_RE = re.compile(r"^(?P<kind>" + L.FIGURE_ALT + "|" + L.TABLE_ALT + r")\s*"
                        r"(?P<num>\d+(?:[.\-–]\d+)*[a-z]?)(?!\d)", re.I)
BULLET_RE = re.compile(r"^\s*(?:[•◦▪●‣⁃·\-\*–]|\(?[a-z0-9]{1,3}[.)])\s+")
BULLET_SYM_RE = re.compile(r"^\s*[•◦▪●‣⁃·\-\*–]\s+")
ENUM_RE = re.compile(r"^\s*\(?[a-z0-9]{1,3}[.)]\s+")
# "(2.14)", "(3-7a)"; not years such as "(1712-1778)"
EQ_NUM_RE = re.compile(r"[(（](\d{1,3}(?:[.\-－]\d{1,3})+[a-z]?)[)）]\s*$")
MATH_CHARS = set("=+−×÷∑∫√≤≥≈≠±∂∞Δαβ"
                 "γδθλμπσωΩ²³")
OTHER_TITLES = re.compile(r"^(?:" + L._alt(L.NOT_CHAPTER) + r")|^(?:" + L._alt(L.NOT_CHAPTER_EXACT) + r")[\s\d.:]*$",
                          re.I)
END_MATTER = L.head_re(L.SUMMARY, L.KEY_TERMS, L.KEY_EQUATIONS, L.EXERCISES, L.BACK_MATTER)
_OWN_HEADS = L.head_re(L.OBJECTIVES, L.EXAMPLE)          # headings of their own kind, never a title's 2nd line
# chapter numbers: digits, roman numerals, or roman numerals as OCR misreads them ("V1", "Xl", "1V"; not the
# "1C" of "Lesson 1C")
_CH_NUM = r"(?:\d+|[ivxlc]+|[IVXLC]+|[IVXLC][IVXLC1l|]*|1[VX][IVXLC1l|]*)"
CHAPTER_TITLE = re.compile(r"^(?:(?:" + L.CHAPTER_WORD_ALT + r")\s+(?P<a>" + _CH_NUM + r")(?![^\W\d_])|"
                           r"(?P<b>\d+)[\s.:]+(?!\d)\S|"               # "1.1 Title" is a section, not chapter 1
                           r"第\s*(?P<c>[\d一-鿿]+)\s*[章课課]|제\s*(?P<d>\d+)\s*장|"
                           r"(?:الفصل|الباب|الوحدة)\s+(?P<e>\S+)|(?:अध्याय|इकाई)\s+(?P<f>\S+))", re.I)
CHAPTER_LABEL = re.compile(r"^(?:(?:" + L.CHAPTER_WORD_ALT + r")\s+" + _CH_NUM + r"|第\s*[\d一-鿿]+\s*[章课課]|"
                           r"제\s*\d+\s*장|(?:الفصل|الباب|الوحدة)\s+\S+|(?:अध्याय|इकाई)\s+\S+)[.:]?$", re.I)
SECTION_NUM = re.compile(r"^(?P<num>\d+(?:\.\d+)+)\.?\s+(?P<title>.+)$")


# ============================================================================ helpers

def roman(n: int) -> str:
    vals = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
            (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
    out = ""
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out


# Chinese and Japanese books mark key terms with a Hei / Gothic font instead of a bold weight
_EMPHASIS_FONT = re.compile(r"hei|gothic|goth\b|黑|ゴシック|(?:^|[^a-z])HT(?:[^a-z]|$)", re.I)
_CJK_TEXT = re.compile(r"[぀-ヿ㐀-鿿]")


def _is_bold(span: dict, body_font: str | None = None) -> bool:
    font = span.get("font", "")
    cf = span.get("char_flags", 0)
    if (cf & 48) == 48:                      # text drawn filled + stroked: fake bold
        return True
    named_bold = bool(re.search(r"bold|black|heavy|semibold|demi", font, re.I))
    if named_bold and font == body_font:
        # the book's text face is itself a bold face (some Japanese and Chinese books set all body text in a bold
        # Mincho / Song): it marks nothing
        return False
    if span.get("flags", 0) & 16 or named_bold or cf & 8:     # a bold font, or MuPDF's synthetic bold
        return True
    return bool(body_font and font != body_font and _EMPHASIS_FONT.search(font) and
                not _EMPHASIS_FONT.search(body_font) and _CJK_TEXT.search(span.get("text", "")))


def _is_italic(span: dict) -> bool:
    font = span.get("font", "")
    return bool(span.get("flags", 0) & 2) or bool(re.search(r"italic|oblique", font, re.I))


def _is_math_line(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    math = sum(1 for c in t if c in MATH_CHARS)
    return ("=" in t and len(t) < 90) or math >= 3 or bool(EQ_NUM_RE.search(t))


# ============================================================================ line building

def _raw_lines(page) -> list[dict]:
    flags = pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP
    d = page.get_text("dict", flags=flags)
    lines = []
    for b in d["blocks"]:
        if b.get("type") != 0:
            continue
        for ln in b["lines"]:
            spans = [s for s in ln["spans"] if s["text"] != ""]
            if not spans or not "".join(s["text"] for s in spans).strip():
                continue
            x0 = min(s["bbox"][0] for s in spans)
            x1 = max(s["bbox"][2] for s in spans)
            y0 = min(s["bbox"][1] for s in spans)
            y1 = max(s["bbox"][3] for s in spans)
            size = Counter()
            for s in spans:
                size[round(s["size"], 1)] += len(s["text"])
            lines.append({"x0": x0, "x1": x1, "y0": y0, "y1": y1, "size": size.most_common(1)[0][0],
                          "spans": spans})
    return lines


def _gutter_between(a: dict, b: dict, width: float | None) -> bool:
    """True when two same-baseline pieces are the ends of lines in two different columns."""
    if not width:
        return False
    left, right = (a, b) if a["x0"] <= b["x0"] else (b, a)
    gap0, gap1 = left["x1"], right["x0"]
    size = max(a["size"], b["size"])
    long_enough = all(sum(len(s["text"].strip()) for s in x["spans"]) >= 15 for x in (a, b))
    return long_enough and gap1 - gap0 >= 0.8 * size and gap0 < 0.62 * width and gap1 > 0.38 * width


def _merge_visual(lines: list[dict], width: float | None = None) -> list[dict]:
    """Merge PyMuPDF lines that sit on the same baseline (e.g. an equation and its number), but never across the
    gutter of a two-column page."""
    lines = sorted(lines, key=lambda l: ((l["y0"] + l["y1"]) / 2, l["x0"]))
    merged: list[dict] = []
    for ln in lines:
        cy = (ln["y0"] + ln["y1"]) / 2
        placed = False
        for m in reversed(merged[-4:]):
            mcy = (m["y0"] + m["y1"]) / 2
            tol = 0.45 * max(m["size"], ln["size"])
            overlap = not (ln["x1"] <= m["x0"] + 1 or ln["x0"] >= m["x1"] - 1)
            if abs(cy - mcy) <= tol and not overlap and not _gutter_between(m, ln, width):
                m["spans"].extend(ln["spans"])
                m["x0"], m["x1"] = min(m["x0"], ln["x0"]), max(m["x1"], ln["x1"])
                m["y0"], m["y1"] = min(m["y0"], ln["y0"]), max(m["y1"], ln["y1"])
                placed = True
                break
        if not placed:
            merged.append(dict(ln, spans=list(ln["spans"])))
    return merged


def _line_text(ln: dict, body_font: str | None = None) -> dict:
    """Build text for a visual line with bold/italic ranges and _sub / ^sup markers."""
    spans = sorted(ln["spans"], key=lambda s: s["bbox"][0])
    size = ln["size"]
    base_cy = None
    normal = [s for s in spans if s["size"] >= 0.9 * size]
    if normal:
        base_cy = statistics.median((s["bbox"][1] + s["bbox"][3]) / 2 for s in normal)
    text = ""
    bold: list[list[int]] = []
    italic: list[list[int]] = []
    last_x1 = None
    for si, s in enumerate(spans):
        t = fix_ligatures(s["text"])
        if "­" in t:
            # soft hyphens are invisible; only one ending the line matters: it marks a word broken across lines
            core = t.rstrip()
            soft_end = si == len(spans) - 1 and core.endswith("­")
            t = t.replace("­", "") if not soft_end else core.replace("­", "") + "­"
        if not t:
            continue
        x0 = s["bbox"][0]
        if last_x1 is not None and text and not text.endswith(" ") and not t.startswith(" "):
            if x0 - last_x1 > 0.18 * size:
                text += " "
        marker = ""
        # (Chinese / Japanese / Korean text is never a sub- or superscript: small raised CJK text is a label or ruby)
        if base_cy is not None and s["size"] < 0.85 * size and t.strip() and not s.get("ocr") and \
                not _CJK_TEXT.search(t) and not re.search(r"[가-힯]", t):
            cy = (s["bbox"][1] + s["bbox"][3]) / 2
            if cy > base_cy + 0.12 * size:
                marker = "_"
            elif cy < base_cy - 0.12 * size:
                marker = "^"
        if marker:
            core = t.strip()
            t = marker + (core if len(core) == 1 else "{" + core + "}")
        start = len(text)
        text += t
        end = len(text)
        if t.strip():
            if _is_bold(s, body_font):
                if bold and bold[-1][1] >= start - 1:
                    bold[-1][1] = end
                else:
                    bold.append([start, end])
            if _is_italic(s) and len(t.strip()) > 1:
                italic.append([start, end])
        last_x1 = s["bbox"][2]
    # trim and shift ranges
    lead = len(text) - len(text.lstrip())
    text = text.strip()
    shift = lambda r: [[max(0, a - lead), min(len(text), b - lead)] for a, b in r if b - lead > 0]
    bold_r = [[a, b] for a, b in shift(bold) if b > a]
    # tighten bold ranges to non-space characters
    tight = []
    for a, b in bold_r:
        while a < b and text[a] == " ":
            a += 1
        while b > a and text[b - 1] == " ":
            b -= 1
        if b > a:
            tight.append([a, b])
    return {"x0": round(ln["x0"], 1), "x1": round(ln["x1"], 1), "y0": round(ln["y0"], 1), "y1": round(ln["y1"], 1),
            "size": ln["size"], "text": text, "bold": tight, "italic": shift(italic)}


def _order_columns(vlines: list[dict], width: float) -> tuple[list[dict], bool]:
    mid = width / 2
    left = [l for l in vlines if l["x1"] < mid + 8]
    right = [l for l in vlines if l["x0"] > mid - 8]
    full = [l for l in vlines if l not in left and l not in right]
    two_col = len(left) >= 8 and len(right) >= 8 and len([l for l in full if len(l["text"]) > 40]) < 0.25 * len(vlines)
    if not two_col:
        return sorted(vlines, key=lambda l: (round(l["y0"], 0), l["x0"])), False
    # bands separated by full-width lines
    ordered: list[dict] = []
    fulls = sorted(full, key=lambda l: l["y0"])
    bounds = [-1e9] + [l["y0"] for l in fulls] + [1e9]
    for i in range(len(bounds) - 1):
        lo, hi = bounds[i], bounds[i + 1]
        if i > 0:
            ordered.append(fulls[i - 1])
        band_l = sorted([l for l in left if lo <= l["y0"] < hi], key=lambda l: l["y0"])
        band_r = sorted([l for l in right if lo <= l["y0"] < hi], key=lambda l: l["y0"])
        ordered.extend(band_l + band_r)
    return ordered, True


# ============================================================================ page model

class PageExtract:
    def __init__(self, index: int, width: float, height: float):
        self.index = index
        self.width = width
        self.height = height
        self.lines: list[dict] = []
        self.two_column = False
        self.images: list[list[float]] = []
        self.drawings: list[list[float]] = []
        self.boxes: list[list[float]] = []
        self.image_area = 0.0
        self.pdf_label = ""
        self.ocr = False
        self.error = ""


def _rect_list(r) -> list[float]:
    return [round(r[0], 1), round(r[1], 1), round(r[2], 1), round(r[3], 1)]


def lines_from_raw(raw: list[dict], width: float, body_font: str | None = None) -> tuple[list[dict], bool]:
    """Turn raw span lines (from a PDF text layer or OCR) into ordered visual lines."""
    vlines = [_line_text(l, body_font) for l in _merge_visual(raw, width)]
    vlines = [l for l in vlines if l["text"]]
    return _order_columns(vlines, width)


def _extract_pdf_page(page, body_font: str | None = None) -> PageExtract:
    pe = PageExtract(page.number, page.rect.width, page.rect.height)
    pe.pdf_label = page.get_label() or ""
    try:
        raw = _raw_lines(page)
    except Exception as exc:  # pragma: no cover - corrupt page
        pe.error = str(exc)
        raw = []
    pe.lines, pe.two_column = lines_from_raw(raw, pe.width, body_font)
    # images and vector paths from the page's drawing log: one cheap call instead of decoding every path
    page_area = pe.width * pe.height
    try:
        log = page.get_bboxlog()
    except Exception:  # pragma: no cover
        log = []
    for kind, r in log:
        x0, y0, x1, y1 = r
        w, h = x1 - x0, y1 - y0
        if kind in ("fill-image", "fill-imgmask"):
            if w * h >= 1600:
                pe.images.append(_rect_list(r))
                pe.image_area += w * h
            continue
        if kind not in ("fill-path", "stroke-path"):
            continue
        if (w < 2 and h < 2) or (h < 1.5 and w > 0.6 * pe.width):     # dots and horizontal rules
            continue
        rect = _rect_list(r)
        pe.drawings.append(rect)
        if w > 150 and h > 25 and w * h < 0.6 * page_area:
            inside = [l for l in pe.lines if l["x0"] >= x0 - 2 and l["x1"] <= x1 + 2 and
                      l["y0"] >= y0 - 2 and l["y1"] <= y1 + 2]
            if inside and sum(len(l["text"]) for l in inside) > 30 and rect not in pe.boxes:
                pe.boxes.append(rect)
    return pe


def _extract_chunk(args: tuple) -> list[PageExtract]:
    """Worker for parallel extraction (runs in a separate process)."""
    path, start, end, body_font = args
    doc = pymupdf.open(path)
    return [_extract_pdf_page(doc[i], body_font) for i in range(start, end)]


def _body_font(doc, samples: int = 24) -> str | None:
    """The font the book's running text is set in (from a sample of pages): the font of spans at the most common
    size that make up most of their line. Headings (bigger) and bold terms (a small part of a line) do not count,
    so a short, heading-heavy book is not taken to be set in its bold face."""
    n = doc.page_count
    spans: list[tuple[str, float, int, float]] = []          # font, size, characters, share of its line
    pick = range(n) if n <= samples else sorted({int(k * (n - 1) / (samples - 1)) for k in range(samples)})
    for i in pick:
        try:
            d = doc[i].get_text("dict", flags=pymupdf.TEXT_MEDIABOX_CLIP)
        except Exception:  # pragma: no cover
            continue
        for b in d["blocks"]:
            for ln in b.get("lines", []):
                total = sum(len(s["text"].strip()) for s in ln["spans"]) or 1
                for s in ln["spans"]:
                    c = len(s["text"].strip())
                    if c:
                        spans.append((s["font"], round(s["size"], 1), c, c / total))
    if not spans:
        return None
    sizes: Counter = Counter()
    for _, size, c, _ in spans:
        sizes[size] += c
    body_size = sizes.most_common(1)[0][0]
    fonts: Counter = Counter()
    for font, size, c, share in spans:
        if abs(size - body_size) <= 0.1 * body_size and share >= 0.6:
            fonts[font] += c
    if not fonts:
        for font, _, c, _ in spans:
            fonts[font] += c
    return fonts.most_common(1)[0][0]


def extract_pages(book: Path, doc, jobs: int | None = None, progress=None) -> list[PageExtract]:
    """Extract every page, in parallel processes for big books (falls back to one process)."""
    n = doc.page_count
    body_font = _body_font(doc)
    if jobs is None:       # one process handles ~150 pages/s; extra processes only pay off for big books on many cores
        cpus = os.cpu_count() or 1
        jobs = min(cpus, 8) if n >= 400 and cpus >= 4 else 1
    if n >= 50 and jobs > 1:
        chunk = max(25, -(-n // (jobs * 4)))
        tasks = [(str(book), a, min(n, a + chunk), body_font) for a in range(0, n, chunk)]
        try:
            from concurrent.futures import ProcessPoolExecutor
            out: list[PageExtract] = []
            with ProcessPoolExecutor(max_workers=jobs) as pool:
                for i, part in enumerate(pool.map(_extract_chunk, tasks)):
                    out.extend(part)
                    if progress:
                        progress(f"  extracted {min(n, (i + 1) * chunk)} of {n} pages")
            return out
        except Exception as exc:          # sandboxes may forbid new processes
            if progress:
                progress(f"  (parallel extraction unavailable: {exc}; continuing in one process)")
    out = []
    for i in range(n):
        out.append(_extract_pdf_page(doc[i], body_font))
        if progress and (i + 1) % 200 == 0:
            progress(f"  extracted {i + 1} of {n} pages")
    return out


def _drop_meaningless_bold(pages: list[PageExtract]) -> None:
    """If most body text counts as bold (a book set in a bold or Hei/Gothic face), bold marks nothing: keep it
    only on short lines (headings) so that key terms are found from defining sentences instead."""
    total = bold = 0
    for pe in pages:
        for ln in pe.lines:
            n = len(ln["text"])
            total += n
            bold += sum(b - a for a, b in ln["bold"])
    if total and bold / total > 0.45:
        for pe in pages:
            for ln in pe.lines:
                if len(ln["text"]) > 40:
                    ln["bold"] = []


# ============================================================================ furniture (headers/footers)

def _furniture_keys(pages: list[PageExtract]) -> set[tuple[int, int]]:
    """Return (page_index, line_no) pairs for running headers, footers and page numbers."""
    marked: set[tuple[int, int]] = set()
    counts: Counter = Counter()
    cand: list[tuple[int, int, str]] = []
    sizes: Counter = Counter()
    for pe in pages:
        for ln in pe.lines:
            sizes[ln["size"]] += len(ln["text"])
    body = sizes.most_common(1)[0][0] if sizes else 10.0
    for pe in pages:
        top, bottom = pe.height * 0.085, pe.height * 0.915
        # scans keep the paper's margins: there the first and last line of a page are candidates a bit further in
        # (small lines only: a big chapter number or title at the top of a chapter's first page is no header)
        ys = sorted(range(len(pe.lines)), key=lambda i: pe.lines[i]["y0"])
        first = {i for i in ys if pe.lines[i]["y0"] <= pe.lines[ys[0]]["y1"]} if ys else set()
        last = {i for i in ys if pe.lines[i]["y1"] >= pe.lines[ys[-1]]["y0"]} if ys else set()
        for i, ln in enumerate(pe.lines):
            margin = ln["size"] <= 1.2 * body and ((i in first and ln["y1"] <= pe.height * 0.15) or
                                                   (i in last and ln["y0"] >= pe.height * 0.85))
            if ln["y1"] <= top or ln["y0"] >= bottom or margin:
                norm = re.sub(r"\d+", "#", ln["text"].casefold()).strip()
                norm = re.sub(r"\b[ivxlc]+\b", "#", norm)
                # repeats are counted without numbers and spaces: OCR gives one running head as "Title 7",
                # "7 Title", "Title7" or "Title" (number on a line of its own)
                core = re.sub(r"[#\s]+", "", norm)
                cand.append((pe.index, i, norm, core))
                counts[core or norm] += 1
    n = max(1, sum(1 for pe in pages if pe.lines))       # pages without text (unread scans) do not count
    for pidx, i, norm, core in cand:
        text = pages[pidx].lines[i]["text"].strip()
        is_number = bool(re.fullmatch(r"(page\s*)?[\divxlcIVXLC]{1,6}", text, re.I))
        seen = counts[core or norm]
        repeated = seen >= 3 and seen >= 0.2 * n and not CHAPTER_LABEL.match(text)
        # a running head with the page number at either end ("6 BOOK TITLE", "CHAPTER TITLE 7")
        numbered_head = ((norm.startswith("#") or norm.endswith("#")) and len(norm) < 60 and seen >= 2 and
                         not CHAPTER_LABEL.match(text))        # "Chapter 3" opening two chapters is no header
        if is_number or repeated or numbered_head:
            marked.add((pidx, i))
    return marked


# ============================================================================ page labels

def _assign_labels(pages: list[PageExtract], furniture_text: dict[int, list[str]]) -> tuple[list[str], str]:
    pdf_labels = [p.pdf_label for p in pages]
    # unique as written is enough ("I" for a cover page and roman "i" can both exist; see Workspace.label_index)
    if any(pdf_labels) and len(set(l for l in pdf_labels if l)) == len([l for l in pdf_labels if l]):
        labels = [l or f"pdf{i + 1}" for i, l in enumerate(pdf_labels)]
        return labels, "pdf-page-labels"
    # printed page numbers in headers/footers
    offsets: Counter = Counter()
    per_page: dict[int, int] = {}
    for p in pages:
        texts = [t.strip() for t in furniture_text.get(p.index, [])]
        # "12" or "Page 12"; else a running head with the number at one end ("12 BOOK TITLE", "Chapter Title 13"),
        # as scans read with OCR give them
        m = next((m for t in texts if (m := re.fullmatch(r"(?:page\s*)?(\d{1,4})", t, re.I))), None) or \
            next((m for t in texts if (m := re.fullmatch(r"(\d{1,4})\s+[^\d\s].{0,58}", t) or
                                       re.fullmatch(r".{0,58}[^\d\s]\s+(\d{1,4})", t))), None)
        if m:
            per_page[p.index] = int(m.group(1))
            offsets[int(m.group(1)) - p.index] += 1
    if per_page:
        off, votes = offsets.most_common(1)[0]
        if votes >= max(3, 0.5 * len(per_page)):
            labels = []
            for p in pages:
                n = p.index + off
                labels.append(str(n) if n >= 1 else roman(p.index + 1))
            if len(set(labels)) == len(labels):
                return labels, "printed-page-numbers"
    return [str(p.index + 1) for p in pages], "pdf-index"


# ============================================================================ paragraphs

# Chinese, Japanese and Thai-like scripts put no spaces between words, so a line break is not a space
_NO_SPACE_JOIN = re.compile(r"[　-ヿ㐀-䶿一-鿿豈-﫿＀-￯"
                            r"฀-໿က-႟ក-៿]")


def _dehyphen_join(a: str, b: str, vocab: Counter) -> str:
    if a.endswith("­"):           # a soft hyphen: the word goes on in the next line
        return a[:-1] + b
    if (a and _NO_SPACE_JOIN.match(a[-1])) or (b and _NO_SPACE_JOIN.match(b[0])):
        return a + b
    m = re.search(r"(\w+)-$", a)
    n = re.match(r"^(\w+)", b)
    if m and n and m.group(1)[-1:].islower() and n.group(1)[:1].islower():
        joined = (m.group(1) + n.group(1)).casefold()
        hyph = (m.group(1) + "-" + n.group(1)).casefold()
        if vocab[joined] >= vocab[hyph]:
            return a[:-1] + b
        return a + b
    if m and n:
        return a + b                   # a real hyphen at the line end: "SI-" + "Einheit" -> "SI-Einheit"
    return a + " " + b


def _build_paragraphs(pe: PageExtract, skip: set[int], vocab: Counter, body_size: float) -> list[dict]:
    lines = [l for i, l in enumerate(pe.lines) if i not in skip]
    if not lines:
        return []
    pitches = [lines[i + 1]["y0"] - lines[i]["y0"] for i in range(len(lines) - 1)
               if abs(lines[i + 1]["size"] - lines[i]["size"]) < 0.5 and 0 < lines[i + 1]["y0"] - lines[i]["y0"] < 40]
    med_pitch = statistics.median(pitches) if pitches else 1.3 * body_size
    right_edge = max(l["x1"] for l in lines)
    paras: list[dict] = []
    cur: dict | None = None

    def box_of(l: dict) -> int:
        cy = (l["y0"] + l["y1"]) / 2
        for bi, b in enumerate(pe.boxes):
            if b[0] - 2 <= l["x0"] and l["x1"] <= b[2] + 2 and b[1] - 2 <= cy <= b[3] + 2:
                return bi
        return -1

    prev = None
    for l in lines:
        text = l["text"]
        full_bold = bool(l["bold"]) and sum(b - a for a, b in l["bold"]) >= 0.8 * len(text.replace(" ", ""))
        short = word_count(text) <= 14
        # a line that ends a sentence is the end of a paragraph, not a heading (headings may end in "?", "？")
        sentence_end = text.endswith("。") or (word_count(text) >= 8 and text.endswith("."))
        heading_like = short and not sentence_end and (full_bold or l["size"] >= body_size * 1.15)
        bx = box_of(l)
        start_new = cur is None or bool(l.get("para_start"))     # text/Markdown input marks paragraphs explicitly
        if cur is not None and prev is not None and not start_new:
            pitch = l["y0"] - prev["y0"]
            formula_like = lambda t: "=" in t and len(t.split()) <= 12 and len(t) < 80
            eq_line = bool(EQ_NUM_RE.search(text)) or (
                _is_math_line(text) and len(text) < 70 and
                (l["x0"] > cur["x0"] + 3 * l["size"] or prev["text"].rstrip().endswith(":"))) or (
                formula_like(text) and formula_like(cur["text"]))
            # the second line of a wrapped CJK heading (OCR sizes of the two lines can differ a lot)
            wrapped_heading = (cur["heading"] and heading_like and abs(l["size"] - cur["size"]) <= 0.35 * cur["size"]
                               and 0 < pitch <= 2.2 * max(l["size"], cur["size"]) and len(text) <= 16
                               and _NO_SPACE_JOIN.match(text[:1] or " ") and _NO_SPACE_JOIN.match(cur["text"][-1:] or " ")
                               and not re.search(r"[.。!?！？:：;；]$", cur["text"]) and word_count(cur["text"] + text) <= 24)
            # the second line of a wrapped heading in spaced scripts ("ELEMENTARY HOUSEHOLD" / "CHEMISTRY"): same
            # size, same case, aligned left or centred, and not a heading of its own kind
            if not wrapped_heading and cur["heading"] and heading_like and not _NO_SPACE_JOIN.match(text[:1] or " "):
                size = max(l["size"], cur["size"])
                aligned = (abs(l["x0"] - cur["x0"]) <= 2 * size or
                           abs((l["x0"] + l["x1"]) - (cur["x0"] + cur["x1"])) <= 4 * size)
                wrapped_heading = (abs(l["size"] - cur["size"]) <= 0.15 * cur["size"] and 0 < pitch <= 2.0 * size
                                   and aligned and cur["text"].isupper() == text.isupper()
                                   and not re.search(r"[.!?:;]$", cur["text"])
                                   and word_count(cur["text"] + " " + text) <= 14
                                   and not CHAPTER_LABEL.match(cur["text"])
                                   and not any(r.match(text) for r in (SECTION_NUM, CHAPTER_LABEL, END_MATTER,
                                                                       CAPTION_RE, _OWN_HEADS)))
            if wrapped_heading:
                start_new = False
            elif abs(l["size"] - cur["size"]) > 0.08 * cur["size"] and not re.fullmatch(r".{0,3}", text):
                start_new = True
            elif cur["heading"] or heading_like:
                start_new = True
            elif pitch > max(1.35 * med_pitch, med_pitch + 0.45 * l["size"]) or pitch < -2:
                start_new = True
            elif BULLET_SYM_RE.match(text) or CAPTION_RE.match(text) or (
                    ENUM_RE.match(text) and (re.search(r"[.:;?!]$", prev["text"].rstrip()) or ENUM_RE.match(cur["text"]))):
                start_new = True
            elif bx != cur["box"]:
                start_new = True
            elif l["x0"] > prev["x0"] + 1.2 * l["size"] and not (prev["x1"] > right_edge - 3 * l["size"]):
                start_new = True
            elif prev["x1"] < right_edge - 4 * l["size"] and re.search(r"[.:!?)\]。！？：」』）।؟]$", prev["text"]):
                start_new = True
            elif (l["bold"] and l["bold"][0][0] == 0 and not full_bold and pitch > 1.1 * med_pitch and
                  not (prev["bold"] and prev["bold"][-1][1] >= len(prev["text"]) - 1)):
                start_new = True       # glossary-style entries that begin with a bold term
            elif eq_line:
                start_new = True
            elif EQ_NUM_RE.search(cur["text"]):
                start_new = True
        if start_new:
            cur = {"y0": l["y0"], "y1": l["y1"], "x0": l["x0"], "x1": l["x1"], "size": l["size"], "text": text,
                   "bold": [list(r) for r in l["bold"]], "italic": [list(r) for r in l["italic"]],
                   "heading": bool(heading_like), "box": bx}
            paras.append(cur)
        else:
            base = cur["text"]
            joined = _dehyphen_join(base, text, vocab)
            offset = len(joined) - len(text)
            cur["text"] = joined
            cur["bold"].extend([[a + offset, b + offset] for a, b in l["bold"]])
            cur["italic"].extend([[a + offset, b + offset] for a, b in l["italic"]])
            cur["y1"] = max(cur["y1"], l["y1"])
            cur["x0"], cur["x1"] = min(cur["x0"], l["x0"]), max(cur["x1"], l["x1"])
        prev = l
    for p in paras:
        if p["text"].endswith("­"):                 # a soft hyphen with no line after it
            p["text"] = p["text"][:-1]
            n = len(p["text"])
            p["bold"] = [[a, min(b, n)] for a, b in p["bold"] if a < n]
            p["italic"] = [[a, min(b, n)] for a, b in p["italic"] if a < n]
        # merge bold ranges separated only by whitespace (a bold term wrapped across lines)
        merged: list[list[int]] = []
        for a, b in sorted(p["bold"]):
            if merged and not p["text"][merged[-1][1]:a].strip():
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        p["bold"] = merged
        p["caption"] = bool(CAPTION_RE.match(p["text"]))
        words = len(p["text"].split())
        p["math"] = bool(EQ_NUM_RE.search(p["text"])) or (
            "=" in p["text"] and words <= 12 and sum(1 for c in p["text"] if c in MATH_CHARS) >= 2)
        for k in ("y0", "y1", "x0", "x1"):
            p[k] = round(p[k], 1)
    return paras


# ============================================================================ quality flags

# Scripts where a word never contains Latin letters: Latin letters inside such words mean the PDF's text layer
# maps glyphs to the wrong characters (common in Arabic and Indic PDFs)
_COMPLEX_SCRIPT = re.compile("[\u0590-\u05ff\u0600-\u06ff\u0750-\u077f\u0900-\u0dff\u0e00-\u0eff"
                             "\u0f00-\u0fff\u1000-\u109f\u1780-\u17ff\ufb1d-\ufdff\ufe70-\ufeff]")
_LATINISH = re.compile("[A-Za-z\u00c0-\u02af\u1e00-\u1eff]")


def garble_ratio(text: str) -> float:
    """How broken a text layer looks (0 = fine, above 0.01 = garbled): replacement characters, private-use
    glyph codes, control characters, (cid:NN) codes, and Latin letters inside Arabic, Hebrew or Indic words."""
    if not text:
        return 0.0
    # Only codes inside words count: a lone unmapped symbol ("\ufffd : sum") and the bracket pieces of Adobe's Symbol
    # font (U+F8E5-F8FF, used for big matrix brackets) are maths typesetting, not a broken text layer.
    bad = 0
    for i, c in enumerate(text):
        if c == "\ufffd" or ("\ue000" <= c <= "\uf8ff" and not "\uf8e5" <= c <= "\uf8ff"):
            near = text[max(0, i - 1):i] + text[i + 1:i + 2]
            if re.search(r"[^\W\d_]", near):
                bad += 1
        elif ord(c) < 32 and c not in "\n\t\r":
            bad += 1
    ratio = bad / len(text)
    if "(cid:" in text:
        ratio = max(ratio, 0.05)
    words = [w for w in text.split() if _COMPLEX_SCRIPT.search(w)]
    if len(words) >= 8:
        mixed = sum(1 for w in words if _LATINISH.search(w))
        ratio = max(ratio, 0.5 * mixed / len(words))
    # Chinese or Cyrillic text decoded with the wrong code page comes out as Latin-1 letters ("ÄÜÁ¿", "Ýíåðãèÿ"):
    # no language writes a third of its letters with them (French and German stay under 10%)
    letters = [c for c in text if c.isalpha()]
    if len(letters) >= 40:
        latin1 = sum(1 for c in letters if "À" <= c <= "ÿ")
        if latin1 > 0.3 * len(letters):
            ratio = max(ratio, 0.5 * latin1 / len(letters))
    return ratio


def _quality(pe: PageExtract, paras: list[dict]) -> list[str]:
    flags = []
    text = "\n".join(p["text"] for p in paras)
    chars = len(re.sub(r"\s", "", text))
    area = pe.width * pe.height
    if chars < 30 and pe.image_area > 0.45 * area:
        flags.append("scanned-no-text")
    elif chars < 30:
        flags.append("blank")
    if text and garble_ratio(text) > 0.01:
        flags.append("garbled")
    formula_lines = [p for p in paras if p.get("math")]
    scripts = len(re.findall(r"[_^](?:\{[^}]*\}|\w)", text))
    if len(formula_lines) >= 3 or scripts >= 6 or (paras and len(formula_lines) / len(paras) > 0.35 and len(formula_lines) >= 2):
        flags.append("math-heavy")
    if pe.two_column:
        flags.append("two-column")
    if pe.ocr:
        flags.append("ocr")
    if pe.error:
        flags.append("extraction-error")
    return flags


# ============================================================================ footnotes

_FOOTNOTE_MARK = re.compile(r"^\s*(?:[①-⑳㉑-㉟⑴-⒇❶-❿*†‡§]|\[\d{1,3}\]|\d{1,3}(?:\s|\.\s|\)\s)\S)")
# what a footnote cites: a book in 《》 with pages, publisher or year; "p. 23", "Press", "(2005)" ...
_REFERENCE = re.compile(r"《[^》]{2,}》[^。]*?(?:\d+\s*页|出版社|\d{4})|(?:\bpp?\.\s*\d+|\bPress\b|\bVerlag\b|\bHrsg\.|"
                        r"\bed\.\s|\bISBN\b|\(\d{4}\)|S\.\s*\d+|\bibid\b|\bvgl\.\s)", re.I)


def _mark_footnotes(pe: PageExtract, paras: list[dict], body_size: float) -> None:
    """Footnotes sit at the foot of a page, after the text. They are marked so that a sentence running on to
    the next page can be quoted across the page break (the footnotes are between its two halves) and so that
    writers see where the text stops. On OCR pages sizes say nothing, so a footnote needs a reference in it;
    in text layers it is set smaller than the text."""
    zone = 0.7 * pe.height
    tail = []
    for p in reversed(paras):
        if p["y0"] < zone or p["heading"] or p.get("caption") or p.get("in_figure"):
            break
        tail.append(p)
    found = False
    for p in reversed(tail):                 # top to bottom
        small = p["size"] <= 0.92 * body_size
        ref = bool(_REFERENCE.search(p["text"]))
        mark = bool(_FOOTNOTE_MARK.match(p["text"]))
        if found or (ref and (mark or small or pe.ocr)) or (small and mark and not pe.ocr):
            p["footnote"] = True
            found = True


# ============================================================================ figures

def _figures(pages: list[PageExtract], page_paras: list[list[dict]], labels: list[str]) -> list[dict]:
    """Find figures and tables by their captions. Only the crop rectangle is recorded here; the picture itself
    is made later, for the chapters that are actually studied (media.ensure_chapter_media)."""
    out = []
    seen: set[str] = set()
    for pe, paras in zip(pages, page_paras):
        for p in paras:
            m = CAPTION_RE.match(p["text"])
            if not m:
                continue
            kind = "table" if L.is_table_word(m.group("kind")) else "figure"
            num = m.group("num").replace("–", "-")
            fid = ("TAB-" if kind == "table" else "FIG-") + num
            if fid in seen:       # a caption mentioned twice (e.g. in a list of figures)
                continue
            cap_top, cap_bottom = p["y0"], p["y1"]
            region = None
            method = ""
            if kind == "figure":
                cands = [r for r in pe.images + pe.drawings if r[3] <= cap_top + 4 and r[3] >= cap_top - 260 and
                         (r[2] - r[0]) * (r[3] - r[1]) > 200]
                cands = [r for r in cands if not any(abs(r[0] - b[0]) < 1 and abs(r[1] - b[1]) < 1 for b in pe.boxes)]
                if cands:
                    x0 = min(r[0] for r in cands); y0 = min(r[1] for r in cands)
                    x1 = max(r[2] for r in cands); y1 = max(r[3] for r in cands)
                    # stop at body text above the figure
                    above = [q for q in paras if q["y1"] <= y0 + 2 and not q["caption"]]
                    region = [x0, y0, x1, y1]
                    method = "image" if any(r in pe.images for r in cands) else "vector"
                    # include label text sitting inside the region
                    for q in paras:
                        if q["y0"] >= y0 - 2 and q["y1"] <= y1 + 2 and len(q["text"]) < 40:
                            region = [min(region[0], q["x0"]), region[1], max(region[2], q["x1"]), region[3]]
                    if above:
                        region[1] = max(region[1], max(q["y1"] for q in above) + 1)
                if region is None:
                    above = [q for q in paras if q["y1"] <= cap_top and not q["caption"]]
                    top = max((q["y1"] for q in above), default=pe.height * 0.08)
                    if cap_top - top > 40:
                        region = [min(q["x0"] for q in paras), top + 2, max(q["x1"] for q in paras), cap_top - 2]
                        method = "gap-above-caption"
            else:  # table: caption above the table; take following short lines
                below = sorted([q for q in paras if q["y0"] >= cap_bottom - 1], key=lambda q: q["y0"])
                y1 = cap_bottom
                for q in below:
                    if q["y0"] - y1 > 18 or len(q["text"]) > 160 or q["heading"] and len(q["text"]) > 60:
                        break
                    y1 = q["y1"]
                if y1 > cap_bottom + 10:
                    region = [p["x0"], cap_top, max([p["x1"]] + [q["x1"] for q in below if q["y1"] <= y1]), y1]
                    method = "table-lines"
            record = {"id": fid, "kind": kind, "number": num, "page_index": pe.index, "page": labels[pe.index],
                      "caption": p["text"], "bbox": [round(v, 1) for v in region] if region else None,
                      "image": None, "method": method or "caption-only"}
            if region:
                pad = 6
                bottom = region[3] if kind == "table" else max(region[3], cap_bottom)
                record["crop"] = [round(max(0.0, region[0] - pad), 1), round(max(0.0, region[1] - pad), 1),
                                  round(min(pe.width, region[2] + pad), 1), round(min(pe.height, bottom + pad), 1)]
            seen.add(fid)
            out.append(record)
    return out


# ============================================================================ outline

def _find_heading_y(paras: list[dict], title: str) -> float | None:
    tkey = key_of(title)
    if not tkey:
        return None
    best = None
    for p in paras:
        pkey = key_of(p["text"])
        if pkey.startswith(tkey[: max(6, min(len(tkey), 40))]) or (tkey and tkey in pkey and len(pkey) < len(tkey) + 30):
            if best is None or p["heading"]:
                best = p["y0"]
                if p["heading"]:
                    break
    return best


def _chapter_number(title: str) -> str | None:
    m = CHAPTER_TITLE.match(title.strip())
    if not m:
        return None
    num = next((m.group(g) for g in "abcdef" if m.group(g)), None)
    return _roman_value(_cn_numeral(num)) if num else num


_ROMAN = re.compile(r"^(?=[MDCLXVI])M*(C[MD]|D?C{0,3})(X[CL]|L?X{0,3})(I[XV]|V?I{0,3})$", re.I)


def _roman_value(num: str) -> str:
    """Roman chapter numbers as digits (IV -> 4, xii -> 12); anything else is returned unchanged."""
    if not num or num.isdigit() or not _ROMAN.match(num):
        return num
    vals = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    total = 0
    for a, b in zip(num.lower(), num.lower()[1:] + " "):
        total += -vals[a] if b != " " and vals[b] > vals[a] else vals[a]
    return str(total) if 0 < total < 200 else num


def _cn_numeral(num: str) -> str:
    """Chinese numerals up to 99 as digits: 十二 -> 12, 三 -> 3 (other text is returned unchanged)."""
    cn = "零一二三四五六七八九"
    if num and len(num) <= 3 and all(c in cn + "十" for c in num):
        tens, ten, ones = num.partition("十")
        if ten and len(tens) <= 1 and len(ones) <= 1:
            return str((cn.index(tens) if tens else 1) * 10 + (cn.index(ones) if ones else 0))
        if not ten and len(num) == 1:
            return str(cn.index(num))
    return num


# Chinese / Japanese / Korean section headings: 第三节 ..., 第3節 ..., 제3절 ...
CJK_SECTION = re.compile(r"^(?:第\s*(?P<a>[\d一二三四五六七八九十]+)\s*[节節]|제\s*(?P<b>\d+)\s*절)\s*(?P<title>.*)$")


def _cjk_section(title: str) -> tuple[str, str] | None:
    m = CJK_SECTION.match(title.strip())
    if not m:
        return None
    return _cn_numeral(m.group("a") or m.group("b")), (m.group("title") or "").strip()


def toc_has_titles(toc: list) -> bool:
    """False for bookmark lists that only number the pages ("1", "2", ... as some scanning tools make them)."""
    if not toc:
        return False
    numeric = sum(1 for e in toc if re.fullmatch(r"\s*(?:(?:page|p\.?|第)\s*)?[\divxlcIVXLC]{1,5}\s*页?\s*",
                                                str(e[1]), re.I))
    return numeric < 0.5 * len(toc)


def _levels_from_titles(entries: list[dict]) -> list[dict]:
    """A one-level bookmark list whose titles say which entries are chapters ("Chapter 3", "第三章"): entries
    after a chapter title become its sections."""
    strong = [e for e in entries if CHAPTER_LABEL.match(e["title"].split()[0] if e["title"].split() else "") or
              re.match(r"^(?:第\s*[\d一-鿿]+\s*[章课課]|제\s*\d+\s*장)", e["title"]) or
              re.match(r"^(?:" + L.CHAPTER_WORD_ALT + r")\s+\d+", e["title"], re.I)]
    if len(strong) < 2:
        return entries
    seen_chapter = False
    for e in entries:
        if e in strong:
            e["level"], seen_chapter = 1, True
        elif seen_chapter and not OTHER_TITLES.match(e["title"]):
            e["level"] = 2
    return entries


def _strip_number(title: str) -> str:
    t = re.sub(r"^(?:" + L.CHAPTER_WORD_ALT + r")\s+" + _CH_NUM + r"(?![^\W\d_])[\s.:—–-]*", "", title.strip(), flags=re.I)
    t = re.sub(r"^(?:第\s*[\d一-鿿]+\s*[章课課]|제\s*\d+\s*장|(?:الفصل|الباب|الوحدة|अध्याय|इकाई)\s+\S+)[\s.:：—–-]*", "", t)
    t = re.sub(r"^\d+[\s.:]+", "", t)
    return t.strip() or title.strip()


def build_outline(toc: list, page_paras: list[list[dict]], labels: list[str], page_count: int,
                  scope_ranges: list[list[int]] | None = None, unread: set[int] | None = None,
                  lang: str | None = None) -> dict:
    """Chapters and sections from the PDF's bookmarks, else from headings, else fixed-size page parts.
    `unread`: scanned pages not read with OCR yet (they have no text; chapters guessed from headings stop before
    them)."""
    entries = []
    for e in toc:
        lvl, title, pno = e[0], str(e[1]).strip(), e[2]
        if pno is None or pno < 1:
            continue
        entries.append({"level": lvl, "title": title, "page": pno - 1})
    if not toc_has_titles(toc):
        entries = []                   # bookmarks that only number the pages carry no structure
    elif entries and len({e["level"] for e in entries}) == 1:
        entries = _levels_from_titles(entries)
    method = "toc"
    if not entries:
        entries = _headings_outline(page_paras)
        method = "headings" if entries else "fallback"
        if any(e["level"] == 1 and _chapter_number(e["title"]) for e in entries):
            # numbered chapters found: other big titles are book titles or noise, except known back/front matter
            entries = [e for e in entries if e["level"] != 1 or _chapter_number(e["title"]) or
                       OTHER_TITLES.match(e["title"])]
    if not entries:
        # no contents and no headings: fixed-size parts, only over the exam's pages when those are known
        ranges = scope_ranges or [[0, page_count - 1]]
        chapters = []
        for n, (a, b) in enumerate(ranges, start=1):
            title = "Whole book" if [a, b] == [0, page_count - 1] else f"Pages {labels[a]}-{labels[b]}"
            chapters.append({"id": f"ch{n:02d}", "number": str(n), "title": title, "kind": "chapter",
                             "start": {"page": a, "y": 0}, "end": {"page": b, "y": 1e9},
                             "sections": _fallback_sections(b - a + 1, start=a, labels=labels, prefix=str(n))})
        return {"method": "fallback", "confirmed": False, "needs_review": True, "chapters": chapters, "other": []}
    # choose chapter level: the shallowest level where titles look like chapters
    levels = sorted({e["level"] for e in entries})
    chap_level = levels[0]
    for lv in levels:
        at = [e for e in entries if e["level"] == lv]
        if sum(1 for e in at if _chapter_number(e["title"])) >= max(1, 0.4 * len(at)):
            chap_level = lv
            break
    chapters, other = [], []
    top_entries = [i for i, e in enumerate(entries) if e["level"] <= chap_level]
    # guessed from headings: once some chapter titles carry numbers, unnumbered big titles are book titles,
    # front matter or noise rather than chapters
    need_number = method == "headings" and any(_chapter_number(entries[i]["title"]) for i in top_entries)
    n_ch = 0
    for pos, i in enumerate(top_entries):
        e = entries[i]
        nxt = top_entries[pos + 1] if pos + 1 < len(top_entries) else None
        end_page = entries[nxt]["page"] if nxt is not None else page_count - 1
        end_y = None
        if nxt is not None:
            nt = entries[nxt]["title"]
            end_y = _find_heading_y(page_paras[end_page], nt)
            if end_y is None:
                ny = _find_heading_y(page_paras[end_page], _strip_number(nt))
                end_y = max(0, ny - 40) if ny is not None else None
        if nxt is not None and (end_y is None or end_y <= 60):
            end_page -= 1
            end_y = 1e9
        is_chapter = e["level"] == chap_level and (_chapter_number(e["title"]) or
                                                   (not need_number and not OTHER_TITLES.match(e["title"])))
        if not is_chapter:
            other.append({"title": e["title"], "start": {"page": e["page"], "y": 0},
                          "end": {"page": max(e["page"], end_page), "y": end_y if end_y is not None else 1e9}})
            continue
        n_ch += 1
        num = _chapter_number(e["title"]) or str(n_ch)
        cid = f"ch{int(num):02d}" if num.isdigit() else f"ch{n_ch:02d}"
        y = _find_heading_y(page_paras[e["page"]], _strip_number(e["title"])) or 0
        ch = {"id": cid, "number": num, "title": _strip_number(e["title"]), "kind": "chapter",
              "start": {"page": e["page"], "y": max(0, y - 40)},
              "end": {"page": max(e["page"], end_page), "y": end_y if end_y is not None else 1e9}, "sections": []}
        subs = [entries[j] for j in range(i + 1, nxt if nxt is not None else len(entries))
                if entries[j]["level"] == chap_level + 1]
        ch["sections"] = _sections_for(ch, subs, page_paras, lang)
        chapters.append(ch)
    # unique chapter ids
    seen: Counter = Counter()
    for c in chapters:
        seen[c["id"]] += 1
        if seen[c["id"]] > 1:
            c["id"] = f"{c['id']}-{seen[c['id']]}"
    if method == "headings" and unread:
        _clip_unread(chapters, other, unread, labels)
    return {"method": method, "confirmed": False, "needs_review": method != "toc", "chapters": chapters,
            "other": other}


def _clip_unread(chapters: list[dict], other: list[dict], unread: set[int], labels: list[str]) -> None:
    """A chapter guessed from headings ends at its last page that has text. Scanned pages after it that were not
    read yet hold no known text (the next chapter may start there), so they are listed apart as unread instead of
    being swallowed by the chapter: otherwise a scan read only for chapter 1 gets a chapter 1 that runs to the end
    of the book."""
    for ch in chapters:
        s, e = ch["start"]["page"], ch["end"]["page"]
        last = e
        while last > s and last in unread:
            last -= 1
        if e - last < 2:               # one blank or unread page at a chapter's end changes nothing
            continue
        other.append({"title": f"Pages {labels[last + 1]}-{labels[e]} (scanned, not read yet)", "unread": True,
                      "start": {"page": last + 1, "y": 0}, "end": {"page": e, "y": 1e9}})
        ch["end"] = {"page": last, "y": 1e9}
        ch["sections"] = [x for x in ch["sections"] if x["start"]["page"] <= last] or ch["sections"][:1]
        for x in ch["sections"]:
            if x["end"]["page"] > last:
                x["end"] = {"page": last, "y": 1e9}
    other.sort(key=lambda o: (o["start"]["page"], o["start"]["y"]))


def _sections_for(ch: dict, subs: list[dict], page_paras: list[list[dict]], lang: str | None = None) -> list[dict]:
    secs = []
    n_other = 0
    for e in subs:
        m = SECTION_NUM.match(e["title"])
        cjk = _cjk_section(e["title"])
        if m:
            sid, title, kind = m.group("num"), m.group("title").strip(), "content"
        elif cjk and ch["number"].isdigit() and cjk[0].isdigit():     # 第三节 ... in chapter 2 -> section 2.3
            sid, title, kind = f"{ch['number']}.{cjk[0]}", cjk[1] or e["title"], "content"
        elif END_MATTER.match(e["title"]):
            n_other += 1
            sid, title, kind = f"{ch['id']}-end{n_other}", e["title"], "end"
        elif OTHER_TITLES.match(e["title"]):     # contents, preface, imprint ... inside a chapter: not study matter
            n_other += 1
            sid, title, kind = f"{ch['id']}-x{n_other}", e["title"], "other"
        else:
            n_other += 1
            sid, title, kind = f"{ch['id']}-s{n_other}", e["title"], "content"
        y = _find_heading_y(page_paras[e["page"]], e["title"])
        if y is None:
            y = _find_heading_y(page_paras[e["page"]], title)
        secs.append({"id": sid, "title": title, "kind": kind, "start": {"page": e["page"], "y": y if y is not None else 0}})
    # intro section if there is body text between the chapter start and the first section
    if secs and L.is_introduction(secs[0]["title"]) and secs[0]["kind"] == "content":
        secs[0]["start"] = dict(ch["start"])       # the book's own introduction also takes the chapter's opening page
    elif secs:
        first = secs[0]["start"]
        if (first["page"], first["y"]) > (ch["start"]["page"], ch["start"]["y"] + 120):
            intro_text = _span_text(page_paras, ch["start"], first)
            if len(intro_text) > 350:
                secs.insert(0, {"id": f"{ch['number']}.0" if ch["number"].isdigit() else f"{ch['id']}-intro",
                                "title": L.introduction(lang), "kind": "content", "start": dict(ch["start"])})
    else:
        secs = [{"id": f"{ch['number']}.0" if ch["number"].isdigit() else f"{ch['id']}-all", "title": ch["title"],
                 "kind": "content", "start": dict(ch["start"])}]
    for i, s in enumerate(secs):
        s["end"] = dict(secs[i + 1]["start"]) if i + 1 < len(secs) else dict(ch["end"])
    # unique ids
    seen: Counter = Counter()
    for s in secs:
        seen[s["id"]] += 1
        if seen[s["id"]] > 1:
            s["id"] = f"{s['id']}-{seen[s['id']]}"
    return secs


# a word of at least three letters, or two CJK / Hangul characters: what every real title has
_REAL_WORD = re.compile(r"[^\W\d_]{3,}|[぀-ヿ㐀-鿿가-힯]{2,}")


def _headings_outline(page_paras: list[list[dict]]) -> list[dict]:
    sizes = Counter()
    for paras in page_paras:
        for p in paras:
            sizes[p["size"]] += len(p["text"])
    if not sizes:
        return []
    body = sizes.most_common(1)[0][0]
    entries = []
    entry = re.compile(r"^(?:第\s*[\d一二三四五六七八九十]+\s*[章节節]|(?:" + L.CHAPTER_WORD_ALT + r")\s+" + _CH_NUM +
                       r"(?![^\W\d_])|\d+(?:\.\d+)+\.?\s+\S)", re.I)
    for pno, paras in enumerate(page_paras):
        # a table-of-contents page: its entries are not the headings themselves. Contents entries start their
        # lines and fill the page, or end in page numbers; a chapter's first page with its sections and a
        # "Figure 1.1" caption is not one.
        entries_here = [p for p in paras if entry.match(p["text"].strip())]
        with_pages = [p for p in entries_here if re.search(r"(?:\.{2,}|…|\s)\s*[(（]?\d{1,4}[)）]?\s*$", p["text"])]
        if len(entries_here) >= 4 and (len(entries_here) >= 0.6 * len(paras) or len(with_pages) >= 3):
            continue
        # A "Chapter 3" line printed above the chapter title. It stands for the chapter alone when it is big, or
        # when it opens the page as a heading of its own (OCR sometimes loses the big title under it); a small
        # "Chapter 3" inside the page is a cross-reference.
        label = None
        for i, p in enumerate(paras):
            t = p["text"].strip()
            if len(t) > 90:
                continue
            if label and p["size"] < 0.85 * body and len(t) <= 12:
                continue         # specks and ornaments read by OCR between "Chapter 3" and its title
            m_end = re.match(r"^(.{2,40}?)\s*(第\s*[\d一-鿿]+\s*[章课課])$", t)
            if m_end:                            # a chapter title printed before its number
                t = f"{m_end.group(2)} {m_end.group(1)}"
            if p["heading"] and (SECTION_NUM.match(t) or (_cjk_section(t) and len(t) <= 40)):
                if label and label["alone"]:
                    entries.append({"level": 1, "title": label["text"], "page": pno})
                entries.append({"level": 2, "title": t, "page": pno})     # numbered sections are never chapters
                label = None
                continue
            if CHAPTER_LABEL.match(t) and (p["heading"] or p["size"] >= body * 1.15):
                if label and label["alone"]:
                    entries.append({"level": 1, "title": label["text"], "page": pno})
                label = {"text": t, "size": p["size"], "alone": p["size"] >= body * 1.3 or (p["heading"] and i <= 1)}
                continue
            big = p["size"] >= body * 1.45 and (_chapter_number(t) or p["heading"])
            # old and scanned books set the title under "CHAPTER 3" in plain capitals of the body size (OCR may
            # read a capital or two as small letters: "THE LAW OF DEFm1TE PROPORTIONS")
            cased = [c for c in t if c.isalpha() and c.lower() != c.upper()]
            caps_title = (len(cased) >= 2 and sum(c.isupper() for c in cased) >= 0.85 * len(cased) and
                          2 <= len(t) <= 80 and word_count(t) <= 12 and
                          not re.search(r"[.,;:]$", t) and not SECTION_NUM.match(t))
            titled = _REAL_WORD.search(t) is not None           # "a e", "2 e": OCR noise, not a title
            if label and titled and (big or (p["heading"] and p["size"] >= body * 1.25) or caps_title):
                entries.append({"level": 1, "title": f"{label['text']} {t}", "page": pno})
                label = None
                continue
            if label and not titled and len(t) <= 12:
                continue
            if label and label["alone"]:
                entries.append({"level": 1, "title": label["text"], "page": pno})
            label = None
            letters = sum(1 for c in t if c.isalpha())
            wordy = titled and (bool(_chapter_number(t)) or letters >= 0.6 * len(t.replace(" ", "")))
            if big and wordy:        # drop caps, figure lettering and OCR noise are not titles
                entries.append({"level": 1, "title": t, "page": pno, "size": p["size"]})
            elif p["heading"] and (SECTION_NUM.match(t) or (_cjk_section(t) and len(t) <= 40) or
                                   (END_MATTER.match(t) and len(t) <= 40 and p["size"] >= body * 1.05)):
                entries.append({"level": 2, "title": t, "page": pno})
        if label and label["alone"]:
            entries.append({"level": 1, "title": label["text"], "page": pno})
    if not any(e["level"] == 1 for e in entries):
        return []
    _fix_misread_numerals(entries)
    _fix_repeated_numbers(entries, body)
    # A chapter number seen again later (answer keys, review parts) is not a new chapter; a section number seen
    # again (chapter summaries, review questions) or belonging to another chapter is not a new section.
    seen: set[str] = set()
    seen_sec: set[str] = set()
    cur = None
    out = []
    for e in entries:
        if e["level"] == 1:
            num = _chapter_number(e["title"])
            if num and num.lower() in seen:
                continue
            if num:
                seen.add(num.lower())
            cur = num
        else:
            m = SECTION_NUM.match(e["title"])
            cjk = _cjk_section(e["title"])
            if m:
                num = m.group("num")
                if num in seen_sec or (cur and cur.isdigit() and num.split(".")[0] != cur):
                    continue
                seen_sec.add(num)
            elif cjk:                  # 第三节: numbered within the current chapter; repeats are running headers
                num = f"{cur}.{cjk[0]}"
                if num in seen_sec:
                    continue
                seen_sec.add(num)
        out.append(e)
    return out


_LABEL_NUM = re.compile(r"^(?P<word>" + L.CHAPTER_WORD_ALT + r")\s+(?P<num>[IVXLC1l|]{1,7})(?![^\W\d_])(?P<rest>.*)$",
                        re.I)


def _fix_misread_numerals(entries: list[dict]) -> None:
    """OCR misreads the roman numerals of chapter labels: "CHAPTER 1V" for IV, "CHAPTER 11" / "111" for II / III.
    Tokens mixing roman letters with 1, l or | become roman; a run of ones becomes roman when the book numbers its
    chapters in roman, or when it follows the chapter before it (1, 11, 111: chapter 11 never follows chapter 1)."""
    found = [(e, _LABEL_NUM.match(e["title"])) for e in entries if e["level"] == 1]
    found = [(e, m) for e, m in found if m]
    roman_book = any(re.search(r"[VXLC]", m.group("num")) or re.fullmatch(r"I{2,3}", m.group("num"))
                     for _, m in found)
    prev = 0
    for e, m in found:
        tok = m.group("num")
        fixed = tok
        if re.search(r"[IVXLC]", tok) and re.search(r"[1l|]", tok):
            fixed = re.sub(r"[1l|]", "I", tok)
        elif re.fullmatch(r"1{2,4}", tok) and (roman_book or prev == len(tok) - 1):
            fixed = "I" * len(tok)
        if fixed != tok:
            e["title"] = f"{m.group('word')} {fixed}{m.group('rest')}"
        num = _chapter_number(e["title"])
        prev = int(num) if num and num.isdigit() else prev


def _fix_repeated_numbers(entries: list[dict], body: float) -> None:
    """OCR misreads chapter numbers in big display type (第二章 read as 第一章). A big chapter title that repeats the
    number of the chapter just before it, with a different title, is the next chapter - unless that next number
    comes later anyway (then the repeat is a running head or an answer key and is dropped as before)."""
    import difflib
    level1 = [e for e in entries if e["level"] == 1]
    nums = [_chapter_number(e["title"]) for e in level1]
    prev_num, prev_title = None, ""
    for i, (e, num) in enumerate(zip(level1, nums)):
        if not num or not num.isdigit():
            continue
        title = _strip_number(e["title"])
        nxt = str(int(num) + 1)
        if (num == prev_num and e.get("size", 0) >= 1.45 * body and nxt not in nums[i + 1:] and
                difflib.SequenceMatcher(None, title, prev_title).ratio() < 0.6):
            e["title"] = f"第{nxt}章 {title}" if re.match(r"^第", e["title"]) else f"Chapter {nxt} {title}"
            num = nums[i] = nxt
        prev_num, prev_title = num, title


def _fallback_sections(page_count: int, per: int = 6, start: int = 0, labels: list[str] | None = None,
                       prefix: str = "1") -> list[dict]:
    secs = []
    last = start + page_count - 1
    lab = (lambda i: labels[i]) if labels else (lambda i: str(i + 1))
    for i, a in enumerate(range(start, last + 1, per)):
        b = min(last, a + per - 1)
        secs.append({"id": f"{prefix}.{i + 1}", "title": f"Pages {lab(a)}-{lab(b)}",
                     "kind": "content", "start": {"page": a, "y": 0},
                     "end": {"page": b + 1, "y": 0} if b < last else {"page": b, "y": 1e9}})
    return secs


def _span_text(page_paras: list[list[dict]], start: dict, end: dict) -> str:
    out = []
    for pno in range(start["page"], end["page"] + 1):
        for p in page_paras[pno]:
            if (pno, p["y0"]) >= (start["page"], start["y"]) and (pno, p["y0"]) < (end["page"], end["y"]):
                out.append(p["text"])
    return "\n".join(out)


# ============================================================================ text / markdown input

MD_PAGE_MARK = re.compile(r"^\s*(?:<!--\s*page\s+(?P<a>[\w.\-]+)\s*-->|\{(?P<b>\d+)\}-{6,}|={3,}\s*PAGE\s+(?P<c>[\w.\-]+)\s*={3,})\s*$",
                          re.I)


def _text_pages(path: Path) -> tuple[list[PageExtract], list[str], list]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    chunks: list[tuple[str, str]] = []
    cur_label, buf = None, []
    marked = False
    if "\f" in raw and not re.search(MD_PAGE_MARK.pattern, raw, re.I | re.M):
        # pdftotext output: one form feed after every page (splitlines() would silently drop them)
        parts = raw.split("\f")
        if parts and not parts[-1].strip():
            parts = parts[:-1]
        raw_lines: list[str] = []
        chunks = [(str(i + 1), p) for i, p in enumerate(parts)]
        marked = True
    else:
        raw_lines = raw.splitlines()
    for line in raw_lines:
        m = MD_PAGE_MARK.match(line)
        if not m and re.fullmatch(r"\s*<!--.*-->\s*", line):
            continue                          # other HTML comments (e.g. the header of an `extract` file)
        if m:
            marked = True
            if buf and "".join(buf).strip():
                chunks.append((cur_label, "\n".join(buf)))
            label = (m.group("a") or m.group("c")) if m else None
            if m and m.group("b") is not None:
                label = str(int(m.group("b")) + 1)   # Marker paginates from 0
            cur_label, buf = label, []
            continue
        buf.append(line)
    if buf and "".join(buf).strip():
        chunks.append((cur_label, "\n".join(buf)))
    if not marked:
        chunks = []
        text, acc = raw, []
        for para in re.split(r"\n\s*\n", text):
            acc.append(para)
            if sum(len(a) for a in acc) > 3000:
                chunks.append((None, "\n\n".join(acc)))
                acc = []
        if acc:
            chunks.append((None, "\n\n".join(acc)))
    pages, labels, toc = [], [], []
    for i, (label, body) in enumerate(chunks):
        pe = PageExtract(i, 612, 792)
        y = 40.0
        after_blank = True
        for line in body.splitlines():
            if not line.strip():
                y += 8
                after_blank = True
                continue
            size = 10.5
            hm = re.match(r"^(#{1,6})\s+(.*)$", line)
            text = line
            # display math from Marker/MinerU/Pandoc: "$$ v = d/t \quad (1.1) $$" or "$$ ... \tag{1.1} $$"
            dm = re.match(r"^\s*\$\$(.*)\$\$\s*$", text)
            if dm:
                inner = dm.group(1)
                inner = re.sub(r"\\tag\{([^}]*)\}", r" (\1)", inner)
                inner = re.sub(r"\\q?quad", " ", inner)
                text = re.sub(r"\s+", " ", inner).strip()
            if hm:
                lvl = len(hm.group(1))
                text = hm.group(2).strip()
                size = {1: 20, 2: 15, 3: 12.5}.get(lvl, 11.5)
                if lvl <= 2:
                    toc.append([lvl, text, i + 1])
            bold = []
            def repl(mm, acc=[]):
                return mm.group(1)
            # record **bold** ranges while stripping markers
            out, pos = "", 0
            for bm in re.finditer(r"\*\*(.+?)\*\*|__(.+?)__", text):
                out += text[pos:bm.start()]
                inner = bm.group(1) or bm.group(2)
                bold.append([len(out), len(out) + len(inner)])
                out += inner
                pos = bm.end()
            out += text[pos:]
            if hm:
                bold = [[0, len(out)]]
            out = fix_ligatures(out)
            pe.lines.append({"x0": 72.0, "x1": 72.0 + min(468, 5.5 * len(out)), "y0": y, "y1": y + size * 1.2,
                             "size": size, "text": out.strip(), "bold": bold, "italic": [],
                             "para_start": after_blank or bool(dm)})
            after_blank = bool(dm)       # a display equation is its own paragraph
            y += size * 1.4
        pages.append(pe)
        labels.append(label or str(i + 1))
    if len(set(labels)) != len(labels):
        labels = [str(i + 1) for i in range(len(pages))]
    return pages, labels, toc


# ============================================================================ main entry

# ============================================================================ OCR results (see ocr.py)

NEEDS_OCR = {"scanned-no-text", "garbled"}
# OCR engines put spaces between Chinese / Japanese characters; those scripts use none. (Not Hangul: Korean
# separates its words with spaces.)
CJK_CHARS = "぀-ヿ㐀-䶿一-鿿豈-﫿＀-￯　-〿"
_CJK_GAP = re.compile(f"(?<=[{CJK_CHARS}]) +(?=[{CJK_CHARS}])")
OCR_HEADING = re.compile(r"^(?:(?:" + L.CHAPTER_WORD_ALT + r")\s+(?:\d+|[ivxlc]+)(?![^\W\d_]).{0,80}|"
                         r"\d+(?:\.\d+)+\.?\s+[^\W\d_].{0,70}|第[\d一-鿿]+[章节節].{0,40}|제\s*\d+\s*[장절].{0,40})$",
                         re.I)


# a line that is nothing but an end-of-chapter or objectives heading ("Key Terms", "Résumé", "思考题")
_HEAD_LINE = re.compile(r"^(?:" + L._alt(L.SUMMARY + L.KEY_TERMS + L.KEY_EQUATIONS + L.EXERCISES + L.BACK_MATTER +
                                         L.OBJECTIVES) + r")\s*[:：]?$", re.I)


def ocr_cache_path(ws: Workspace, index: int) -> Path:
    return ws.source_dir / "ocr" / f"p{index + 1:04d}.json"


def _body_size(pages: list[PageExtract]) -> float | None:
    sizes: Counter = Counter()
    for pe in pages:
        for ln in pe.lines:
            sizes[ln["size"]] += len(ln["text"])
    return sizes.most_common(1)[0][0] if sizes and sum(sizes.values()) > 2000 else None


def _apply_ocr(ws: Workspace, pages: list[PageExtract]) -> int:
    """Use cached OCR lines (source/ocr/pNNNN.json) as the text of pages that were read with OCR.

    OCR gives no font sizes, bold or sub/superscripts. Sizes are rebuilt from line heights: lines of normal height
    get the body size, clearly taller lines (titles) a proportionally larger one. Short numbered lines that look like
    headings ("2.1 Heat", "Chapter 3 ...") are marked bold so paragraph and outline detection still work.
    """
    caches: dict[int, dict] = {}
    for pe in pages:
        path = ocr_cache_path(ws, pe.index)
        if path.exists():
            data = read_json(path, None)
            if data and abs(data.get("width", 0) - pe.width) < 2 and abs(data.get("height", 0) - pe.height) < 2:
                caches[pe.index] = data
    if not caches:
        return 0
    text_body = _body_size([pe for pe in pages if pe.index not in caches])
    heights = [l["y1"] - l["y0"] for d in caches.values() for l in d["lines"] if len(l["text"]) >= 25]
    median_h = statistics.median(heights) if heights else 10.0
    body = text_body or max(6.0, round(median_h / 0.9 * 2) / 2)
    for idx, data in caches.items():
        pe = pages[idx]
        raw = []
        for l in data["lines"]:
            text = _CJK_GAP.sub("", fix_ligatures(l["text"])).strip()
            if not text:
                continue
            ratio = (l["y1"] - l["y0"]) / median_h if median_h else 1.0
            size = body if 0.72 <= ratio <= 1.18 else round(body * ratio * 2) / 2
            span = {"text": text, "bbox": (l["x0"], l["y0"], l["x1"], l["y1"]), "size": size, "font": "", "flags": 0,
                    "ocr": True}
            raw.append({"x0": l["x0"], "x1": l["x1"], "y0": l["y0"], "y1": l["y1"], "size": size, "spans": [span]})
        pe.lines, pe.two_column = lines_from_raw(raw, pe.width)
        for ln in pe.lines:
            t = ln["text"]
            if len(t.split()) <= 12 and not re.search(r"[.,;:]$", t) and OCR_HEADING.match(t):
                ln["bold"] = [[0, len(t)]]
            elif _HEAD_LINE.match(t):
                # "Key Terms", "Summary", "Exercises", "Learning Objectives" set a little larger than the text:
                # OCR line heights hide that, so they are marked as headings by their words
                ln["bold"] = [[0, len(t)]]
                ln["size"] = max(ln["size"], round(body * 1.1 * 2) / 2)
        pe.ocr = True
        pe.error = ""
    return len(caches)


def _carry_scope(ws: Workspace, old: dict, new: dict, labels: list[str]) -> None:
    """The chapter list changed (e.g. OCR revealed headings): keep the exam scope by turning the old chapter
    choice into page ranges, and forget per-chapter progress that referred to the old chapters."""
    scope = ws.config.setdefault("scope", {})
    chosen = scope.get("chapters")
    if isinstance(chosen, list) and chosen and not scope.get("pages"):
        ranges = []
        for c in old["chapters"]:
            if c["id"] in chosen:
                ranges.append([c["start"]["page"], min(c["end"]["page"], len(labels) - 1)])
        if ranges:
            spec = ", ".join(f"{labels[a]}-{labels[b]}" for a, b in ranges)
            scope["pages"] = {"spec": spec, "ranges": ranges}
            scope["chapters"] = "all"
            ws.save_config()
    st = ws.state
    st["chapters"] = {}
    st["plan_confirmed"] = False
    st.pop("plan", None)
    # a guessed chapter list needs the user's OK; before the intake the intake questions already ask for it
    if new.get("method") in ("headings", "fallback") and (ws.config.get("intake") or {}).get("done"):
        st["outline_review"] = True
    ws.save_state()


def ingest(ws: Workspace, jobs: int | None = None, progress=None) -> dict:
    """Extract the whole book. Fast: no pictures are made here and OCR is a separate step (ocr.py) whose
    cached results are picked up on every run."""
    book = ws.root / ws.config["book"]["file"]
    if not book.exists():
        raise ESError(f"Book file not found: {book}")
    suffix = book.suffix.lower()
    is_pdf = suffix in PDF_LIKE
    n_ocr = 0
    reader = "pymupdf"
    if is_pdf and (pymupdf is None or os.environ.get("EXAMSCRIBE_PDF_READER") in ("pdfplumber", "pypdf")):
        if suffix != ".pdf":
            raise ESError(f"Reading {suffix} books needs PyMuPDF.", "Run: python -m pip install pymupdf")
        from .pdfread import available, read_pdf
        reader = available() or "none"
        pages, toc = read_pdf(book, progress)          # text layer without PyMuPDF (no pictures, no OCR)
        _drop_meaningless_bold(pages)
        n_ocr = _apply_ocr(ws, pages)
    elif is_pdf:
        doc = pymupdf.open(str(book))
        if doc.needs_pass:
            raise ESError("The PDF is password-protected.", "Ask the user for an unlocked copy of the book.")
        pages = extract_pages(book, doc, jobs=jobs, progress=progress)
        _drop_meaningless_bold(pages)
        n_ocr = _apply_ocr(ws, pages)
        toc = doc.get_toc(simple=True)
    elif suffix in TEXT_LIKE:
        pages, text_labels, toc = _text_pages(book)
    else:
        raise ESError(f"Unsupported book format: {suffix}",
                      "Supported: PDF, EPUB, MOBI, XPS, CBZ, TXT, Markdown. Convert other formats to PDF first.")

    # furniture
    furniture = _furniture_keys(pages) if is_pdf else set()
    furn_text: dict[int, list[str]] = {}
    for pidx, i in furniture:
        furn_text.setdefault(pidx, []).append(pages[pidx].lines[i]["text"])
    labels, label_method = _assign_labels(pages, furn_text) if is_pdf else (text_labels, "text-markers")

    # vocabulary for de-hyphenation
    vocab: Counter = Counter()
    for pe in pages:
        for ln in pe.lines:
            for w in re.findall(r"\w+(?:-\w+)*", ln["text"].casefold()):
                vocab[w] += 1
                if "-" in w:
                    for part in w.split("-"):
                        vocab[part] += 0
    sizes: Counter = Counter()
    for pe in pages:
        for ln in pe.lines:
            sizes[ln["size"]] += len(ln["text"])
    body_size = sizes.most_common(1)[0][0] if sizes else 10.5
    skip_lines: dict[int, set[int]] = {}
    for pidx, i in furniture:
        skip_lines.setdefault(pidx, set()).add(i)
    page_paras = [_build_paragraphs(pe, skip_lines.get(pe.index, set()), vocab, body_size) for pe in pages]

    figures = _figures(pages, page_paras, labels) if is_pdf else []
    # pictures made earlier (by media.py) stay valid for figures that are still found
    for f in figures:
        rel = f"source/figures/{f['id']}.png"
        if f.get("crop") and (ws.root / rel).exists():
            f["image"] = rel
    write_json(ws.source_dir / "figures.json", figures)
    # paragraphs that are labels inside a figure are kept for quote matching but hidden from task sources
    for f in figures:
        if f["kind"] != "figure" or not f.get("bbox"):
            continue
        x0, y0, x1, y1 = f["bbox"]
        for p in page_paras[f["page_index"]]:
            if not p["caption"] and p["x0"] >= x0 - 3 and p["x1"] <= x1 + 3 and p["y0"] >= y0 - 3 and p["y1"] <= y1 + 3:
                p["in_figure"] = f["id"]

    for pe, paras in zip(pages, page_paras):
        _mark_footnotes(pe, paras, body_size)

    quality = {}
    records = []
    for pe, paras, label in zip(pages, page_paras, labels):
        flags = _quality(pe, paras)
        if flags:
            quality[label] = flags
        records.append({"index": pe.index, "label": label, "width": round(pe.width, 1), "height": round(pe.height, 1),
                        "flags": flags, "two_column": pe.two_column, "boxes": pe.boxes,
                        "images": pe.images, "paras": paras,
                        # labels drawn inside figures are left out: writers never see them in the source files
                        "text": "\n\n".join(p["text"] for p in paras if not p.get("in_figure"))})
    write_jsonl(ws.pages_path, records)

    old = read_json(ws.outline_path, None)
    if old and old.get("method") == "manual":
        outline = old          # an outline the user supplied is never replaced by a guess
    else:
        unread = {r["index"] for r in records if set(r["flags"]) & NEEDS_OCR and "ocr" not in r["flags"]}
        outline = build_outline(toc, page_paras, labels, len(pages), _scope_ranges(ws, len(pages)), unread,
                                (ws.config.get("book") or {}).get("language"))
        sig = lambda o: [(c["id"], c["start"]["page"]) for c in o["chapters"]]
        same = bool(old) and sig(old) == sig(outline)
        # keep a previously confirmed outline if the chapter ids still match
        if same and old.get("confirmed"):
            outline["confirmed"] = True
        if old and not same:
            _carry_scope(ws, old, outline, labels)
        outline["label_method"] = label_method
        outline["body_size"] = body_size
        write_json(ws.outline_path, outline)

    needs_ocr = [label for label, fl in quality.items() if set(fl) & NEEDS_OCR]
    write_json(ws.quality_path, {"pages": quality, "label_method": label_method, "needs_ocr": needs_ocr,
                                 "ocr_pages": n_ocr, "reader": reader if is_pdf else "text"})
    ws.reload()
    summary = {
        "pages": len(pages),
        "label_method": label_method,
        "outline_method": outline["method"],
        "chapters": [{"id": c["id"], "title": c["title"],
                      "sections": len([s for s in c["sections"] if s["kind"] == "content"])} for c in outline["chapters"]],
        "figures": len(figures),
        "flagged_pages": {k: v for k, v in quality.items()},
        "needs_ocr": len(needs_ocr),
        "ocr_pages": n_ocr,
        "reader": reader if is_pdf else "text",
    }
    ws.state.setdefault("stages", {})["ingest"] = {"done": True, "summary": summary}
    ws.state["stages"].pop("inventory", None)
    ws.save_state()
    return summary


def _scope_ranges(ws: Workspace, n_pages: int) -> list[list[int]] | None:
    sp = (ws.config.get("scope") or {}).get("pages")
    if isinstance(sp, dict) and sp.get("ranges"):
        return [[max(0, a), min(n_pages - 1, b)] for a, b in sp["ranges"] if a <= b and a < n_pages]
    return None


# ============================================================================ section text for tasks

def section_paragraphs(ws: Workspace, sec: dict) -> list[tuple[dict, dict]]:
    """(page_record, paragraph) pairs inside a section's [start, end) range."""
    out = []
    s, e = sec["start"], sec["end"]
    for pno in range(s["page"], min(e["page"], len(ws.pages) - 1) + 1):
        page = ws.pages[pno]
        for p in page["paras"]:
            pos = (pno, p["y0"])
            if pos >= (s["page"], s["y"] - 1) and pos < (e["page"], e["y"] - 1):
                out.append((page, p))
    return out


def render_source(ws: Workspace, pairs: list[tuple[dict, dict]], header: str) -> str:
    figures: dict[int, list[dict]] = {}
    for f in read_json(ws.source_dir / "figures.json", []):
        figures.setdefault(f["page_index"], []).append(f)
    pairs = [(pg, p) for pg, p in pairs if not p.get("in_figure")]
    lines = [header, "Copy quotes EXACTLY from this text. A new page starts at each ======== PAGE n ======== marker.",
             "Cite a quote with the page number shown in the marker above it.", ""]
    cur_page = None
    in_box = -1
    in_notes = False
    for page, p in pairs:
        if page["index"] != cur_page:
            if in_box >= 0:
                lines.append("--- end box ---")
                in_box = -1
            cur_page = page["index"]
            in_notes = False
            lines.append("")
            flags = page.get("flags") or []
            note = f"   (extraction warning: {', '.join(flags)})" if flags and flags != ["two-column"] else ""
            lines.append(f"======== PAGE {page['label']} ========{note}")
            lines.append("")
        if p.get("footnote") and not in_notes:
            # the page's footnotes: a sentence cut off above them goes on at the top of the next page
            lines.append("--- footnotes of this page (the text above continues on the next page) ---")
            in_notes = True
        if p.get("box", -1) != in_box:
            if in_box >= 0:
                lines.append("--- end box ---")
            if p.get("box", -1) >= 0:
                lines.append("--- box ---")
            in_box = p.get("box", -1)
        lines.append(p["text"])
        if p.get("caption"):
            for f in figures.get(page["index"], []):
                if f["caption"] == p["text"] and f.get("image"):
                    lines.append(f"(image of this {f['kind']}: {f['image']})")
        lines.append("")
    if in_box >= 0:
        lines.append("--- end box ---")
    return "\n".join(lines).rstrip() + "\n"


def copy_book(src: Path, ws: Workspace) -> str:
    dest_dir = ws.source_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / ("book" + src.suffix.lower())
    if src.resolve() != dest.resolve():
        shutil.copyfile(src, dest)
    return f"source/{dest.name}"


def render_page_image(ws: Workspace, label: str, dpi: int = 130) -> Path:
    page = ws.page_by_label(label)
    if page is None:
        raise ESError(f"No page labeled '{label}'.")
    book = ws.root / ws.config["book"]["file"]
    if book.suffix.lower() not in PDF_LIKE:
        raise ESError("Page images are only available for PDF-like books.")
    doc = pymupdf.open(str(book))
    ws.page_images_dir.mkdir(parents=True, exist_ok=True)
    path = ws.page_images_dir / f"p{page['index'] + 1:04d}.png"
    doc[page["index"]].get_pixmap(dpi=dpi).save(str(path))
    return path


def write_text_file(path: Path, text: str) -> None:
    write_text(path, text)


__all__ = ["ingest", "section_paragraphs", "render_source", "copy_book", "render_page_image", "build_outline", "roman",
           "CAPTION_RE", "EQ_NUM_RE", "END_MATTER", "CLI"]
