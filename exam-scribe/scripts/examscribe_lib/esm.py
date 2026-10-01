"""ExamScribe Markdown (ESM): the strict, line-oriented format all notes and worksheets use.

    ::: concept T-enthalpy
    term: Enthalpy
    definition: [p.11: "Enthalpy (H) is a property of a system equal to ..."]
    plain: At constant pressure, a change in enthalpy is the heat taken in or given out. [p.11: "..."]
    :::

Rules (enforced here and in lint.py):
  * Content lives only inside `::: <kind> <ID>` ... `:::` blocks.
  * Inside a block every line is `key: value` (one line per field; repeat a key for lists),
    an HTML comment, a blank line, or one fenced code block.
  * Outside blocks only headings (#), comments, blank lines and `---` are allowed.
Line-oriented rules are the easiest format for any model to follow and for a script to check.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

OPEN_RE = re.compile(r"^:::\s*(?P<kind>[A-Za-z][\w-]*)(?:\s+(?P<id>\S+))?\s*$")
CLOSE_RE = re.compile(r"^:::\s*$")
FIELD_RE = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9 _-]{0,30}?)\s*:\s?(?P<value>.*)$")
FENCE_RE = re.compile(r"^(?P<fence>```+|~~~+)\s*(?P<lang>[\w+-]*)\s*$")
CITE_RE = re.compile(r'\[p\.\s?(?P<page>[^\]:"]{1,20}?)\s*:\s*"(?P<quote>.+?)"\s*\]')
COVERS_RE = re.compile(r"\(\s*covers?\s*:\s*(?P<ids>[^)]*)\)", re.I)
PLACEHOLDER_RE = re.compile(r"<<\s*(FILL|OPTIONAL)\b.*?>>", re.S)
TRUST_MARKS = "✅⚠️\U0001f4a1❌✔✓✖"


@dataclass
class Field:
    key: str
    value: str
    line: int
    raw: str


@dataclass
class Block:
    kind: str
    id: str
    line: int
    end_line: int | None = None
    fields: list[Field] = field(default_factory=list)
    code: str | None = None
    code_lang: str = ""
    code_line: int | None = None

    def get(self, key: str) -> Field | None:
        for f in self.fields:
            if f.key == key:
                return f
        return None

    def all(self, key: str) -> list[Field]:
        return [f for f in self.fields if f.key == key]

    def value(self, key: str, default: str = "") -> str:
        f = self.get(key)
        return f.value if f else default

    def keys(self) -> list[str]:
        return [f.key for f in self.fields]


@dataclass
class Issue:
    line: int
    code: str
    message: str
    hint: str = ""
    level: str = "error"          # error | warn
    block: str = ""
    category: str = "format"      # format | evidence | coverage


@dataclass
class Doc:
    path: Path | None
    lines: list[str]
    blocks: list[Block]
    issues: list[Issue]
    headings: list[tuple[int, str]]

    def by_id(self) -> dict[str, Block]:
        return {b.id: b for b in self.blocks}

    def of_kind(self, *kinds: str) -> list[Block]:
        return [b for b in self.blocks if b.kind in kinds]


def normalize_key(key: str) -> str:
    k = re.sub(r"[\s_]+", " ", key.strip().lower())
    m = re.fullmatch(r"option\s*-?\s*([a-f])", k)
    if m:
        return f"option {m.group(1)}"
    m = re.fullmatch(r"why\s*-?\s*not\s*-?\s*([a-f])", k)
    if m:
        return f"why-not {m.group(1)}"
    k = re.sub(r"\s*-\s*", "-", k)
    return k


def parse(text: str, path: Path | str | None = None) -> Doc:
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    blocks: list[Block] = []
    issues: list[Issue] = []
    headings: list[tuple[int, str]] = []
    cur: Block | None = None
    in_comment = False
    fence: str | None = None
    code_buf: list[str] = []
    last_field: Field | None = None
    for no, raw in enumerate(lines, start=1):
        line = raw.rstrip()
        stripped = line.strip()
        # fenced code inside a block
        if fence is not None:
            if stripped.startswith(fence) and not stripped[len(fence):].strip():
                cur.code = "\n".join(code_buf)
                fence = None
                code_buf = []
            else:
                code_buf.append(raw)
            continue
        # comments (possibly multi-line)
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if stripped.startswith("<!--"):
            if "-->" not in stripped[4:]:
                in_comment = True
            continue
        if not stripped:
            continue
        m_open = OPEN_RE.match(stripped)
        if CLOSE_RE.match(stripped):
            if cur is None:
                issues.append(Issue(no, "stray-close", "':::' closes nothing here.",
                                    "Delete this line, or add the missing '::: <kind> <ID>' opening line above."))
            else:
                cur.end_line = no
                cur = None
                last_field = None
            continue
        if m_open:
            if cur is not None:
                issues.append(Issue(cur.line, "unclosed", f"Block '{cur.kind} {cur.id}' is not closed.",
                                    f"Add a line with only ':::' before line {no}.", block=cur.id))
                cur.end_line = no - 1
            bid = m_open.group("id")
            if not bid:
                issues.append(Issue(no, "no-id", f"Block '{m_open.group('kind')}' has no ID.",
                                    "Opening lines look like '::: concept T-enthalpy'. Keep the ID from the draft."))
                bid = f"?line{no}"
            cur = Block(kind=m_open.group("kind").lower(), id=bid, line=no)
            blocks.append(cur)
            last_field = None
            continue
        if cur is None:
            if stripped.startswith("#"):
                headings.append((no, stripped.lstrip("#").strip()))
                continue
            if re.fullmatch(r"-{3,}|\*{3,}|_{3,}", stripped):
                continue
            issues.append(Issue(no, "stray-text", "Text outside a ::: block.",
                                "Every claim must live inside a block so it can be checked. Move this line into "
                                "the right block as a 'field: value' line, or delete it."))
            continue
        fm = FENCE_RE.match(stripped)
        if fm:
            if cur.code is not None:
                issues.append(Issue(no, "two-code", "A block may contain only one fenced code block.",
                                    "Merge the code into one fence.", block=cur.id))
            fence = fm.group("fence")
            cur.code_lang = fm.group("lang").lower()
            cur.code_line = no
            cur.code = ""
            continue
        fmatch = FIELD_RE.match(stripped)
        if fmatch and not stripped.startswith(("- ", "* ")):
            f = Field(normalize_key(fmatch.group("key")), fmatch.group("value").strip(), no, raw)
            cur.fields.append(f)
            last_field = f
            continue
        if raw[:1] in (" ", "\t") and last_field is not None:
            last_field.value = (last_field.value + " " + stripped).strip()
            issues.append(Issue(no, "continuation", "A field value continued on a new line.",
                                "Keep each field on one line. (This was joined automatically.)", level="warn",
                                block=cur.id))
            continue
        issues.append(Issue(no, "bad-line", "Expected 'field: value' inside the block.",
                            "Write each piece as its own field line, e.g. 'plain: ... [p.12: \"...\"]'.",
                            block=cur.id))
    if fence is not None and cur is not None:
        issues.append(Issue(cur.code_line or 0, "unclosed-code", "A fenced code block is not closed.",
                            "Close it with the same fence (```).", block=cur.id))
        cur.code = "\n".join(code_buf)
    if cur is not None:
        issues.append(Issue(cur.line, "unclosed", f"Block '{cur.kind} {cur.id}' is not closed.",
                            "Add a line with only ':::' at the end of the block.", block=cur.id))
    return Doc(Path(path) if path else None, lines, blocks, issues, headings)


# ------------------------------------------------------------------------------ citations

@dataclass
class Citation:
    page: str
    quote: str
    start: int
    end: int


def citations(value: str) -> list[Citation]:
    return [Citation(m.group("page").strip(), m.group("quote").strip(), m.start(), m.end())
            for m in CITE_RE.finditer(value)]


def strip_citations(value: str) -> str:
    v = CITE_RE.sub(" ", value)
    v = COVERS_RE.sub(" ", v)
    return re.sub(r"\s+", " ", v).strip()


def covers(value: str) -> list[str]:
    ids = []
    for m in COVERS_RE.finditer(value):
        ids.extend(i.strip() for i in re.split(r"[,\s]+", m.group("ids")) if i.strip())
    return ids


def is_unsure(value: str) -> bool:
    return value.strip().upper().startswith("UNSURE")


# ------------------------------------------------------------------------------ auto-fix

_CITE_VARIANTS = [
    # (pages 12-13 / pp. 12 / page 12 / p 12 / p12) with straight or curly quotes, optional colon
    re.compile(r'[\[(]\s*(?:pp?\.?|pages?)\s*(?P<page>[\w.\-–]{1,20}?)\s*[:,]?\s*'
               r'["“”„«»](?P<quote>[^\]\n]+?)["“”«»]\s*[\])]', re.I),
]


def autofix(text: str, kinds_with_points: tuple[str, ...] = ("must-know",)) -> tuple[str, list[str]]:
    """Fix harmless format slips. Never changes the words of a claim or a quote."""
    notes: list[str] = []
    out_lines: list[str] = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cur_kind = None
    in_comment = False
    in_fence = False
    for raw in lines:
        line = raw.rstrip().replace("\t", "    ")
        s = line.strip()
        if in_comment:
            out_lines.append(line)
            if "-->" in line:
                in_comment = False
            continue
        if s.startswith("<!--") and "-->" not in s[4:]:
            in_comment = True
            out_lines.append(line)
            continue
        if in_fence:
            out_lines.append(raw.rstrip("\n"))
            if FENCE_RE.match(s):
                in_fence = False
            continue
        if FENCE_RE.match(s) and cur_kind:
            in_fence = True
            out_lines.append(line)
            continue
        m_open = OPEN_RE.match(s)
        if m_open:
            cur_kind = m_open.group("kind").lower()
            if s != line:
                notes.append("removed indentation before a ':::' line")
            out_lines.append(s)
            continue
        if CLOSE_RE.match(s):
            cur_kind = None
            out_lines.append(":::")
            continue
        new = line
        if any(ch in new for ch in TRUST_MARKS):
            new = "".join(ch for ch in new if ch not in TRUST_MARKS).replace("️", "")
            notes.append("removed trust-marker symbols (the scripts add these)")
        if cur_kind:
            # bullets in must-know style blocks become point: lines
            bm = re.match(r"^\s*[-*•]\s+(.*)$", new)
            if bm and cur_kind in kinds_with_points:
                new = "point: " + bm.group(1)
                notes.append("turned a '- ' bullet into a 'point:' line")
            fm = FIELD_RE.match(new.strip())
            if fm and not new.strip().startswith(("- ", "* ")):
                key = fm.group("key")
                nk = normalize_key(key)
                if cur_kind == "question" and re.fullmatch(r"[A-Fa-f]", key.strip()):
                    nk = f"option {key.strip().lower()}"
                display = re.sub(r"(option|why-not) ([a-f])$", lambda mm: f"{mm.group(1)} {mm.group(2).upper()}", nk)
                val = fm.group("value").strip()
                val2 = _fix_citations(val)
                if val2 != val:
                    notes.append("normalized a citation to [p.N: \"...\"]")
                val2 = re.sub(r"^(?:unsure|Unsure)\s*[:\-—]\s*", "UNSURE: ", val2)
                new_line = f"{display}: {val2}".rstrip()
                if new_line != new.strip():
                    if display != key.strip():
                        notes.append(f"normalized field name '{key.strip()}' -> '{display}'")
                new = new_line
        else:
            new = new.rstrip()
        out_lines.append(new)
    fixed = "\n".join(out_lines)
    if not fixed.endswith("\n"):
        fixed += "\n"
    seen = []
    for n in notes:
        if n not in seen:
            seen.append(n)
    return fixed, seen


def _fix_citations(value: str) -> str:
    def repl(m: re.Match) -> str:
        page = m.group("page").replace("–", "-").strip(" .")
        return f'[p.{page}: "{m.group("quote").strip()}"]'
    new = value
    for rx in _CITE_VARIANTS:
        new = rx.sub(repl, new)
    return new


def render_block(kind: str, bid: str, fields: list[tuple[str, str]], comments: list[str] | None = None) -> str:
    out = [f"::: {kind} {bid}"]
    for c in comments or []:
        out.append(f"<!-- {c} -->")
    for k, v in fields:
        out.append(f"{k}: {v}".rstrip())
    out.append(":::")
    return "\n".join(out)
