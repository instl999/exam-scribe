"""Read scanned pages with OCR: fast engines, parallel workers, a cache per page, resumable runs.

Engines (the first one available is used unless `ocr.engine` is set):
  windows    the OCR built into Windows 10/11 - nothing to install, roughly 0.3-0.8 s per page per worker
  tesseract  Tesseract through PyMuPDF (needs Tesseract's language data installed)
  rapidocr   RapidOCR (python -m pip install rapidocr_onnxruntime) - the best choice for Chinese
Only the pages of the exam scope are read (unless asked otherwise). Each page's result is saved in
source/ocr/pNNNN.json the moment it is read, so a run that is stopped (time limit, closed terminal) continues
where it stopped. A run also stops by itself when its time budget is used up. Afterwards the book is
re-extracted so the new text is used everywhere (ingest.py picks the cached pages up).
"""
from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .common import CLI, ESError, Workspace, read_json, write_json
from .config import get_key
from .ingest import NEEDS_OCR, PDF_LIKE, ocr_cache_path

try:
    import pymupdf
except ImportError:  # pragma: no cover
    pymupdf = None

WINOCR = Path(__file__).resolve().parent.parent / "winocr.ps1"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0          # CREATE_NO_WINDOW
SPEED = {"windows": 0.6, "tesseract": 2.5, "rapidocr": 4.0}  # rough seconds per page per worker (8-core PC)
STARTUP = {"windows": 3.0, "tesseract": 2.0, "rapidocr": 5.0}
# measured speeds, kept per computer so that the first estimate in a new workspace is already realistic
MACHINE_SPEED = Path.home() / ".examscribe" / "ocr-speed.json"
DEFAULT_DPI = {"windows": 200, "tesseract": 300, "rapidocr": 200}
TESS_LANG = {"en": "eng", "zh": "chi_sim", "zh-cn": "chi_sim", "zh-tw": "chi_tra", "zh-hk": "chi_tra", "ja": "jpn",
             "ko": "kor", "de": "deu", "fr": "fra", "es": "spa", "it": "ita", "pt": "por", "ru": "rus", "nl": "nld",
             "pl": "pol", "tr": "tur", "ar": "ara", "hi": "hin", "vi": "vie", "sv": "swe", "cs": "ces", "uk": "ukr"}
DEFAULT_BUDGET = 540          # seconds; below the 10-minute limit many agent tools have


@dataclass
class Engine:
    name: str
    lang: str            # the engine's own language code
    workers: int
    dpi: int
    tessdata: str | None = None      # Tesseract only: the folder holding this language's data

    def estimate(self, pages: int, ws: Workspace | None = None) -> float:
        per = SPEED[self.name]
        if self.name == "rapidocr":     # one process using every core: small machines are much slower
            per *= max(1.0, 8 / (os.cpu_count() or 2))
        timed = []
        for path in ([ws.source_dir / "ocr" / "meta.json"] if ws is not None else []) + [MACHINE_SPEED]:
            try:
                timed.append(read_json(path, {}) or {})
            except (OSError, ESError):
                pass
        for meta in timed:        # a timed earlier run on this computer is a better guide
            if isinstance(meta.get(self.name), dict) and meta[self.name].get("sec_per_page_worker"):
                per = meta[self.name]["sec_per_page_worker"]
                break
        parallel = self.workers if self.name != "rapidocr" else 1
        return STARTUP[self.name] + pages * per / max(1, parallel)


def fmt_duration(seconds: float) -> str:
    if seconds < 90:
        return f"{max(5, int(round(seconds / 5.0)) * 5)} seconds"
    minutes = seconds / 60
    return f"{int(round(minutes))} minutes" if minutes < 90 else f"{minutes / 60:.1f} hours"


# ============================================================================ engine detection

def _powershell() -> str | None:
    if os.name != "nt":
        return None
    p = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(p) if p.exists() else shutil.which("powershell")


_WIN_LANGS: list[str] | None = None


