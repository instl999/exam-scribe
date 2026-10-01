"""Look at a book file in a few seconds and report what it needs (text layer? OCR? contents?) and how long
processing will take, before any slow step starts."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

from .common import ESError
from .ingest import PDF_LIKE, TEXT_LIKE, _extract_pdf_page, garble_ratio, toc_has_titles

try:
    import pymupdf
except ImportError:  # pragma: no cover
    pymupdf = None


def _ranges(idx: list[int]) -> str:
    out, start, prev = [], None, None
    for i in idx:
        if start is None:
            start = prev = i
        elif i == prev + 1:
            prev = i
        else:
            out.append((start, prev))
            start = prev = i
    if start is not None:
        out.append((start, prev))
    return ", ".join(f"{a + 1}" if a == b else f"{a + 1}-{b + 1}" for a, b in out)


# very common words, to tell Latin-script languages apart
_STOPWORDS = {
    "en": "the of and is to in that are for with as by this from",
    "de": "der die das und ist nicht ein eine den mit von zu sich auf",
    "fr": "le la les des est et une dans du que pour sur au par",
    "es": "el la los las es y de que en un una del por con para",
    "it": "il la di che è e un una del della per con non sono gli",
    "pt": "o a os as de que é e um uma do da em para com não",
    "nl": "de het een en is van dat in op te zijn voor met niet",
    "pl": "i w się jest nie na z do że to jak od są przez",
    "tr": "ve bir bu için ile olarak da de en çok olan gibi",
    "id": "yang dan di dengan ini untuk dari dalam adalah pada",
    "vi": "của và là các có được trong cho những một không với",
}


def _guess_language(text: str) -> str | None:
    count = lambda rx: len(re.findall(rx, text))
    kana, hangul, han = count(r"[぀-ヿ]"), count(r"[가-힯]"), count(r"[一-鿿]")
    latin = count(r"[A-Za-zÀ-ɏḀ-ỿ]")
    scripts = {"ru": count(r"[Ѐ-ӿ]"), "el": count(r"[Ͱ-Ͽ]"), "ar": count(r"[؀-ۿ]"),
               "he": count(r"[֐-׿]"), "hi": count(r"[ऀ-ॿ]"), "th": count(r"[฀-๿]")}
    if kana > 0.1 * (han + 1) and kana + han > latin:
        return "ja"
    if hangul > latin:
        return "ko"
    if han > 0.5 * latin:
        return "zh" if not re.search(r"[們這個來說為與學體]", text) else "zh-tw"
    best = max(scripts, key=scripts.get)
    if scripts[best] > latin:
        return best
    if not latin:
        return None
    words = re.findall(r"[^\W\d_]+", text.casefold())[:20000]
    freq: dict[str, int] = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    scores = {lang: sum(freq.get(w, 0) for w in sw.split()) for lang, sw in _STOPWORDS.items()}
    return max(scores, key=scores.get) if max(scores.values()) else "en"


def probe_book(path: Path, lang: str | None = None, max_pages: int = 400, engines: bool = True) -> dict:
    if not path.exists():
        raise ESError(f"File not found: {path}")
    start = time.perf_counter()
    info: dict = {"name": path.name, "size_mb": round(path.stat().st_size / 1e6, 1)}
    suffix = path.suffix.lower()
    if suffix in TEXT_LIKE:
        text = path.read_text(encoding="utf-8", errors="replace")
        info.update(kind="text", chars=len(text), lang_guess=_guess_language(text[:200000]), need_ocr=0,
                    est_ingest=1 + len(text) / 2e6)
        return info
    if suffix not in PDF_LIKE:
        info["kind"] = "unsupported"
        return info
    if pymupdf is None:
        return _probe_without_pymupdf(path, info, lang, max_pages, start)
    doc = pymupdf.open(str(path))
    info["kind"] = "pdf" if suffix == ".pdf" else suffix.lstrip(".")
    if doc.needs_pass:
        info["encrypted"] = True
        return info
    n = doc.page_count
    idxs = list(range(n)) if n <= max_pages else sorted({round(i * (n - 1) / (max_pages - 1)) for i in range(max_pages)})
    counts = {"text": 0, "scan": 0, "garbled": 0, "blank": 0}
    need: list[int] = []
    sample_text = []
    for i in idxs:
        page = doc[i]
        t = page.get_text("text")
        chars = len("".join(t.split()))
        if chars >= 30:
            if garble_ratio(t) > 0.01:
                counts["garbled"] += 1
                need.append(i)
            else:
                counts["text"] += 1
                if len(sample_text) < 60:
                    sample_text.append(t)
        else:
            area = sum((r[2] - r[0]) * (r[3] - r[1]) for k, r in page.get_bboxlog() if k in ("fill-image", "fill-imgmask"))
            if area > 0.45 * abs(page.rect):
                counts["scan"] += 1
                need.append(i)
            else:
                counts["blank"] += 1
    factor = n / max(1, len(idxs))
    # time a few full extractions to estimate the whole run
    text_idx = [i for i in idxs if i not in set(need)]
    sample = text_idx[:: max(1, len(text_idx) // 8)][:8]
    t0 = time.perf_counter()
    for i in sample:
        _extract_pdf_page(doc[i])
    per_page = (time.perf_counter() - t0) / len(sample) if sample else 0.02
    cpus = os.cpu_count() or 1
    workers = min(cpus, 8) if n >= 400 and cpus >= 4 else 1
    est_ingest = 1.5 + n * (per_page + 0.004) / (0.6 * workers if workers > 1 else 1)
    toc = doc.get_toc(simple=True)
    top = min((e[0] for e in toc), default=1)
    guess = _guess_language("\n".join(sample_text)) if sum(len(t) for t in sample_text) > 200 else None
    if guess is None:          # a scan: the bookmarks, the title and the file name still show the language
        guess = _guess_language(" ".join(str(e[1]) for e in toc) + " " + ((doc.metadata or {}).get("title") or "")
                                + " " + path.stem)
    toc_useful = toc_has_titles(toc)
    info.update(pages=n, sampled=len(idxs) < n, text_pages=round(counts["text"] * factor),
                scanned_pages=round(counts["scan"] * factor), garbled_pages=round(counts["garbled"] * factor),
                blank_pages=round(counts["blank"] * factor), need_ocr=round(len(need) * factor),
                need_ocr_pages=_ranges(need) if len(idxs) == n else "", toc_entries=len(toc) if toc_useful else 0,
                toc_chapters=sum(1 for e in toc if e[0] == top), toc_page_numbers_only=bool(toc) and not toc_useful,
                page_labels=bool(doc.get_page_labels()),
                lang_guess=guess, est_ingest=round(est_ingest, 1), workers=workers)
    if engines and info["need_ocr"]:
        from .ocr import engine_report, pick_engine
        book_lang = lang or guess or "en"
        eng = pick_engine(None, book_lang=book_lang)
        info["ocr_lang"] = book_lang
        info["ocr_engine"] = f"{eng.name} ({eng.lang}, {eng.workers} workers)" if eng else None
        info["est_ocr_all"] = round(eng.estimate(info["need_ocr"]), 1) if eng else None
        info["est_ocr_100"] = round(eng.estimate(100), 1) if eng else None
        info["engines"] = engine_report(book_lang)
    info["probe_seconds"] = round(time.perf_counter() - start, 1)
    return info


def _probe_without_pymupdf(path: Path, info: dict, lang: str | None, max_pages: int, start: float) -> dict:
    """A slower, text-only check when PyMuPDF is missing (pypdf or pdfplumber)."""
    from .pdfread import available
    reader = available()
    if reader is None or path.suffix.lower() != ".pdf":
        raise ESError("No PDF reader is installed.", "Run: python -m pip install pymupdf")
    texts: list[str] = []
    if reader == "pypdf" or _importable("pypdf"):
        import pypdf
        r = pypdf.PdfReader(str(path))
        n = len(r.pages)
        idxs = list(range(n)) if n <= 60 else sorted({round(i * (n - 1) / 59) for i in range(60)})
        texts = [(r.pages[i].extract_text() or "") for i in idxs]
        toc = len(r.outline) if r.outline else 0
    else:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            n = len(pdf.pages)
            idxs = list(range(n)) if n <= 30 else sorted({round(i * (n - 1) / 29) for i in range(30)})
            texts = [(pdf.pages[i].extract_text() or "") for i in idxs]
        toc = 0
    no_text = sum(1 for t in texts if len("".join(t.split())) < 30)
    garbled = sum(1 for t in texts if len("".join(t.split())) >= 30 and garble_ratio(t) > 0.01)
    factor = n / max(1, len(idxs))
    per_page = 0.12 if reader == "pdfplumber" else 0.06
    # without PyMuPDF images cannot be seen: a few pages without text are title or blank pages, not scans
    blank = no_text if no_text <= 0.1 * len(idxs) else 0
    no_text -= blank
    info.update(kind="pdf", pages=n, sampled=len(idxs) < n, reader=reader,
                text_pages=round((len(idxs) - no_text - garbled - blank) * factor), scanned_pages=round(no_text * factor),
                garbled_pages=round(garbled * factor), blank_pages=round(blank * factor),
                need_ocr=round((no_text + garbled) * factor),
                need_ocr_pages="", toc_entries=toc, toc_chapters=toc, page_labels=False,
                lang_guess=_guess_language("\n".join(texts)), est_ingest=round(2 + n * per_page, 1), workers=1,
                probe_seconds=round(time.perf_counter() - start, 1))
    if info["need_ocr"]:
        info["ocr_engine"] = None
        info["ocr_lang"] = lang or info["lang_guess"] or "en"
        info["engines"] = [{"name": "PyMuPDF", "ok": False, "detail": "needed to render pages for OCR "
                                                                   "(python -m pip install pymupdf)"}]
    return info


def _importable(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def probe_text(info: dict) -> str:
    from .ocr import fmt_duration
    lines = [f"Book: {info['name']} ({info.get('pages', '?')} pages, {info['size_mb']} MB)"]
    if info.get("kind") == "unsupported":
        return lines[0] + "\nNot a supported format. Use PDF, EPUB, MOBI, XPS, CBZ, TXT or Markdown."
    if info.get("encrypted"):
        return lines[0] + "\nThe file is password-protected. Ask the user for an unlocked copy."
    if info.get("kind") == "text":
        return (f"Book: {info['name']} (plain text / Markdown, {info['chars']} characters)\n"
                "No OCR needed; extraction takes seconds.")
    n = info["pages"]
    approx = " (estimated from a sample)" if info.get("sampled") else ""
    lines.append(f"Text layer:   {info['text_pages']} of {n} pages have text{approx}")
    if info["scanned_pages"]:
        where = f" (PDF pages {info['need_ocr_pages']})" if info.get("need_ocr_pages") and info["scanned_pages"] < n else ""
        lines.append(f"Scans:        {info['scanned_pages']} pages are images without text{where}")
    if info["garbled_pages"]:
        lines.append(f"Broken text:  {info['garbled_pages']} pages have unusable characters (they are read with OCR)")
    if info.get("toc_page_numbers_only"):
        contents = "only page-number bookmarks (ignored; chapters are found from headings)"
    elif info["toc_entries"]:
        contents = f"yes ({info['toc_chapters']} top-level entries)"
    else:
        contents = "none in the file (chapters are guessed from headings)"
    lines.append(f"Contents:     {contents}   Page labels: {'yes' if info['page_labels'] else 'no'}")
    if info.get("lang_guess"):
        lines.append(f"Language:     looks like '{info['lang_guess']}' (init uses it unless --language is given)")
    lines.append(f"Extraction:   about {fmt_duration(info['est_ingest'])} for the whole book"
                 + (f" ({info['workers']} parallel workers)" if info["workers"] > 1 else "")
                 + (f" (PyMuPDF missing: reading with {info['reader']}, no figure pictures)" if info.get("reader") else ""))
    advice = []
    if info["need_ocr"]:
        if info.get("ocr_engine"):
            lines.append(f"OCR:          {info['need_ocr']} pages need OCR -> {info['ocr_engine']}: about "
                         f"{fmt_duration(info['est_ocr_all'])} for all of them, {fmt_duration(info['est_ocr_100'])} "
                         "per 100 pages")
            if info["est_ocr_all"] <= 150:
                advice.append("The scanned pages are read with OCR right after extraction (quick for this book).")
            else:
                advice.append("Only the pages on the exam are read with OCR (after the intake questions), so narrow "
                              "the scope to what the exam covers.")
        else:
            lines.append(f"OCR:          {info['need_ocr']} pages need OCR, but no OCR engine is available for "
                         f"'{info.get('ocr_lang')}':")
            for r in info.get("engines", []):
                lines.append(f"                {r['name']:<10} {r['detail']}")
            advice.append("Install an OCR engine (see above) or use a PDF that already has a text layer.")
        if not info["toc_entries"] and info["need_ocr"] > 0.5 * n:
            advice.append("There are no contents in the file: the user will be asked which pages the exam covers.")
    else:
        advice.append("No OCR needed. Extraction is fast; pictures are made only for the chapters you study.")
    advice.append("Never read the PDF yourself: the scripts extract it much faster and quotes are checked "
                  "against their text.")
    lines.append("Advice:       " + "\n              ".join(advice))
    return "\n".join(lines)
