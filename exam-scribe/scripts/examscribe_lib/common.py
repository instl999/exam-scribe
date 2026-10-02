"""Shared helpers: paths, workspace, config, JSON/text IO, and text normalization."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import secrets
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Iterable

VERSION = "1.0.0"
LIB_DIR = Path(__file__).resolve().parent
SKILL_DIR = LIB_DIR.parents[1]
ASSETS_DIR = SKILL_DIR / "assets"
REFS_DIR = SKILL_DIR / "references"
CLI = SKILL_DIR / "scripts" / "examscribe.py"


class ESError(Exception):
    """A user-facing error. `hint` tells the reader (often a model) how to fix it."""

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


def setup_console() -> None:
    """Make stdout/stderr UTF-8 so non-ASCII book text never crashes a Windows console, and line-buffered so the
    progress of long commands reaches a log file (a command run in the background) as it happens."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            pass


# ----------------------------------------------------------------------------- IO

def read_text(path: Path | str) -> str:
    # utf-8-sig: tolerate a byte-order mark (some editors and Windows PowerShell add one)
    return Path(path).read_text(encoding="utf-8-sig")


def write_text(path: Path | str, text: str) -> None:
    # Not tempfile.mkstemp: on Windows it takes "access denied" for a name clash and retries up to 2**31 times, so
    # a write a sandbox forbids (Codex: anything outside the workspace) spins forever instead of failing.
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".tmp-{os.getpid()}-{secrets.token_hex(4)}{path.suffix}")
    try:
        with open(tmp, "x", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    from .integrity import note_write          # script-owned workspace files: remember what the scripts wrote
    note_write(path)


def make_temp_dir(prefix: str) -> Path:
    """A new temporary folder, without tempfile.mkdtemp's endless retry on Windows when a sandbox denies the write:
    the system temp folder if it is writable, else the current folder."""
    for parent in (Path(tempfile.gettempdir()), Path.cwd()):
        d = parent / f"{prefix}{os.getpid()}-{secrets.token_hex(4)}"
        try:
            d.mkdir(parents=True)
            return d
        except OSError:
            continue
    raise ESError("There is no folder this command may write temporary files to.",
                  "Run it from a folder you can write to (in a sandbox: the workspace folder).")


def read_json(path: Path | str, default: Any = None) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ESError(f"{path} is not valid JSON ({exc}).",
                      "This file is managed by the scripts. Restore it or re-run the step that creates it.")


def write_json(path: Path | str, data: Any) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_jsonl(path: Path | str) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path | str, rows: Iterable[dict]) -> None:
    write_text(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def sha(text: str, n: int = 12) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:n]


def file_hash(path: Path | str) -> str | None:
    path = Path(path)
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def today() -> _dt.date:
    override = os.environ.get("EXAMSCRIBE_TODAY")
    if override:
        return _dt.date.fromisoformat(override)
    return _dt.date.today()


def now_iso() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat()


def rel(path: Path | str, root: Path | str) -> str:
    # workspace paths are absolute and share the root, so a string prefix test is enough (pathlib's
    # relative_to/resolve cost 60-400 us per call on Windows, and this runs thousands of times per command)
    ps, rs = str(path), str(root).rstrip("\\/")
    if len(ps) > len(rs) + 1 and ps[len(rs)] in "\\/" and ps[:len(rs)].lower() == rs.lower():
        return ps[len(rs) + 1:].replace("\\", "/")
    p, r = Path(path), Path(root)
    try:
        return p.resolve().relative_to(r.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


# ------------------------------------------------------------------------ text helpers

LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
             "ﬅ": "st", "ﬆ": "st"}
_LIG_RE = re.compile("[" + "".join(LIGATURES) + "]")


def fix_ligatures(text: str) -> str:
    return _LIG_RE.sub(lambda m: LIGATURES[m.group(0)], text)


def slugify(text: str, max_len: int = 48) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"\(.*?\)", " ", text)          # drop parentheticals such as "(J)" or "(ΔH)"
    text = re.sub(r"[^\w]+", "-", text).strip("-_")
    return text[:max_len].strip("-") or "item"


_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯豈-﫿]")


# scripts written without spaces between words (Thai, Lao, Khmer, Myanmar)
_NOSPACE_RE = re.compile(r"[฀-໿က-႟ក-៿]")