WIN_LANGS_CACHE = Path.home() / ".examscribe" / "windows-ocr-languages.json"
WIN_LANGS_TTL = 600        # seconds: `status` and `next` run often (e.g. while OCR runs); a new language pack shows soon


def windows_languages(fresh: bool = False) -> list[str]:
    """OCR languages installed in Windows (empty when not on Windows or the OCR API is unavailable). Asking
    Windows takes a PowerShell start (1-2 s), so the answer is remembered for a few minutes."""
    global _WIN_LANGS
    if _WIN_LANGS is not None and not fresh:
        return _WIN_LANGS
    if not fresh:
        try:
            cached = json.loads(WIN_LANGS_CACHE.read_text(encoding="utf-8"))
            if 0 <= time.time() - cached["time"] < WIN_LANGS_TTL:
                _WIN_LANGS = [str(t) for t in cached["tags"]]
                return _WIN_LANGS
        except Exception:
            pass
    _WIN_LANGS = []
    ps = _powershell()
    if ps and WINOCR.exists():
        try:
            out = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                  str(WINOCR), "-Languages"], capture_output=True, text=True, timeout=90,
                                 creationflags=NO_WINDOW)
            if out.returncode == 0 and out.stdout.strip():
                tags = json.loads(out.stdout.strip().splitlines()[-1])
                _WIN_LANGS = [tags] if isinstance(tags, str) else [str(t) for t in tags]
                try:
                    WIN_LANGS_CACHE.parent.mkdir(parents=True, exist_ok=True)
                    WIN_LANGS_CACHE.write_text(json.dumps({"time": time.time(), "tags": _WIN_LANGS}), encoding="utf-8")
                except OSError:
                    pass
        except Exception:
            _WIN_LANGS = []
    return _WIN_LANGS


def _win_tag(book_lang: str, tags: list[str]) -> str | None:
    lang = (book_lang or "en").lower()
    # Simplified and Traditional Chinese are different OCR models: never fall back from one to the other
    if lang.startswith("zh"):
        prefs = ["zh-hant", "zh-tw", "zh-hk"] if _traditional(lang) else ["zh-hans", "zh-cn", "zh-sg"]
    else:
        prefs = [lang, lang.split("-")[0]]
    for pref in prefs:
        for tag in tags:
            t = tag.lower()
            if t == pref or t.startswith(pref + "-"):
                return tag
    return None


# PyMuPDF contains the Tesseract engine; it only needs language data (<lang>.traineddata files). Besides a normal
# Tesseract installation, files dropped into this folder are used (no admin rights or system install needed).
USER_TESSDATA = Path.home() / ".examscribe" / "tessdata"


TESSDATA_URL = "https://github.com/tesseract-ocr/tessdata_fast/raw/main/{code}.traineddata"


def tess_folders() -> list[tuple[str, list[str]]]:
    """Folders with Tesseract language data and the language codes in each: an installed Tesseract's folder
    first, then ~/.examscribe/tessdata (filled by `ocr-setup`)."""
    if pymupdf is None:
        return []
    try:
        system = pymupdf.get_tessdata()
    except Exception:
        system = None
    out = []
    for td in (system, str(USER_TESSDATA)):
        if td and Path(td).is_dir():
            codes = sorted(p.stem for p in Path(td).glob("*.traineddata") if p.stat().st_size > 100_000)
            if codes and all(td != f for f, _ in out):
                out.append((str(td), codes))
    return out


def tesseract_info() -> tuple[str | None, list[str]]:
    """(first tessdata folder, its language codes) or (None, [])."""
    folders = tess_folders()
    return folders[0] if folders else (None, [])


def tess_codes_for(book_lang: str) -> list[str]:
    """Tesseract language files a book needs: its language, and English (textbooks mix in English terms)."""
    lang = (book_lang or "en").lower()
    code = ("chi_tra" if _traditional(lang) else "chi_sim") if lang.startswith("zh") else \
        TESS_LANG.get(lang) or TESS_LANG.get(lang.split("-")[0])
    return list(dict.fromkeys(c for c in (code, "eng") if c))


