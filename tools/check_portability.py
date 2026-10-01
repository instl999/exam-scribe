"""Flag Python-3.12-only syntax so the skill keeps running on Python 3.9-3.11.

Checks every .py file under the given folders for:
  * backslashes inside f-string {expressions} (allowed only since Python 3.12, PEP 701)
  * the same quote character reused inside an f-string expression (also 3.12-only)
Run:  python tools/check_portability.py exam-scribe/scripts tests tools
"""
from __future__ import annotations

import io
import sys
import tokenize
from pathlib import Path


def check_file(path: Path) -> list[str]:
    problems = []
    src = path.read_text(encoding="utf-8")
    toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    stack: list[dict] = []          # one entry per open f-string: {"quote": str, "depth": int}
    for tok in toks:
        name = tokenize.tok_name.get(tok.type, "")
        if name == "FSTRING_START":
            q = tok.string.lstrip("rRbBfFuU")
            stack.append({"quote": q, "depth": 0, "line": tok.start[0]})
            continue
        if not stack:
            continue
        top = stack[-1]
        if name == "FSTRING_END":
            stack.pop()
            continue
        if name == "OP" and tok.string == "{":
            top["depth"] += 1
        elif name == "OP" and tok.string == "}":
            top["depth"] = max(0, top["depth"] - 1)
        elif top["depth"] > 0 and name == "STRING":
            if "\\" in tok.string:
                problems.append(f"{path}:{tok.start[0]}: backslash inside an f-string expression")
            body_quote = tok.string.lstrip("rRbBuU")[:1]
            if len(top["quote"]) == 1 and body_quote == top["quote"]:
                problems.append(f"{path}:{tok.start[0]}: same quote character reused inside an f-string expression")
    return problems


def main(paths: list[str]) -> int:
    if sys.version_info < (3, 12):
        print("Run this checker with Python 3.12+ (it relies on the new f-string tokens).")
        return 2
    problems = []
    for base in paths or ["."]:
        for p in sorted(Path(base).rglob("*.py")):
            problems += check_file(p)
    for pr in problems:
        print(pr)
    print(f"{len(problems)} portability problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