def word_count(text: str) -> float:
    """Approximate words. CJK characters count as half a word each; Thai-like scripts a third."""
    cjk = len(_CJK_RE.findall(text))
    nospace = len(_NOSPACE_RE.findall(text))
    rest = _NOSPACE_RE.sub(" ", _CJK_RE.sub(" ", text))
    return len(re.findall(r"[^\s]+", rest)) + cjk / 2 + nospace / 3


def estimate_tokens(text: str) -> int:
    """Rough model tokens. Scripts other than Latin cost more tokens per character."""
    cjk = len(_CJK_RE.findall(text))
    indic = len(re.findall(r"[ऀ-෿฀-໿က-႟ក-៿]", text))   # Indic, Thai, ...
    semitic = len(re.findall(r"[֐-ۿݐ-ݿ]", text))                              # Hebrew, Arabic
    cyr_greek = len(re.findall(r"[Ͱ-ϿЀ-ԯ]", text))
    rest = len(text) - cjk - indic - semitic - cyr_greek
    return int(rest / 4 + cjk * 1.2 + indic * 0.5 + semitic * 0.4 + cyr_greek * 0.33) + 1


# Abbreviations whose full stop does not end a sentence (English, German, French, Spanish, Italian, Portuguese,
# Russian), matched case-insensitively: some always, some only before a number ("Fig. 2", "S. 12", "рис. 3").
_ABBREV_ALWAYS = (r"e\.g|i\.e|etc|vs|approx|et al|dr|mr|mrs|ms|cf|ca|z\.\s?b|d\.\s?h|u\.\s?a|bzw|usw|vgl|ggf|"
                  r"evtl|inkl|p\.\s?ex|env|mme|p\.\s?ej|aprox|sra?|ad es|т\.\s?е|т\.\s?д|т\.\s?п|см|напр|и др")
_ABBREV_NUMBER = (r"no|nr|figs?|eqs?|abb|tab|gl|kap|abschn|chap|ch|sec|vol|pp?|s|st|éq|ec|cap|pág|pag|núm|"
                  r"рис|табл|ур|стр|гл|с|г")
_ABBREV_RE = re.compile(r"(?<![^\W\d_])(?:(?:" + _ABBREV_ALWAYS + r")\.|(?:" + _ABBREV_NUMBER + r")\.(?=\s?\d))",
                        re.I)
# a sentence ends at . ! ? … followed by a space, at CJK full stops, at the Devanagari danda and at Arabic ؟
_SENT_END_RE = re.compile(r"[.!?…]+(?: ?\s?[\"'”’»)\]])*\s+|[。！？]+[”’」』）)]*\s*|[।॥]\s*|؟\s*")


# German, Scandinavian, Czech, Hungarian, Finnish and Turkish write ordinals with a full stop: "im 19. Jahrhundert",
# "am 3. Oktober". A number with a full stop before one of these words does not end a sentence.
_ORDINAL_NEXT = re.compile(r"(?:Jahrhundert|Jh\b|Jahrtausend|Januar|Jänner|Februar|März|April|Mai|Juni|Juli|August|"
                           r"September|Oktober|November|Dezember|Mal\b|Auflage|Weltkrieg|Kapitel|Klasse|Stelle|Platz|"
                           r"Bundestag|Legislatur|Wahlperiode|Lebensjahr|Jahrestag|Geburtstag|Sitzung|Stufe|Runde|"
                           r"Grad|Ordnung|Reich|Republik|Parteitag|Kongress|Dynastie|Satz|Absatz|Abschnitt|Artikel|"
                           r"Band|Ausgabe|Jahrgang|Semester|Schuljahr|århundrede|århundre|århundradet|století|"
                           r"század|vuosisata|yüzyıl)")


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    # protect abbreviations (their dots become a look-alike character that is put back at the end)
    protected = _ABBREV_RE.sub(lambda m: m.group(0).replace(".", "․"), text)
    parts, start = [], 0
    for m in _SENT_END_RE.finditer(protected):
        nxt = protected[m.end():m.end() + 1]
        if m.group(0)[0] in ".!?…" and (not nxt or nxt.islower()):
            continue                     # "... e.g. water" or the end of the text: not a break here
        if m.group(0).rstrip() == "." and re.search(r"(?:^|[\s(])\d{1,3}$", protected[:m.start()]) and \
                _ORDINAL_NEXT.match(protected, m.end()):
            continue                     # "im 19. Jahrhundert"
        parts.append(protected[start:m.end()])
        start = m.end()
    parts.append(protected[start:])
    return [p.replace("․", ".").strip() for p in parts if p and p.strip()]