def fetch_tessdata(book_lang: str, say=print) -> list[str]:
    """Download the Tesseract language data a book needs (2-15 MB per language, no admin rights) into
    ~/.examscribe/tessdata. Returns the codes now available there."""
    import urllib.request
    codes = tess_codes_for(book_lang)
    if not codes or codes == ["eng"] and not (book_lang or "en").lower().startswith("en"):
        raise ESError(f"Tesseract has no language data for '{book_lang}'.",
                      "Use another OCR engine, or a copy of the PDF with a text layer.")
    USER_TESSDATA.mkdir(parents=True, exist_ok=True)
    for code in codes:
        dest = USER_TESSDATA / f"{code}.traineddata"
        if dest.exists() and dest.stat().st_size > 100_000:
            say(f"  {code}: already downloaded ({dest})")
            continue
        url = TESSDATA_URL.format(code=code)
        tmp = dest.with_suffix(".part")
        say(f"  downloading {code} ({url}) ...")
        try:
            with urllib.request.urlopen(url, timeout=180) as resp, open(tmp, "wb") as fh:
                shutil.copyfileobj(resp, fh)
            if tmp.stat().st_size < 100_000:
                raise OSError("the downloaded file is too small to be language data")
            os.replace(tmp, dest)
            say(f"  {code}: {dest.stat().st_size / 1e6:.1f} MB saved to {dest}")
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            raise ESError(f"Could not download {code}.traineddata ({exc}).",
                          f"Download {url} by hand (a browser works) and put the file into {USER_TESSDATA}")
    return codes


def _traditional(lang: str) -> bool:
    return any(x in lang.lower() for x in ("hant", "tw", "hk", "mo"))


def _tess_lang(book_lang: str, have: list[str]) -> str | None:
    lang = (book_lang or "en").lower()
    if lang.startswith("zh"):
        code = "chi_tra" if _traditional(lang) else "chi_sim"
    else:
        code = TESS_LANG.get(lang) or TESS_LANG.get(lang.split("-")[0])
    if not code or code not in have:
        return None
    if code != "eng" and "eng" in have:
        code += "+eng"             # textbooks mix in English terms and units
    return code


def _rapidocr_class():
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore
        return RapidOCR
    except Exception:
        pass
    try:
        from rapidocr import RapidOCR  # type: ignore
        return RapidOCR
    except Exception:
        return None


def _rapidocr_installed() -> bool:
    """Whether RapidOCR is installed, without importing it (the import alone takes seconds)."""
    import importlib.util
    return any(importlib.util.find_spec(m) is not None for m in ("rapidocr_onnxruntime", "rapidocr"))


def _rapid_ok(book_lang: str) -> bool:
    return (book_lang or "en").lower().split("-")[0] in ("zh", "en")


def _order(book_lang: str) -> list[str]:
    base = (book_lang or "en").lower().split("-")[0]
    if base == "zh":
        return ["rapidocr", "windows", "tesseract"]
    return ["windows", "tesseract", "rapidocr"]


def engine_report(book_lang: str) -> list[dict]:
    """Every engine with whether it can read this language, for `probe`, `doctor` and the OCR task cards."""
    rows = []
    for name in _order(book_lang):
        if name == "windows":
            if os.name != "nt":
                rows.append({"name": name, "ok": False, "detail": "only on Windows 10/11"})
                continue
            tags = windows_languages()
            tag = _win_tag(book_lang, tags)
            rows.append({"name": name, "ok": bool(tag), "lang": tag,
                         "detail": f"installed OCR languages: {', '.join(tags) or 'none'}" + (
                             "" if tag else f" (add '{book_lang}' in Settings > Time & language > Language & region)")})
        elif name == "tesseract":
            folders = tess_folders()
            found = next(((td, code) for td, have in folders if (code := _tess_lang(book_lang, have))), None)
            have = sorted({c for _, codes in folders for c in codes})
            missing = "+".join(tess_codes_for(book_lang))
            rows.append({"name": name, "ok": bool(found), "lang": found[1] if found else None,
                         "tessdata": found[0] if found else None,
                         "detail": (f"language data: {', '.join(have[:12]) or 'none'}" if folders else
                                    "no language data") +
                                   ("" if found else f" (get '{missing}' with: python {CLI} ocr-setup <workspace>)")})
        else:
            have = _rapidocr_installed()
            ok = have and _rapid_ok(book_lang)
            rows.append({"name": name, "ok": ok, "lang": "ch+en" if ok else None,
                         "detail": ("installed" if have else "not installed (python -m pip install rapidocr_onnxruntime)") +
                                   ("" if _rapid_ok(book_lang) else "; reads only Chinese and English")})
    return rows


