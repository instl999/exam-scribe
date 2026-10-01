#!/usr/bin/env python3
"""ExamScribe command line. Run `python examscribe.py help` for the command list.

The normal loop for any model is:
    python examscribe.py next  <workspace>     # shows the task card
    ... do exactly what the card says ...
    python examscribe.py check <workspace>     # PASS shows the next card; FAIL lists fixes
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from examscribe_lib.common import CLI, ESError, Workspace, setup_console  # noqa: E402

HELP = f"""ExamScribe — turn a textbook into verified exam-prep materials.

Check:     python {CLI} probe <file.pdf>       (seconds: text layer? scans? how long will it take?)
Read:      python {CLI} extract <file.pdf> [--pages 10-25] [--out book.md]
                                               (the book's text as Markdown in seconds; never OCR a text PDF)
Start:     python {CLI} init <workspace> --book <file.pdf> [--tier strict|standard|frontier] [--language xx]
                                               (the book's language is detected when --language is not given)
Loop:      python {CLI} next  <workspace>      (shows the task to do)
           python {CLI} check <workspace>      (PASS -> next task, FAIL -> what to fix)

Other commands:
  status <ws>                       progress overview
  restore-draft <ws>                put the current task's draft back to the script's version (a damaged or
                                    rewritten draft; your version is kept as .bak)
  config <ws> show|get K|set K V    settings (exam date, formats, scope, language, OCR, ...)
  plan <ws> [--confirm]             priorities and study plan
  add-material <ws> <file> --kind past-paper|syllabus|slides [--label NAME]
  find <ws> "words" [--chapter ch01]   where words appear in the book (with page numbers)
  page <ws> <page-label> [--image]  print one page's extracted text (or render its image)
  format <kind>                     exact format of a block kind (concept, formula, question, ...)
  build <ws> [--pdf]                rebuild study pages, flashcards, calendar, report
  report <ws>                       print the verification summary
  mistakes <ws> add Q-ID... | import <results.json> | due
  outline <ws> [--confirm | --from-text <file>]   show, confirm or replace the chapter/section outline
  ingest <ws> [--ocr] [--jobs N]    (re)extract the book (--ocr: then read scanned pages)
  ocr <ws> [--pages 45-120 | --all] [--engine auto|windows|tesseract|rapidocr] [--dpi 200] [--jobs N]
           [--budget SECONDS] [--force]
                                    read scanned pages of the exam scope with OCR (resumable)
  ocr-setup [<ws>] [--language xx]  download Tesseract language data (a few MB) so scans in that language can
                                    be read on any computer (ask the user first)
  inventory <ws>                    rebuild the inventory
  doctor                            check Python packages and OCR engines
"""


def main(argv: list[str] | None = None) -> int:
    setup_console()
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("help", "-h", "--help"):
        print(HELP)
        return 0
    cmd = argv[0]
    p = argparse.ArgumentParser(prog=f"examscribe {cmd}", add_help=False)
    try:
        if cmd == "doctor":
            return _doctor()
        if cmd == "ocr-setup":
            p.add_argument("workspace", nargs="?", default=None)
            p.add_argument("--language", default=None)
            a = p.parse_args(argv[1:])
            from examscribe_lib.ocr import fetch_tessdata, pick_engine
            lang = a.language
            ws = None
            if a.workspace:
                ws = Workspace.open(Path(a.workspace))
                lang = lang or (ws.config.get("book") or {}).get("language")
            lang = lang or "en"
            print(f"Getting Tesseract language data for '{lang}' (saved in your home folder, used for every book):")
            fetch_tessdata(lang, say=print)
            eng = pick_engine(ws, lang, preferred="tesseract")
            if eng is None:
                raise ESError("The language data is there, but Tesseract still cannot run.",
                              f"Run: python {CLI} doctor   (PyMuPDF is needed for OCR)")
            print(f"OK: Tesseract can now read '{lang}' scans ({eng.lang})."
                  + (f" Next: python {CLI} next \"{ws.root}\"" if ws else ""))
            return 0
        if cmd == "format":
            from examscribe_lib.schema import SCHEMAS, format_help
            kind = argv[1] if len(argv) > 1 else ""
            if not kind:
                print("Block kinds: " + ", ".join(k for k, b in SCHEMAS.items() if not b.worksheet))
                return 0
            print(format_help(kind))
            return 0
        if cmd == "probe":
            p.add_argument("file")
            p.add_argument("--language", default=None)
            a = p.parse_args(argv[1:])
            import tempfile
            from examscribe_lib.images import prepare_book
            from examscribe_lib.probe import probe_book, probe_text
            with tempfile.TemporaryDirectory() as tmp:
                book = prepare_book(Path(a.file).resolve(), Path(tmp) / "pictures.pdf")
                print(probe_text(probe_book(book, a.language)))
            return 0
        if cmd == "extract":
            p.add_argument("file")
            p.add_argument("--out", default=None)
            p.add_argument("--pages", default=None)
            p.add_argument("--language", default="en")
            a = p.parse_args(argv[1:])
            from examscribe_lib.extract import extract_markdown
            info = extract_markdown(Path(a.file), Path(a.out).resolve() if a.out else None, a.pages, a.language)
            print(f"Wrote {info['out']}: {info['pages']} page(s), {info['chars']} characters, "
                  f"{info['seconds']} s (reader: {info['reader']}).")
            if info["needs_ocr"]:
                print(f"{info['needs_ocr']} page(s) are scans without text; they are marked in the file. Read them "
                      f"with the workspace commands (init, then ocr).")
            return 0
        if cmd == "init":
            p.add_argument("workspace")
            p.add_argument("--book", required=True)
            p.add_argument("--tier", default="strict")
            p.add_argument("--title", default=None)
            p.add_argument("--language", default=None)
            a = p.parse_args(argv[1:])
            from examscribe_lib.config import init_workspace
            from examscribe_lib.images import page_images, prepare_book
            from examscribe_lib.probe import probe_book, probe_text
            book_path = Path(a.book).resolve()
            title = a.title
            if page_images(book_path) or book_path.suffix.lower() in (".djvu", ".djv"):
                # photos or scans of pages: one PDF in the new workspace, then read like any scanned book
                if (Path(a.workspace).resolve() / "examscribe.json").exists():
                    raise ESError(f"A workspace already exists at {Path(a.workspace).resolve()}.")
                title = title or book_path.stem
                book_path = prepare_book(book_path, Path(a.workspace).resolve() / "source" / "book.pdf")
                print(f"Made one PDF from the page pictures: {book_path}")
            try:
                info = probe_book(book_path, a.language)
            except ESError:
                info = None
            guess = (info or {}).get("lang_guess")
            language = a.language or guess or "en"
            ws = init_workspace(Path(a.workspace).resolve(), book_path, a.tier, title, language)
            print(f"Created workspace {ws.root} (tier: {a.tier}, book language: {language}"
                  + (" - detected from the text" if not a.language and guess else "") + ").")
            if info:
                info["name"] = book_path.name
                print(probe_text(info))
                if a.language and guess and guess != a.language.split("-")[0]:
                    print(f"NOTE: the book looks like '{guess}', but --language is '{a.language}'. If that is "
                          f"wrong: python {CLI} config \"{ws.root}\" set book.language {guess}")
            print(f"Next: python {CLI} next \"{ws.root}\"")
            return 0
        if len(argv) < 2:
            raise ESError(f"'{cmd}' needs a workspace folder.", f"Example: python {CLI} {cmd} ./exam-prep/chemistry")
        ws = Workspace.open(Path(argv[1]))
        rest = argv[2:]
        if cmd == "next":
            from examscribe_lib.pipeline import compute_next, render_card
            print(render_card(ws, compute_next(ws)))
            return 0
        if cmd == "restore-draft":
            from examscribe_lib.pipeline import restore_draft
            print(restore_draft(ws))
            return 0
        if cmd == "check":
            p.add_argument("--accept-flags", action="store_true")
            p.add_argument("--file", default=None)
            a = p.parse_args(rest)
            from examscribe_lib.pipeline import check
            res = check(ws, accept_flags=a.accept_flags, only_file=Path(a.file) if a.file else None)
            print(res.text)
            return 0 if res.ok else 1
        if cmd == "status":
            from examscribe_lib.pipeline import status_text
            print(status_text(ws))
            return 0
        if cmd == "ingest":
            p.add_argument("--ocr", action="store_true")
            p.add_argument("--jobs", type=int, default=None)
            a = p.parse_args(rest)
            from examscribe_lib.ingest import ingest
            summary = ingest(ws, jobs=a.jobs, progress=print)
            _print_ingest(summary)
            if a.ocr and summary.get("needs_ocr"):
                print("")
                return _ocr(ws, argparse.Namespace(pages=None, all=False, engine=None, dpi=None, jobs=None,
                                                   force=False, budget=None))
            print(f"\nNext: python {CLI} next \"{ws.root}\"")
            return 0
        if cmd == "ocr":
            p.add_argument("--pages", default=None)
            p.add_argument("--all", action="store_true")
            p.add_argument("--engine", default=None, choices=["auto", "windows", "tesseract", "rapidocr"])
            p.add_argument("--dpi", type=int, default=None)
            p.add_argument("--jobs", type=int, default=None)
            p.add_argument("--budget", type=float, default=None)
            p.add_argument("--force", action="store_true")
            return _ocr(ws, p.parse_args(rest))
        if cmd == "inventory":
            from examscribe_lib.inventory import build_inventory
            print(build_inventory(ws))
            return 0
        if cmd == "config":
            from examscribe_lib import config as C
            if not rest or rest[0] == "show":
                import json
                print(json.dumps(ws.config, indent=2, ensure_ascii=False))
                print("\nSettable keys:")
                for k, (_, h) in C.KEYS.items():
                    print(f"  {k:<26} {h}")
                return 0
            if rest[0] == "get" and len(rest) > 1:
                print(C.get_key(ws.config, rest[1]))
                return 0
            if rest[0] == "set" and len(rest) > 2:
                val = C.set_key(ws, rest[1], " ".join(rest[2:]))
                print(f"OK {rest[1]} = {val}")
                return 0
            raise ESError("Use: config <ws> show | get KEY | set KEY VALUE")
        if cmd == "plan":
            p.add_argument("--confirm", action="store_true")
            a = p.parse_args(rest)
            from examscribe_lib.priority import compute_priorities, plan_summary
            compute_priorities(ws)
            if a.confirm:
                ws.state["plan_confirmed"] = True
                ws.save_state()
                from examscribe_lib.pipeline import compute_next, render_card
                print("Plan confirmed.\n\nNext task:\n" + render_card(ws, compute_next(ws)))
            else:
                print(plan_summary(ws))
            return 0
        if cmd == "outline":
            p.add_argument("--from-text", default=None)
            p.add_argument("--confirm", action="store_true")
            a = p.parse_args(rest)
            from examscribe_lib.outline_edit import confirm_outline, load_outline_text, outline_text
            if a.from_text:
                print(load_outline_text(ws, Path(a.from_text)))
            elif a.confirm:
                print(confirm_outline(ws))
                from examscribe_lib.pipeline import compute_next, render_card
                print("\nNext task:\n" + render_card(ws, compute_next(ws)))
            else:
                print(outline_text(ws))
            return 0
        if cmd == "add-material":
            p.add_argument("file")
            p.add_argument("--kind", required=True, choices=["past-paper", "syllabus", "slides"])
            p.add_argument("--label", default=None)
            a = p.parse_args(rest)
            from examscribe_lib.materials import add_material
            print(add_material(ws, Path(a.file).resolve(), a.kind, a.label))
            return 0
        if cmd == "find":
            p.add_argument("text")
            p.add_argument("--chapter", default=None)
            a = p.parse_args(rest)
            return _find(ws, a.text, a.chapter)
        if cmd == "page":
            p.add_argument("label")
            p.add_argument("--image", action="store_true")
            a = p.parse_args(rest)
            if a.image:
                from examscribe_lib.ingest import render_page_image
                print(render_page_image(ws, a.label))
                return 0
            page = ws.page_by_label(a.label)
            if page is None:
                raise ESError(f"No page labeled '{a.label}'.")
            print(f"======== PAGE {page['label']} ========  flags: {', '.join(page['flags']) or 'none'}\n")
            print(page["text"])
            return 0
        if cmd == "build":
            p.add_argument("--pdf", action="store_true")
            a = p.parse_args(rest)
            from examscribe_lib.build import build_all
            info = build_all(ws, pdf=a.pdf)
            print(info["message"])
            return 0
        if cmd == "report":
            from examscribe_lib.report import report_text
            print(report_text(ws))
            return 0
        if cmd == "mistakes":
            from examscribe_lib.mistakes import cli as mistakes_cli
            print(mistakes_cli(ws, rest))
            return 0
        raise ESError(f"Unknown command '{cmd}'.", f"See: python {CLI} help")
    except ESError as exc:
        print(f"ERROR: {exc}")
        if exc.hint:
            print(f"Fix: {exc.hint}")
        return 2
    except SystemExit as exc:          # argparse errors
        return int(exc.code or 2)


def _print_ingest(summary: dict) -> None:
    print(f"Extracted {summary['pages']} pages (page numbers from: {summary['label_method']}; outline from: "
          f"{summary['outline_method']}).")
    for c in summary["chapters"][:40]:
        print(f"  {c['id']}: {c['title']} ({c['sections']} sections)")
    if len(summary["chapters"]) > 40:
        print(f"  ... and {len(summary['chapters']) - 40} more")
    print(f"Figures/tables found: {summary['figures']} (pictures are made for the chapters you study)")
    if summary.get("ocr_pages"):
        print(f"Pages with text from OCR: {summary['ocr_pages']}")
    if summary.get("needs_ocr"):
        print(f"Scanned pages without text: {summary['needs_ocr']} (read with OCR later, only those on the exam)")
    flagged = {k: v for k, v in summary["flagged_pages"].items() if set(v) - {"two-column"}}
    if flagged:
        print(f"Pages with extraction warnings: {len(flagged)}; e.g.")
        for label, flags in list(flagged.items())[:8]:
            print(f"  p.{label}: {', '.join(flags)}")


def _ocr(ws: Workspace, a: argparse.Namespace) -> int:
    from examscribe_lib import ocr as O
    from examscribe_lib.config import resolve_pages
    from examscribe_lib.ingest import ingest, ocr_cache_path
    if a.pages:
        r = resolve_pages(ws, a.pages)
        idx = sorted({i for s, e in r["ranges"] for i in range(s, e + 1)}) if r else list(range(len(ws.pages)))
        if a.force:
            for i in idx:
                ocr_cache_path(ws, i).unlink(missing_ok=True)
            targets = idx
        else:
            targets = O.pages_to_ocr(ws, idx)
    else:
        mode = "all" if a.all else "scope"
        if a.force:
            for i in O.scope_pages(ws, mode):
                if "ocr" in (ws.pages[i].get("flags") or []):
                    ocr_cache_path(ws, i).unlink(missing_ok=True)
            ws.reload()
            ingest(ws)
        targets = O.pages_to_ocr(ws, mode=mode)
    new = 0
    if targets:
        eng = O.pick_engine(ws, preferred=a.engine, jobs=a.jobs, dpi=a.dpi)
        if eng is None:
            raise ESError(O.no_engine_help(ws))
        res = O.run_ocr(ws, targets, eng, budget=O.DEFAULT_BUDGET if a.budget is None else a.budget)
        for msg in res["problems"][:5]:
            print(f"  warning: {msg}")
        new = res["read"] + res["salvaged"]
        left = res["left"]
    else:
        left = 0
        print("Nothing to read with OCR: every page " + ("of the file" if a.all else "in the exam scope") + " has text" +
              ("." if a.all or a.pages else " (use --all to include front matter, appendices and answer keys)."))
    cached = {int(p.stem[1:]) - 1 for p in (ws.source_dir / "ocr").glob("p*.json") if p.stem[1:].isdigit()}
    unapplied = [i for i in cached if i < len(ws.pages) and "ocr" not in (ws.pages[i].get("flags") or [])]
    if new or unapplied:
        print("Updating the book text with the OCR results ...")
        summary = ingest(ws)
        print(f"  {summary['ocr_pages']} page(s) now have text from OCR; outline from: {summary['outline_method']} "
              f"({len(summary['chapters'])} chapter(s)).")
    if left:
        print(f"NOT FINISHED — {left} page(s) still to read. Run the same command again to continue "
              "(pages already read are kept).")
        return 1
    print(f"OCR DONE.\nNext: python {CLI} next \"{ws.root}\"")
    return 0


def _find(ws: Workspace, text: str, chapter: str | None) -> int:
    from examscribe_lib.citations import QuoteIndex
    pages = None
    if chapter:
        ch = ws.chapter(chapter)
        pages = set(range(ch["start"]["page"], ch["end"]["page"] + 1))
    hits = QuoteIndex(ws).search(text, chapter_pages=pages)
    if not hits:
        print("No match. Try fewer or different words.")
        return 1
    for label, score, snippet in hits:
        tag = "exact" if score >= 1 else f"{int(score * 100)}% similar"
        print(f"p.{label} ({tag}): {snippet}")
    return 0


def _doctor() -> int:
    ok = True
    print(f"Python {sys.version.split()[0]}")
    if sys.version_info < (3, 9):
        print("  ERROR: Python 3.9 or newer is required.")
        ok = False
    for mod, pip, need in (("pymupdf", "pymupdf", True), ("markdown_it", "markdown-it-py", True),
                           ("mdit_py_plugins", "mdit-py-plugins", True), ("genanki", "genanki", False)):
        try:
            __import__(mod)
            print(f"  ok       {pip}")
        except ImportError:
            fallback = None
            if mod == "pymupdf":
                from examscribe_lib.pdfread import available
                fallback = available()
            if fallback:
                print(f"  MISSING  {pip}   ->  python -m pip install {pip}  (fast reading, figure pictures, OCR).\n"
                      f"           Until then text PDFs are read with {fallback} (slower, no pictures, no OCR).")
                continue
            print(f"  {'MISSING ' if need else 'optional'} {pip}   ->  python -m pip install {pip}")
            ok = ok and not need
    try:
        from examscribe_lib.ocr import engine_report, windows_languages
        windows_languages(fresh=True)          # doctor always asks Windows again (e.g. after adding a language)
        print("OCR engines (only needed for scanned pages without a text layer):")
        for r in engine_report("en"):
            print(f"  {'ok      ' if r['ok'] else 'optional'} {r['name']:<10} {r['detail']}")
    except Exception as exc:  # pragma: no cover
        print(f"  (could not check OCR engines: {exc})")
    print("Ready." if ok else "Install the missing packages above, then run doctor again.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