# ------------------------------------------------------------------------ match keys
# A match key is a canonical form used to compare a quote with book text. It is
# forgiving about things that do not change meaning (case, whitespace,
# punctuation, ligatures, curly quotes, line-break hyphens, x vs * vs times) but
# keeps what does: letters, digits, decimal points, minus signs, and relations.

_KEEP_SYMBOLS = set("+=<>/%±√∑∫≈≠≤≥∞")
_CHAR_MAP = {
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-",
    "−": "-", "⁻": "-", "₋": "-", "﹣": "-", "－": "-",
    "⁄": "/", "∕": "/", "∆": "δ", "Δ": "δ",
}


# Characters kept in a key: letters and digits; a decimal point between two digits; a minus sign directly
# before a digit and not after a letter or digit; and relation/operator symbols.
_KEEP_RE = re.compile(r"[^\W_]|(?<=\d)\.(?=\d)|(?<![^\W_])-(?=\d)|[+=<>/%±√∑∫≈≠≤≥∞]")


def _stage_char(ch: str) -> str:
    """Per-character normalisation: our dash/slash/delta map, else NFKC then the map, then casefold."""
    if ch in _CHAR_MAP:
        return _CHAR_MAP[ch]
    return "".join(_CHAR_MAP.get(c, c).casefold() for c in unicodedata.normalize("NFKC", ch))


def _build_trans() -> dict[int, str]:
    """Translation table for characters whose per-character normalisation changes them (ligatures,
    super/subscripts, fractions, special spaces, full-width forms, ...), so whole strings can be
    normalised at C speed with exactly the same result as the per-character path."""
    cands = set(_CHAR_MAP)
    ranges = [(0x00A0, 0x00BF), (0x02B0, 0x02FF), (0x2000, 0x206F), (0x2070, 0x209F), (0x2100, 0x218F),
              (0x2460, 0x24FF), (0xFB00, 0xFB06), (0xFF01, 0xFF5E), (0x3000, 0x3000)]
    for a, b in ranges:
        cands.update(chr(c) for c in range(a, b + 1))
    table = {}
    for ch in cands:
        staged = _stage_char(ch)
        if staged != ch:
            table[ord(ch)] = staged
    return table


_TRANS = _build_trans()


def build_key(text: str) -> tuple[str, list[int]]:
    """Return (key, index_map) where index_map[i] is the index in `text` of key[i]. Slow; use key_of()
    when the positions are not needed."""
    chars: list[str] = []
    owner: list[int] = []
    for i, ch in enumerate(text):
        for c in _stage_char(ch):
            chars.append(c)
            owner.append(i)
    stage = "".join(chars)
    out, idx = [], []
    for m in _KEEP_RE.finditer(stage):
        out.append(m.group(0))
        idx.append(owner[m.start()])
    return "".join(out), idx


def key_of(text: str) -> str:
    """The match key of `text` (same result as build_key(text)[0], much faster on long text)."""
    t = text.translate(_TRANS)
    if unicodedata.is_normalized("NFKC", t):
        stage = t.casefold()
    else:
        stage = "".join(_stage_char(ch) for ch in text)
    return "".join(_KEEP_RE.findall(stage))


# A number token: digits, optionally joined by "." "," or thin/no-break spaces directly between digits.
NUMBER_TOKEN_RE = re.compile(r"(?<![\w.,])[-\u2212]?\d+(?:[.,\u00a0\u2009\u202f]\d+)*(?![\w])")


def canon_number(raw: str) -> str:
    """Canonical form of a dot-decimal number: '15,690' -> '15690', '\u2212890' -> '-890', '250.' -> '250',
    '0.500' -> '0.5', '15.0' -> '15'. (Book text goes through number_groups, which also knows decimal commas.)"""
    raw = raw.replace("\u2212", "-")
    raw = re.sub(r"[,\u00a0\u2009\u202f ]", "", raw).rstrip(".")
    if "." in raw:
        raw = raw.rstrip("0").rstrip(".")
    raw = raw.lstrip("+")
    raw = re.sub(r"^(-?)0+(?=\d)", r"\1", raw)
    return raw if raw not in ("", "-", "-0") else "0"