def pick_engine(ws: Workspace | None, book_lang: str | None = None, preferred: str | None = None,
                jobs: int | None = None, dpi: int | None = None) -> Engine | None:
    if pymupdf is None:              # pages must be rendered to images first, and that needs PyMuPDF
        return None
    cfg = ws.config if ws is not None else {}
    lang = book_lang or (cfg.get("book") or {}).get("language") or "en"
    preferred = preferred or get_key(cfg, "ocr.engine") or "auto"
    jobs = jobs or get_key(cfg, "ocr.jobs")
    dpi = dpi or get_key(cfg, "ocr.dpi")
    rows = {r["name"]: r for r in engine_report(lang)}
    names = _order(lang) if preferred == "auto" else [preferred]
    for name in names:
        r = rows.get(name)
        if r and r["ok"]:
            cpus = os.cpu_count() or 2
            # pages are rendered by this process at ~7-10 pages/s, which 3-4 fast Windows workers already match
            auto = {"windows": max(2, min(4, cpus - 1)), "tesseract": max(1, min(8, cpus)), "rapidocr": 1}[name]
            workers = 1 if name == "rapidocr" else int(jobs or auto)
            return Engine(name, r["lang"], workers, int(dpi or DEFAULT_DPI[name]), r.get("tessdata"))
    return None


def no_engine_help(ws: Workspace) -> str:
    lang = ws.config.get("book", {}).get("language") or "en"
    if pymupdf is None:
        return ("OCR needs PyMuPDF to turn pages into images, and it is not installed.\n"
                "Options for the user:\n"
                "  1. Install it: python -m pip install pymupdf   (then run next again)\n"
                "  2. Use a copy of the PDF that already has a text layer (for example made with OCRmyPDF).\n"
                f"  3. Go on without the scanned pages: python \"{CLI}\" config \"{ws.root}\" set ocr.skip true")
    rows = engine_report(lang)
    status = "\n".join(f"    {r['name']:<10} {'ready' if r['ok'] else 'not usable'} - {r['detail']}" for r in rows)
    codes = tess_codes_for(lang)
    size = "2-4 MB" if not any(c.startswith(("chi", "jpn", "kor")) for c in codes) else "3-5 MB"
    return (f"No OCR engine can read this book's language ({lang}) on this computer:\n{status}\n"
            "Options for the user (ask which one; each needs their OK):\n"
            f"  1. Any computer, no admin rights: download the Tesseract language data ({'+'.join(codes)}, about "
            f"{size} each) from github.com:\n       python \"{CLI}\" ocr-setup \"{ws.root}\"\n"
            f"  2. Windows 10/11: Settings > Time & language > Language & region > add the language '{lang}' "
            "(it includes optical character recognition).\n"
            "  3. Chinese or English books: python -m pip install rapidocr_onnxruntime   (best for Chinese)\n"
            "  4. Use a copy of the PDF that already has a text layer (for example made with OCRmyPDF) and start a "
            "new workspace with it.\n"
            f"  5. Go on without the scanned pages: python \"{CLI}\" config \"{ws.root}\" set ocr.skip true "
            "(their content will be missing from the notes).")


# ============================================================================ which pages

