"""Regenerate exam-scribe/references/format.md from the block schema, so the docs never drift from the linter.

    python tools/gen_format_doc.py          # writes the file
    python tools/gen_format_doc.py --check  # exit 1 if the file is out of date (used by the tests)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exam-scribe" / "scripts"))

from examscribe_lib.schema import SCHEMAS, format_help  # noqa: E402

INTRO = '''# Notes format (ExamScribe Markdown)

This file is generated from the block schema by `tools/gen_format_doc.py`; the linter enforces exactly
what is written here. At any time you can print one block's format with
`python SKILL/scripts/examscribe.py format <kind>`.

## The rules

1. Content lives only inside blocks:

   ```
   ::: concept T-enthalpy
   term: Enthalpy
   definition: [p.11: "Enthalpy (H) is a property of a system equal to its internal energy plus the product of its pressure and volume:"]
   plain: Enthalpy is a property of a system: its internal energy plus its pressure times its volume. [p.11: "equal to its internal energy plus the product of its pressure and volume"]
   :::
   ```

2. Inside a block every line is `field: value` on ONE line. Repeat a field for lists (`step:`, `row:`,
   `point:`). Comments (`<!-- -->`) and blank lines are allowed; a block may hold one fenced code block.
3. Outside blocks only headings (`#`), comments, blank lines and `---` are allowed.
4. Keep every `::: kind ID` line exactly as the skeleton wrote it. You may add new blocks only of the
   kinds marked "new blocks allowed" (questions, comparisons, processes, timelines, ...), with new unique IDs.
5. A **citation** is `[p.N: "exact words"]`: N is the printed page label shown in the source file's
   `======== PAGE N ========` marker; the words are copied exactly (case, punctuation and line breaks do not
   matter). Several citations may follow one claim. Quotes need at least 4 words.
6. `UNSURE: <reason>` replaces a value the book does not support. It is shown to the student as
   "not in the book" and listed in the report.
7. `skip: <reason>` inside a block means the item does not belong (e.g. bold used only for emphasis).
8. Never type the trust marks ✅ ⚠️ 💡; the scripts add them.

## Calculator lines

`calc:` lines are evaluated by the script. Numbers carry units in brackets; `=>` states the result, which is
recomputed and must agree to the precision you wrote.

```
calc: dT = 35.0[degC] - 20.0[degC] => 15.0[degC]
calc: q = 250[g] * 4.184[J/(g*degC)] * dT => 15690[J]
calc: q => 15.7[kJ]
```

- Operators: `+ - * / ^` and `sqrt() ln() log() exp() sin() cos() tan() abs()`, constants `pi`, `e`.
- Units: SI units with prefixes (`kg`, `mL`, `kJ`, `mol`, `kPa`...), `L`, `atm`, `bar`, `mmHg`, `cal`, `eV`,
  `min`, `h`, `degC` (or `°C`), `M` (mol/L), `%`, and compound units like `J/(g*degC)` or `m/s^2`.
- A Celsius value may only be added or subtracted; multiply with a difference (as above) or convert to kelvin.
- `check:` and `rearrange:` in formula blocks use the same syntax without units (`q = m * c * dT`); every
  rearranged form is tested numerically against the `check:` form.

## Block reference
'''


def build() -> str:
    parts = [INTRO]
    for kind, b in SCHEMAS.items():
        if b.worksheet:
            continue
        flag = " (new blocks allowed)" if b.new_ids_allowed else ""
        parts.append(f"### {kind}{flag}\n\n{b.help}\n\n```\n{format_help(kind)}\n```\n")
    parts.append("## Worksheet blocks (checker tasks)\n\nWorksheets are written by the script; fill only the "
                 "`<<FILL>>` lines and never change read-only lines.\n")
    for kind, b in SCHEMAS.items():
        if not b.worksheet:
            continue
        parts.append(f"### {kind}\n\n{b.help}\n\n```\n{format_help(kind)}\n```\n")
    return "\n".join(parts)


if __name__ == "__main__":
    target = ROOT / "exam-scribe" / "references" / "format.md"
    text = build()
    if "--check" in sys.argv:
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if current != text:
            print("references/format.md is out of date; run: python tools/gen_format_doc.py")
            sys.exit(1)
        print("format.md is up to date")
        sys.exit(0)
    target.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {target}")