def _readings(token: str) -> list[str]:
    """The possible values of one number token. Decimal commas (4,184 = 4.184 in German, French, Russian ...)
    and dot thousands (1.000 = 1000) are read correctly; a token that fits both conventions ('4,184', '1.000')
    gives both readings, so checks accept either."""
    sign = "-" if token[0] in "-\u2212" else ""
    body = re.sub(r"[\u00a0\u2009\u202f](?=\d{3}(?!\d))", "", token.lstrip("-\u2212"))   # thin-space thousands
    parts = re.split(r"[.,\u00a0\u2009\u202f]", body)
    seps = re.findall(r"[.,\u00a0\u2009\u202f]", body)

    def c(s: str) -> str:
        return canon_number(sign + s)
    if not seps:
        return [c(body)]
    if set(seps) == {"."} or set(seps) == {","}:
        sep = seps[0]
        if len(seps) == 1:
            a, b = parts
            decimal = c(a + "." + b)
            if len(b) == 3 and 1 <= len(a) <= 3 and a[0] != "0":  # 4,184 / 1.000: thousands or decimal
                return [c(a + b), decimal] if sep == "," else [decimal, c(a + b)]
            return [decimal]
        if all(len(p) == 3 for p in parts[1:]) and 1 <= len(parts[0]) <= 3:
            return [c("".join(parts))]                          # 1,000,000 / 1.000.000
        return [c(p) for p in parts]                            # 2.1.3, a list or a date: separate numbers
    last_dot, last_comma = body.rfind("."), body.rfind(",")
    if last_dot > last_comma:                                    # 1,234.56
        return [c(body.replace(",", ""))]
    return [c(body.replace(".", "").replace(",", "."))]         # 1.234,56


def number_groups(text: str) -> list[list[str]]:
    """Each number in `text` with its possible canonical readings (usually one)."""
    return [_readings(m.group(0)) for m in NUMBER_TOKEN_RE.finditer(text)]


def numbers_in(text: str) -> list[str]:
    """All numbers in `text`, in canonical form (every reading of an ambiguous number)."""
    return [r for g in number_groups(text) for r in g]


# ------------------------------------------------------------------------ workspace

CONFIG_NAME = "examscribe.json"
STATE_NAME = "state.json"