def scope_pages(ws: Workspace, mode: str = "scope") -> list[int]:
    """Page indices to consider for OCR.

    scope     the exam scope: the scope.pages ranges if given, else the pages of the chosen chapters
              (all chapters while the scope is not set yet)
    chapters  the pages of every chapter (front matter, index, answer keys and appendices are left out)
    all       every page of the file
    """
    last = len(ws.pages) - 1
    if mode == "all":
        return list(range(last + 1))
    ranges = ws.scope_ranges() if mode == "scope" else None
    if ranges:
        return sorted({i for a, b in ranges for i in range(a, min(b, last) + 1)})
    chosen = (ws.config.get("scope") or {}).get("chapters")
    if mode == "chapters" or chosen in (None, "", []):
        chapters = [c for c in ws.outline["chapters"] if c.get("kind", "chapter") == "chapter"]
    else:
        chapters = ws.chapters_in_scope()
    idx: set[int] = set()
    for c in chapters:
        idx.update(range(c["start"]["page"], min(c["end"]["page"], last) + 1))
    return sorted(idx)


def pages_to_ocr(ws: Workspace, indices: list[int] | None = None, mode: str = "scope") -> list[int]:
    """Pages without a usable text layer that have not been read yet."""
    pool = indices if indices is not None else scope_pages(ws, mode)
    out = []
    for i in pool:
        flags = ws.pages[i].get("flags") or []
        if set(flags) & NEEDS_OCR and "ocr" not in flags and not ocr_cache_path(ws, i).exists():
            out.append(i)
    return out


def ocr_status(ws: Workspace) -> dict:
    pool = scope_pages(ws)
    needing = [i for i in pool if set(ws.pages[i].get("flags") or []) & NEEDS_OCR or ocr_cache_path(ws, i).exists()]
    done = [i for i in needing if ocr_cache_path(ws, i).exists()]
    return {"scope_pages": len(pool), "scanned": len(needing), "done": len(done), "left": len(needing) - len(done)}


# ============================================================================ running

def _save(ws: Workspace, doc, index: int, lines: list[dict], scale_x: float, scale_y: float, engine: Engine,
          angle: float = 0.0) -> None:
    page = doc[index]
    out = []
    for l in lines:
        text = " ".join(str(l.get("text", "")).split())
        if not text:
            continue
        out.append({"text": text, "x0": round(l["x0"] * scale_x, 1), "y0": round(l["y0"] * scale_y, 1),
                    "x1": round(l["x1"] * scale_x, 1), "y1": round(l["y1"] * scale_y, 1)})
    write_json(ocr_cache_path(ws, index), {"engine": engine.name, "lang": engine.lang, "dpi": engine.dpi,
                                           "width": round(page.rect.width, 1), "height": round(page.rect.height, 1),
                                           "angle": angle, "lines": out})


def _render(doc, index: int, folder: Path, dpi: int, raw: bool = False) -> tuple[Path, int, int]:
    """Render one page in gray. raw=True writes an uncompressed .gray file (8-byte size header + pixels): no
    PNG compression, which costs more than the OCR itself on big noisy scans."""
    page = doc[index]
    longest = max(page.rect.width, page.rect.height) / 72.0
    dpi = int(min(dpi, 9000 / max(1.0, longest)))          # engines refuse very large images
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
    tmp = folder / f"p{index + 1:04d}.part"
    if raw:
        final = folder / f"p{index + 1:04d}.gray"
        data = getattr(pix, "samples_mv", None) or pix.samples
        if pix.stride != pix.width:                          # drop row padding
            data = b"".join(bytes(data[r * pix.stride:r * pix.stride + pix.width]) for r in range(pix.height))
        with open(tmp, "wb") as fh:
            fh.write(struct.pack("<ii", pix.width, pix.height))
            fh.write(data)
    else:
        final = folder / f"p{index + 1:04d}.png"
        pix.save(str(tmp), output="png")
    os.replace(tmp, final)                                   # workers never see a half-written file
    return final, pix.width, pix.height


def _index_of(image_path: str) -> int | None:
    name = Path(image_path).stem
    return int(name[1:]) - 1 if name.startswith("p") and name[1:].isdigit() else None


