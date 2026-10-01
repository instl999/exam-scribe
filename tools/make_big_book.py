"""Generate a large, realistic textbook PDF for performance testing (no download needed).

    python tools/make_big_book.py out.pdf [--chapters 40] [--pages-per-chapter 15] [--scanned 0]

Each chapter has sections with bold key terms, numbered equations, boxed notes, running headers and page
numbers, vector figures made of many small paths (like real textbook line art), raster figures, and end-of-
chapter summaries. --scanned N appends N image-only pages (to time OCR).
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import pymupdf

W, H = 612, 792
CSS = "* {font-family: sans-serif; font-size: 10.5pt; line-height: 1.32;} h1 {font-size: 22pt;} h2 {font-size: 14pt;} p {margin: 0 0 6px 0;}"
WORDS = ("energy heat system reaction pressure volume temperature molecule atom bond electron solution rate "
         "equilibrium entropy enthalpy mass charge field force motion wave light gas liquid solid acid base "
         "process change model property quantity measure value unit sample surface density current").split()


def sentence(rng: random.Random, n: int = 14) -> str:
    words = [rng.choice(WORDS) for _ in range(n)]
    return (" ".join(words)).capitalize() + "."


def paragraph(rng: random.Random, bold_term: str | None = None) -> str:
    s = " ".join(sentence(rng, rng.randint(10, 18)) for _ in range(rng.randint(3, 5)))
    if bold_term:
        s = f"<b>{bold_term}</b> is the {rng.choice(WORDS)} of a {rng.choice(WORDS)} in a {rng.choice(WORDS)}. " + s
    return f"<p>{s}</p>"


def vector_figure(page, rect, rng: random.Random, paths: int = 1500) -> None:
    shape = page.new_shape()
    for _ in range(paths):
        x = rect.x0 + rng.random() * rect.width
        y = rect.y0 + rng.random() * rect.height
        shape.draw_line((x, y), (x + rng.uniform(-8, 8), y + rng.uniform(-8, 8)))
    shape.finish(color=(0.2, 0.3, 0.6), width=0.4)
    shape.commit()


def build(out: Path, chapters: int, per_chapter: int, scanned: int, seed: int = 1) -> int:
    rng = random.Random(seed)
    doc = pymupdf.open()
    toc = []
    img_page = pymupdf.open().new_page(width=300, height=150)
    img_page.draw_rect(img_page.rect, color=None, fill=(0.9, 0.95, 1))
    for _ in range(40):
        img_page.draw_circle((rng.uniform(0, 300), rng.uniform(0, 150)), rng.uniform(4, 20), color=(0.3, 0.3, 0.7))
    raster = img_page.get_pixmap(dpi=120)
    term_n = 0
    for c in range(1, chapters + 1):
        for p in range(per_chapter):
            page = doc.new_page(width=W, height=H)
            label = len(doc)
            if p > 0:
                page.insert_text((72, 44), f"Chapter {c} | Topic {c}", fontsize=8.5, fontname="helv")
            page.insert_text((W / 2 - 6, 760), str(label), fontsize=9, fontname="helv")
            y = 72
            html = ""
            if p == 0:
                html += f"<h1>Chapter {c} Topic {c}</h1>"
                toc.append([1, f"{c} Topic {c}", label])
            if p % 4 == 0:
                sec = p // 4 + 1
                html += f"<h2>{c}.{sec} Section {c}.{sec}</h2>"
                toc.append([2, f"{c}.{sec} Section {c}.{sec}", label])
            term_n += 1
            html += paragraph(rng, f"term {term_n}")
            html += paragraph(rng)
            if p % 2 == 0:
                html += f"<p style='text-align:center'>q = m &times; c &times; &Delta;T + {rng.randint(2, 9)}x<sub>n</sub> &nbsp;&nbsp; ({c}.{p + 1})</p>"
            html += paragraph(rng)
            spare, _ = page.insert_htmlbox(pymupdf.Rect(72, y, 540, 460), html, css=CSS, scale_low=0.5)
            if p % 3 == 1:
                r = pymupdf.Rect(150, 470, 460, 660)
                vector_figure(page, r, rng)
                page.insert_htmlbox(pymupdf.Rect(72, 665, 540, 720),
                                    f"<p><b>Figure {c}.{p}</b> A diagram of {sentence(rng, 8)}</p>", css=CSS)
            elif p % 7 == 3:
                page.insert_image(pymupdf.Rect(156, 470, 456, 620), pixmap=raster)
                page.insert_htmlbox(pymupdf.Rect(72, 625, 540, 690),
                                    f"<p><b>Figure {c}.{p}</b> A photograph of {sentence(rng, 8)}</p>", css=CSS)
            elif p % 4 == 2:
                box = pymupdf.Rect(72, 480, 540, 600)
                page.draw_rect(box, color=(0.5, 0.6, 0.8), fill=(0.93, 0.95, 1.0))
                page.insert_htmlbox(box + (8, 8, -8, -8), paragraph(rng), css=CSS)
            else:
                page.insert_htmlbox(pymupdf.Rect(72, 470, 540, 720), paragraph(rng) + paragraph(rng), css=CSS)
        page = doc.new_page(width=W, height=H)
        page.insert_htmlbox(pymupdf.Rect(72, 72, 540, 720), "<h2>Summary</h2>" + paragraph(rng) + paragraph(rng), css=CSS)
        toc.append([2, "Summary", len(doc)])
    if scanned:
        src = doc[min(1, len(doc) - 1)]
        pix = src.get_pixmap(dpi=200)
        for _ in range(scanned):
            pg = doc.new_page(width=W, height=H)
            pg.insert_image(pg.rect, pixmap=pix)
        toc.append([1, "Scanned appendix", len(doc) - scanned + 1])
    doc.set_toc(toc)
    try:
        doc.subset_fonts()
    except Exception:
        pass
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out), garbage=4, deflate=True)
    return len(doc)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--chapters", type=int, default=40)
    ap.add_argument("--pages-per-chapter", type=int, default=15)
    ap.add_argument("--scanned", type=int, default=0)
    a = ap.parse_args()
    n = build(Path(a.out), a.chapters, a.pages_per_chapter, a.scanned)
    print(f"wrote {a.out}: {n} pages")
    sys.exit(0)