class Workspace:
    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self._config: dict | None = None
        self._state: dict | None = None
        self._pages: list[dict] | None = None
        self._label_index: dict[str, int] | None = None

    # -- discovery
    @classmethod
    def open(cls, root: Path | str) -> "Workspace":
        ws = cls(root)
        if not ws.config_path.exists():
            raise ESError(f"No ExamScribe workspace at {ws.root}.",
                          f"Create one first: python {CLI} init <workspace-folder> --book <file.pdf>")
        return ws

    # -- paths
    @property
    def config_path(self) -> Path:
        return self.root / CONFIG_NAME

    @property
    def state_path(self) -> Path:
        return self.root / STATE_NAME

    @property
    def source_dir(self) -> Path:
        return self.root / "source"

    @property
    def pages_path(self) -> Path:
        return self.source_dir / "pages.jsonl"

    @property
    def outline_path(self) -> Path:
        return self.source_dir / "outline.json"

    @property
    def quality_path(self) -> Path:
        return self.source_dir / "quality.json"

    @property
    def figures_dir(self) -> Path:
        return self.source_dir / "figures"

    @property
    def page_images_dir(self) -> Path:
        return self.source_dir / "page-images"

    @property
    def inventory_dir(self) -> Path:
        return self.root / "inventory"

    @property
    def chapters_dir(self) -> Path:
        return self.root / "chapters"

    @property
    def materials_dir(self) -> Path:
        return self.root / "materials"

    @property
    def site_dir(self) -> Path:
        return self.root / "site"

    @property
    def export_dir(self) -> Path:
        return self.root / "export"

    @property
    def progress_dir(self) -> Path:
        return self.root / "progress"

    def chapter_dir(self, ch: str) -> Path:
        return self.chapters_dir / ch

    def draft_dir(self, ch: str) -> Path:
        return self.chapter_dir(ch) / "draft"

    def verify_dir(self, ch: str) -> Path:
        return self.chapter_dir(ch) / "verify"

    def inventory_path(self, ch: str) -> Path:
        return self.inventory_dir / f"{ch}.json"

    # -- config
    @property
    def config(self) -> dict:
        if self._config is None:
            self._config = read_json(self.config_path, None)
            if self._config is None:
                raise ESError(f"Missing {self.config_path}.")
        return self._config

    def save_config(self) -> None:
        write_json(self.config_path, self.config)

    # -- state
    @property
    def state(self) -> dict:
        if self._state is None:
            self._state = read_json(self.state_path, None) or {}
        return self._state

    def save_state(self) -> None:
        write_json(self.state_path, self.state)

    # -- pages
    @property
    def pages(self) -> list[dict]:
        if self._pages is None:
            if not self.pages_path.exists():
                raise ESError("The book has not been ingested yet.", f"Run: python {CLI} ingest {self.root}")
            self._pages = read_jsonl(self.pages_path)
        return self._pages

    def reload(self) -> None:
        self._config = self._state = self._pages = self._label_index = None

    @property
    def label_index(self) -> dict[str, int]:
        """Labels as written, plus case-insensitive forms where they are unambiguous (a book can label a cover page
        "I" and a front-matter page "i")."""
        if self._label_index is None:
            exact: dict[str, int] = {}
            folded: dict[str, list[int]] = {}
            for p in self.pages:
                exact.setdefault(str(p["label"]), p["index"])
                folded.setdefault(str(p["label"]).casefold(), []).append(p["index"])
            self._label_index = {k: v[0] for k, v in folded.items() if len(v) == 1}
            self._label_index.update({"\x00" + k: v for k, v in exact.items()})
        return self._label_index

    def page_by_label(self, label: str) -> dict | None:
        label = str(label).strip()
        i = self.label_index.get("\x00" + label)
        if i is None:
            i = self.label_index.get(label.casefold())
        return self.pages[i] if i is not None else None

    def pages_for_spec(self, spec: str) -> list[dict]:
        """Resolve '142', 'iv', or a range '142-143' to page records ([] if unknown)."""
        spec = spec.strip()
        p = self.page_by_label(spec)
        if p is not None:
            return [p]
        m = re.fullmatch(r"(.+?)\s*[-–]\s*(.+)", spec)
        if m:
            a, b = self.page_by_label(m.group(1)), self.page_by_label(m.group(2))
            if a is not None and b is not None and 0 <= b["index"] - a["index"] <= 3:
                return self.pages[a["index"]: b["index"] + 1]
        return []

    @property
    def outline(self) -> dict:
        data = read_json(self.outline_path, None)
        if data is None:
            raise ESError("No outline yet.", f"Run: python {CLI} ingest {self.root}")
        return data

    def chapter(self, ch: str) -> dict:
        for c in self.outline["chapters"]:
            if c["id"] == ch:
                return c
        raise ESError(f"Unknown chapter id '{ch}'.", f"See the chapter list with: python {CLI} status {self.root}")

    def scope_ranges(self) -> list[tuple[int, int]] | None:
        """Page-index ranges (inclusive) of the exam scope when it was given as pages (scope.pages)."""
        sp = (self.config.get("scope") or {}).get("pages")
        if isinstance(sp, dict) and sp.get("ranges"):
            return [(int(a), int(b)) for a, b in sp["ranges"]]
        return None

    def span_in_scope(self, start: dict, end: dict) -> bool:
        ranges = self.scope_ranges()
        if not ranges:
            return True
        a = start["page"]
        b = end["page"] - (1 if end.get("y", 1e9) <= 60 and end["page"] > a else 0)
        return any(a <= hi and lo <= b for lo, hi in ranges)

    def chapters_in_scope(self) -> list[dict]:
        scope = self.config.get("scope", {}).get("chapters", "all")
        chapters = [c for c in self.outline["chapters"] if c.get("kind", "chapter") == "chapter"]
        if scope not in (None, "", "all"):
            wanted = [s.strip() for s in (scope if isinstance(scope, list) else str(scope).split(",")) if s.strip()]
            chapters = [c for c in chapters if c["id"] in wanted]
        return [c for c in chapters if self.span_in_scope(c["start"], c["end"])]

    def section_in_scope(self, sec: dict) -> bool:
        return self.span_in_scope(sec["start"], sec["end"])

    def inventory(self, ch: str) -> dict:
        data = read_json(self.inventory_path(ch), None)
        if data is None:
            raise ESError(f"No inventory for {ch}.", f"Run: python {CLI} inventory {self.root}")
        return data

    def all_inventory_items(self) -> dict[str, dict]:
        items: dict[str, dict] = {}
        if not self.inventory_dir.exists():
            return items
        for path in sorted(self.inventory_dir.glob("ch*.json")):
            inv = read_json(path, {})
            for it in inv.get("items", []):
                items[it["id"]] = it
        return items

    @property
    def tier(self) -> str:
        return self.config.get("tier", "strict")