class _Progress:
    def __init__(self, total: int, say, every: float = 10.0):
        self.total, self.say, self.every = total, say, every
        self.start = time.time()
        self.last = self.start

    def tick(self, done: int, force: bool = False) -> None:
        now = time.time()
        if not self.say or (not force and now - self.last < self.every):
            return
        self.last = now
        rate = done / max(0.001, now - self.start)
        left = (self.total - done) / rate if rate > 0 else 0
        speed = f"{rate:.1f} pages/s" if rate >= 1 else (f"{1 / rate:.0f} s per page" if rate > 0 else "starting")
        self.say(f"  OCR {done}/{self.total} pages  ({speed}" +
                 (f", about {fmt_duration(left)} left)" if done < self.total and rate > 0 else ")"))


def salvage(ws: Workspace, doc, engine_name: str = "windows") -> int:
    """Save results that workers of an earlier, interrupted run wrote but nobody collected."""
    root = ws.source_dir / "ocr" / "work"
    if not root.exists():
        return 0
    n = 0
    for f in root.glob("*/w*.jsonl"):
        try:
            text = f.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            idx = _index_of(rec.get("image", ""))
            if idx is None or rec.get("error") or idx >= doc.page_count or ocr_cache_path(ws, idx).exists():
                continue
            page = doc[idx]
            eng = Engine(engine_name, rec.get("lang", ""), 1, int(round(72 * rec["width"] / page.rect.width)))
            _save(ws, doc, idx, rec.get("lines") or [], page.rect.width / rec["width"],
                  page.rect.height / rec["height"], eng, rec.get("angle") or 0.0)
            n += 1
    for d in root.iterdir():
        shutil.rmtree(d, ignore_errors=True)
    return n


def _run_windows(ws: Workspace, doc, todo: list[int], engine: Engine, deadline: float, prog: _Progress) -> tuple[int, list[str]]:
    ps = _powershell()
    run_dir = ws.source_dir / "ocr" / "work" / uuid.uuid4().hex[:8]
    run_dir.mkdir(parents=True, exist_ok=True)
    k = max(1, min(engine.workers, len(todo)))
    stop = run_dir / "STOP"
    procs, outs, errs = [], [], []
    for w in range(k):
        mine = todo[w::k]
        lst = run_dir / f"w{w}.txt"
        lst.write_text("\n".join(str(run_dir / f"p{i + 1:04d}.gray") for i in mine) + "\n", encoding="utf-8")
        out = run_dir / f"w{w}.jsonl"
        out.write_text("", encoding="utf-8")
        err = open(run_dir / f"w{w}.err", "w", encoding="utf-8")
        errs.append(err)
        procs.append(subprocess.Popen(
            [ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(WINOCR), "-List", str(lst),
             "-Out", str(out), "-Lang", engine.lang, "-WaitSeconds", "300", "-StopFile", str(stop),
             "-ParentPid", str(os.getpid())], stdout=subprocess.DEVNULL, stderr=err, creationflags=NO_WINDOW))
        outs.append({"path": out, "pos": 0, "buf": b""})
    sizes: dict[int, tuple[int, int]] = {}
    problems: list[str] = []
    finished = 0

    def collect() -> int:
        n = 0
        for o in outs:
            try:
                with open(o["path"], "rb") as fh:
                    fh.seek(o["pos"])
                    chunk = fh.read()
            except OSError:
                continue
            o["pos"] += len(chunk)
            data = o["buf"] + chunk
            *complete, o["buf"] = data.split(b"\n")
            for raw in complete:
                if not raw.strip():
                    continue
                try:
                    rec = json.loads(raw.decode("utf-8-sig"))
                except ValueError:
                    continue
                idx = _index_of(rec.get("image", ""))
                n += 1
                if idx is None:
                    continue
                if rec.get("error"):
                    problems.append(f"page {idx + 1}: {rec['error']}")
                else:
                    page = doc[idx]
                    _save(ws, doc, idx, rec.get("lines") or [], page.rect.width / rec["width"],
                          page.rect.height / rec["height"], engine, rec.get("angle") or 0.0)
                try:
                    (run_dir / f"p{idx + 1:04d}.gray").unlink()
                except OSError:
                    pass
        return n

    rendered = 0
    ahead = 2 * k + 2
    try:
        while True:
            finished += collect()
            prog.tick(finished)
            if rendered < len(todo) and rendered - finished < ahead and time.time() < deadline:
                _render(doc, todo[rendered], run_dir, engine.dpi, raw=True)
                rendered += 1
                continue
            if finished >= rendered and (rendered == len(todo) or time.time() >= deadline):
                break
            codes = [p.poll() for p in procs]
            if all(c is not None for c in codes) or any(c not in (None, 0) for c in codes):
                finished += collect()        # all workers ended, or one failed (e.g. language missing)
                break
            time.sleep(0.05)
    finally:
        stop.write_text("stop", encoding="utf-8")
        end = time.time() + 60
        while time.time() < end and any(p.poll() is None for p in procs):
            finished += collect()
            time.sleep(0.1)
        for p in procs:
            if p.poll() is None:
                p.kill()
        finished += collect()
        for e in errs:
            e.close()
        err_text = " ".join((run_dir / f"w{w}.err").read_text(encoding="utf-8", errors="replace").strip()
                            for w in range(k)).strip()
        if err_text:
            problems.insert(0, err_text[:500])
        shutil.rmtree(run_dir, ignore_errors=True)
    return finished, problems


