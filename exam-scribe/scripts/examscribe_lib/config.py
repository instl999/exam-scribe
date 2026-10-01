"""Workspace creation and validated configuration (models change settings through commands, never by hand)."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from .common import CLI, ESError, Workspace, read_json, slugify, write_json
from .tiers import TIERS

FORMATS = ("mcq", "short-answer", "problems", "essay")
SUBJECTS = ("general", "math-physics", "chemistry", "biology-medicine", "history-social", "law", "computer-science",
            "economics-business", "languages")
POLICIES = ("closed", "open", "cheat-sheet")


def _date(v: str) -> str:
    try:
        return dt.date.fromisoformat(v.strip()).isoformat()
    except ValueError:
        raise ESError(f"'{v}' is not a date.", "Use the form YYYY-MM-DD, e.g. 2026-12-15.")


def _formats(v: str) -> list[str]:
    items = [x.strip().lower().replace("_", "-") for x in re.split(r"[,\s]+", v) if x.strip()]
    alias = {"multiple-choice": "mcq", "choice": "mcq", "short": "short-answer", "problem": "problems",
             "calculation": "problems", "calculations": "problems", "essays": "essay"}
    items = [alias.get(x, x) for x in items]
    bad = [x for x in items if x not in FORMATS]
    if bad or not items:
        raise ESError(f"Unknown exam format(s): {', '.join(bad) or '(none)'}.", f"Use a comma list of: {', '.join(FORMATS)}.")
    return items


def _enum(options: tuple[str, ...]):
    def f(v: str) -> str:
        v = v.strip().lower()
        if v not in options:
            raise ESError(f"'{v}' is not allowed.", f"Use one of: {', '.join(options)}.")
        return v
    return f


def _float(lo: float, hi: float):
    def f(v: str) -> float:
        try:
            x = float(v)
        except ValueError:
            raise ESError(f"'{v}' is not a number.")
        if not lo <= x <= hi:
            raise ESError(f"{x} is out of range ({lo}-{hi}).")
        return x
    return f


def _int(lo: int, hi: int):
    def f(v: str) -> int:
        try:
            x = int(v)
        except ValueError:
            raise ESError(f"'{v}' is not a whole number.")
        if not lo <= x <= hi:
            raise ESError(f"{x} is out of range ({lo}-{hi}).")
        return x
    return f


def _bool(v: str) -> bool:
    if v.strip().lower() in ("true", "yes", "1", "on"):
        return True
    if v.strip().lower() in ("false", "no", "0", "off"):
        return False
    raise ESError(f"'{v}' is not true/false.")


def _lang(v: str) -> str:
    v = v.strip().lower()
    if not re.fullmatch(r"[a-z]{2,3}(-[a-z0-9]{2,8})?", v):
        raise ESError(f"'{v}' is not a language code.", "Use codes like en, zh, es, de, ja, pt-br.")
    return v


def _scope(v: str):
    if v.strip().lower() in ("all", "*", ""):
        return "all"
    return [x.strip() for x in re.split(r"[,\s]+", v) if x.strip()]


def _text(v: str) -> str:
    return v.strip()


def _weekdays(v: str) -> list[str]:
    days = [x.strip().lower()[:3] for x in re.split(r"[,\s]+", v) if x.strip()]
    ok = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    bad = [d for d in days if d not in ok]
    if bad:
        raise ESError(f"Unknown day(s): {', '.join(bad)}.", "Use mon,tue,wed,thu,fri,sat,sun or 'none'.")
    return days


KEYS = {
    "title": (_text, "Course or book title shown on the study pages."),
    "tier": (_enum(tuple(TIERS)), "Model tier: strict (default), standard or frontier."),
    "subject": (_enum(SUBJECTS), "Subject profile: " + ", ".join(SUBJECTS)),
    "book.language": (_lang, "Language of the book, e.g. en."),
    "exam.date": (_date, "Exam date, YYYY-MM-DD."),
    "exam.formats": (_formats, "Question formats in the exam: " + ", ".join(FORMATS)),
    "exam.book_policy": (_enum(POLICIES), "closed, open, or cheat-sheet (one page of own notes allowed)."),
    "exam.duration_minutes": (_int(5, 600), "Exam length in minutes."),
    "exam.question_count": (_int(1, 300), "About how many questions the exam has."),
    "scope.chapters": (_scope, "Chapters in scope: 'all' or a list like ch01,ch02."),
    "scope.pages": (_text, "Pages on the exam, e.g. 45-120, 130-140 (printed page numbers, or PDF page numbers when "
                           "the book has none), or 'all'. Combines with scope.chapters."),
    "ocr.engine": (_enum(("auto", "windows", "tesseract", "rapidocr")),
                   "OCR engine for scanned pages: auto (fastest available), windows, tesseract or rapidocr."),
    "ocr.dpi": (_int(100, 600), "OCR resolution (default 200; try 300 for small print)."),
    "ocr.jobs": (_int(1, 32), "Parallel OCR workers (default: number of CPU cores, at most 8)."),
    "ocr.skip": (_bool, "true = go on without reading scanned pages (their content will be missing)."),
    "output.language": (_lang, "Language for the notes (quotes stay in the book's language)."),
    "study.hours_per_day": (_float(0.25, 16), "Hours per day available for study."),
    "study.start_date": (_date, "First study day (default: today)."),
    "study.rest_days": (lambda v: [] if v.strip().lower() in ("none", "") else _weekdays(v),
                        "Days off, e.g. sun, or none."),
    "checks.run_code": (_bool, "Run Python code in trace blocks to verify their output (true/false)."),
    "anki.include_unverified": (_bool, "Also put not-yet-verified cards in the Anki deck (true/false)."),
    "intake.done": (_bool, "Set to true after asking the user the intake questions."),
}

REQUIRED_INTAKE = ("exam.formats", "exam.book_policy", "scope.chapters", "study.hours_per_day", "subject")


def default_config(book_rel: str, title: str, tier: str, language: str) -> dict:
    return {
        "version": 1,
        "title": title,
        "tier": tier,
        "subject": None,
        "book": {"file": book_rel, "language": language},
        "exam": {"date": None, "formats": None, "book_policy": None, "duration_minutes": None, "question_count": None},
        "scope": {"chapters": None},
        "output": {"language": language},
        "study": {"hours_per_day": None, "start_date": None, "rest_days": []},
        "checks": {"run_code": False},
        "anki": {"include_unverified": False},
        "intake": {"done": False},
    }


def get_key(cfg: dict, key: str):
    cur = cfg
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def set_key(ws: Workspace, key: str, value: str) -> object:
    if key not in KEYS:
        close = [k for k in KEYS if k.split(".")[-1] == key.split(".")[-1]]
        raise ESError(f"Unknown setting '{key}'.",
                      (f"Did you mean {close[0]}? " if close else "") + "See all settings: python " + str(CLI) +
                      " config <workspace> show")
    conv, _ = KEYS[key]
    val = conv(value)
    if key == "scope.pages":
        val = resolve_pages(ws, val)
    if key == "scope.chapters" and val != "all":
        known = {c["id"] for c in ws.outline["chapters"]}
        bad = [c for c in val if c not in known]
        if bad:
            raise ESError(f"Unknown chapter id(s): {', '.join(bad)}.", f"Known chapters: {', '.join(sorted(known))}")
    if key == "intake.done" and val:
        missing = [k for k in REQUIRED_INTAKE if get_key(ws.config, k) in (None, "", [])]
        if missing:
            raise ESError(f"Intake is not finished: {', '.join(missing)} not set yet.",
                          "Ask the user and set them first.")
    cur = ws.config
    parts = key.split(".")
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = val
    ws.save_config()
    return val


def resolve_pages(ws: Workspace, spec: str) -> dict | None:
    """'45-120, 130' -> {"spec": ..., "ranges": [[44, 119], [129, 129]]} (0-based page indices, inclusive).
    Each number is read as a page label (printed page number) first, then as a PDF page number (1 = first page)."""
    spec = spec.strip()
    if spec.lower() in ("", "all", "none", "*"):
        return None
    norm = re.sub(r"\s*(?:[-–—~]|\bto\b)\s*", "-", spec, flags=re.I)
    ranges = []
    for tok in [t for t in re.split(r"[,;\s]+", norm) if t]:
        ends = tok.split("-") if tok.count("-") == 1 else [tok]
        idx = []
        for e in ends:
            p = ws.page_by_label(e)
            if p is not None:
                idx.append(p["index"])
            elif e.isdigit() and 1 <= int(e) <= len(ws.pages):
                idx.append(int(e) - 1)
            else:
                raise ESError(f"'{e}' is not a page of this book.",
                              f"Use printed page numbers or PDF page numbers 1-{len(ws.pages)}, e.g. 45-120, 130-140.")
        a, b = idx[0], idx[-1]
        if b < a:
            raise ESError(f"Page range '{tok}' ends before it starts.")
        ranges.append([a, b])
    ranges.sort()
    merged: list[list[int]] = []
    for a, b in ranges:
        if merged and a <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return {"spec": spec, "ranges": merged}


def init_workspace(root: Path, book: Path, tier: str, title: str | None, language: str) -> Workspace:
    from .ingest import PDF_LIKE, TEXT_LIKE, copy_book
    if not book.exists():
        raise ESError(f"Book file not found: {book}")
    if book.suffix.lower() not in PDF_LIKE | TEXT_LIKE:
        raise ESError(f"Unsupported book format: {book.suffix}",
                      "Use PDF, EPUB, MOBI, XPS, CBZ, TXT, Markdown, page pictures (JPG, PNG, TIFF) or a folder of "
                      "them. Convert other formats (DOCX, DjVu, ...) to PDF first.")
    if tier not in TIERS:
        raise ESError(f"Unknown tier '{tier}'.", f"Use one of: {', '.join(TIERS)}")
    root.mkdir(parents=True, exist_ok=True)
    ws = Workspace(root)
    if ws.config_path.exists():
        raise ESError(f"A workspace already exists at {root}.",
                      "Continue it with: python " + str(CLI) + f" next {root}")
    write_json(ws.config_path, default_config("", title or book.stem, tier, language))
    ws.reload()
    rel_book = copy_book(book, ws)
    cfg = read_json(ws.config_path)
    cfg["book"]["file"] = rel_book
    cfg["book"]["original_name"] = book.name
    if not title:
        try:
            import pymupdf
            if book.suffix.lower() in PDF_LIKE:
                meta_title = (pymupdf.open(str(book)).metadata or {}).get("title")
                if meta_title and len(meta_title) > 3:
                    cfg["title"] = meta_title
        except Exception:
            pass
    write_json(ws.config_path, cfg)
    ws.reload()
    ws.state.update({"created": dt.datetime.now().replace(microsecond=0).isoformat(), "stages": {}, "chapters": {},
                     "attempts": {}})
    ws.save_state()
    return ws


def workspace_slug(title: str) -> str:
    return slugify(title, 40)