def _tess_chunk(args: tuple) -> list[tuple[int, list | None, str]]:
    path, indices, lang, dpi, tessdata = args
    doc = pymupdf.open(path)
    out = []
    for i in indices:
        try:
            page = doc[i]
            tp = page.get_textpage_ocr(language=lang, dpi=dpi, full=True, tessdata=tessdata)
            d = page.get_text("dict", textpage=tp)
            lines = []
            for b in d.get("blocks", []):
                for ln in b.get("lines", []):
                    text = " ".join(s["text"].strip() for s in ln.get("spans", []) if s["text"].strip())
                    if text:
                        x0, y0, x1, y1 = ln["bbox"]
                        lines.append({"text": text, "x0": x0, "y0": y0, "x1": x1, "y1": y1})
            out.append((i, lines, ""))
        except Exception as exc:
            out.append((i, None, str(exc)))
    return out


def _run_tesseract(ws: Workspace, doc, todo: list[int], engine: Engine, deadline: float, prog: _Progress) -> tuple[int, list[str]]:
    book = str(ws.root / ws.config["book"]["file"])
    tessdata = engine.tessdata or tesseract_info()[0]
    chunks = [todo[i:i + 2] for i in range(0, len(todo), 2)]
    finished, problems = 0, []

    def handle(results) -> None:
        nonlocal finished
        for i, lines, err in results:
            finished += 1
            if lines is None:
                problems.append(f"page {i + 1}: {err}")
            else:
                _save(ws, doc, i, lines, 1.0, 1.0, engine)
        prog.tick(finished)

    if engine.workers > 1 and len(chunks) > 1:
        try:
            from concurrent.futures import ProcessPoolExecutor, as_completed
            with ProcessPoolExecutor(max_workers=engine.workers) as pool:
                futures = [pool.submit(_tess_chunk, (book, c, engine.lang, engine.dpi, tessdata)) for c in chunks]
                for fut in as_completed(futures):
                    handle(fut.result())
                    if time.time() >= deadline:
                        for f in futures:
                            f.cancel()
                        break
            return finished, problems
        except Exception as exc:          # no subprocesses allowed: go on in this process
            problems.append(f"parallel OCR unavailable ({exc}); continuing in one process")
    for c in chunks:
        if time.time() >= deadline:
            break
        if all(ocr_cache_path(ws, i).exists() for i in c):
            continue
        handle(_tess_chunk((book, c, engine.lang, engine.dpi, tessdata)))
    return finished, problems


def _rapid_lines(result) -> list[dict]:
    items = []
    if isinstance(result, tuple) and len(result) == 2 and (result[0] is None or isinstance(result[0], list)):
        for box, text, *_ in result[0] or []:          # rapidocr_onnxruntime: ([[box, text, score], ...], times)
            items.append((box, text))
    else:                                              # rapidocr >= 2: object with boxes / txts
        boxes = getattr(result, "boxes", None)
        txts = getattr(result, "txts", None)
        if boxes is not None and txts is not None:
            items = list(zip([list(map(list, b)) for b in boxes], txts))
    lines = []
    for box, text in items:
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        lines.append({"text": str(text), "x0": min(xs), "y0": min(ys), "x1": max(xs), "y1": max(ys)})
    return lines


def _run_rapidocr(ws: Workspace, doc, todo: list[int], engine: Engine, deadline: float, prog: _Progress) -> tuple[int, list[str]]:
    cls = _rapidocr_class()
    if cls is None:
        raise ESError("RapidOCR is installed but cannot be loaded.",
                      "Reinstall it: python -m pip install --force-reinstall rapidocr_onnxruntime")
    reader = cls()
    run_dir = ws.source_dir / "ocr" / "work" / uuid.uuid4().hex[:8]
    run_dir.mkdir(parents=True, exist_ok=True)
    finished, problems = 0, []
    try:
        for i in todo:
            if time.time() >= deadline:
                break
            path, w, h = _render(doc, i, run_dir, engine.dpi)
            try:
                lines = _rapid_lines(reader(str(path)))
                page = doc[i]
                _save(ws, doc, i, lines, page.rect.width / w, page.rect.height / h, engine)
            except Exception as exc:
                problems.append(f"page {i + 1}: {exc}")
            finished += 1
            path.unlink(missing_ok=True)
            prog.tick(finished)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
    return finished, problems


RUNNERS = {"windows": _run_windows, "tesseract": _run_tesseract, "rapidocr": _run_rapidocr}


def run_ocr(ws: Workspace, pages: list[int], engine: Engine, budget: float = DEFAULT_BUDGET, say=print) -> dict:
    """OCR the given pages (skipping ones already cached). Returns counts; never raises for single-page failures."""
    book = ws.root / ws.config["book"]["file"]
    if pymupdf is None or book.suffix.lower() not in PDF_LIKE:
        raise ESError("OCR works on PDF-like books only.")
    doc = pymupdf.open(str(book))
    (ws.source_dir / "ocr").mkdir(parents=True, exist_ok=True)
    salvaged = salvage(ws, doc, engine.name)
    todo = [i for i in pages if not ocr_cache_path(ws, i).exists()]
    start = time.time()
    deadline = start + budget if budget and budget > 0 else float("inf")
    done, problems = 0, []
    if todo:
        if say:
            say(f"Reading {len(todo)} page(s) with {engine.name} OCR ({engine.lang}, {engine.dpi} dpi, "
                f"{engine.workers} worker(s)); estimated {fmt_duration(engine.estimate(len(todo), ws))}.")
        prog = _Progress(len(todo), say)
        done, problems = RUNNERS[engine.name](ws, doc, todo, engine, deadline, prog)
        prog.tick(done, force=True)
    elapsed = time.time() - start
    left = [i for i in pages if not ocr_cache_path(ws, i).exists()]
    if done >= 3:
        parallel = engine.workers if engine.name != "rapidocr" else 1
        timing = {"sec_per_page_worker": round(max(0.05, (elapsed - STARTUP[engine.name]) * parallel / done), 3),
                  "dpi": engine.dpi, "workers": engine.workers, "pages": done}
        # the computer-wide record only from runs long enough to be a real measurement
        for meta_path in [ws.source_dir / "ocr" / "meta.json"] + ([MACHINE_SPEED] if elapsed >= 10 else []):
            try:
                meta = read_json(meta_path, {}) or {}
                meta[engine.name] = timing
                write_json(meta_path, meta)
            except (OSError, ESError):   # the home folder may be read-only in a sandbox
                pass
    return {"read": done - len([p for p in problems if p.startswith("page ")]), "salvaged": salvaged,
            "left": len(left), "left_pages": left, "seconds": round(elapsed, 1), "problems": problems}
