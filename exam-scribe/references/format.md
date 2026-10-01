# Notes format (ExamScribe Markdown)

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

### concept

A key term: definition quoted exactly, explained simply, with evidence.

```
::: concept T-<term>
<!-- A key term: definition quoted exactly, explained simply, with evidence. -->
term: <required, max 10 words>  The term exactly as the book writes it.
term-original: <optional, max 10 words>  Only when notes are in another language: the term exactly as the book writes it.
skip: <optional, max 40 words>  Only if this is not really a key term (e.g. bold used for emphasis). Give the reason.
definition: <required, exactly one citation, nothing else>  The book's own defining sentence, copied exactly, as [p.N: "..."].
definition-translation: <optional, must end with [p.N: "exact words"], max 80 words>  Only when notes are in another language: your translation of the definition, cited.
plain: <required, must end with [p.N: "exact words"], max 60 words>  One or two sentences in simple words, ending with a citation.
why: <optional, must end with [p.N: "exact words"], max 60 words>  Why it matters or why it is true, cited.
example: <optional, up to 2 lines, must end with [p.N: "exact words"], max 60 words>  An example from the book, cited.
misconception: <optional, up to 2 lines, must end with [p.N: "exact words"], max 70 words>  'Wrong: <mistake students make> | Right: <what the book says> [p.N: "..."]'.
figure: <optional, up to 2 lines>  ID of a figure or table that illustrates this term.
cue: <optional, max 25 words>  Optional recall question for this card (default: 'What is <term>?').
ai-mnemonic: <optional, max 50 words>  AI-added memory aid (all tiers). Shown with a 'not from the book' label. No citation.
ai-analogy: <optional, max 50 words>  AI-added analogy (standard and frontier tiers). Shown with a 'not from the book' label. No citation.
ai-tip: <optional, max 50 words>  AI-added exam tip (standard and frontier tiers). Shown with a 'not from the book' label. No citation.
ai-example: <optional, max 50 words>  AI-added extra example (frontier tier). Shown with a 'not from the book' label. No citation.
:::
```

### formula

A formula: LaTeX, symbols with units, when it holds, and a script-checkable form.

```
::: formula EQ-<number>
<!-- A formula: LaTeX, symbols with units, when it holds, and a script-checkable form. -->
name: <required, max 12 words>  What the formula is for.
skip: <optional, max 40 words>  Only if this is not a real formula. Give the reason.
latex: <required>  The formula in LaTeX, same symbols as the book, e.g. q = m c \Delta T
where: <required, must end with [p.N: "exact words"], max 90 words>  Each symbol = meaning (unit); separated by ';' and cited.
holds-when: <required, must end with [p.N: "exact words"], max 45 words>  Conditions or assumptions the book states, cited. If the book states none: UNSURE: not stated.
source: <required, exactly one citation, nothing else>  Quote the sentence or line that gives the formula.
check: <optional>  The formula in calculator syntax, e.g. q = m * c * dT
rearrange: <optional, up to 4 lines>  Rearranged forms in calculator syntax, e.g. dT = q / (m * c)
example: <optional, must end with [p.N: "exact words"], max 60 words>  How the book uses it, cited.
ai-tip: <optional, max 50 words>  AI-added exam tip (standard and frontier tiers). Shown with a 'not from the book' label. No citation.
ai-mnemonic: <optional, max 50 words>  AI-added memory aid (all tiers). Shown with a 'not from the book' label. No citation.
:::
```

### worked-example

A worked example from the book, with every calculation recomputed by the script.

```
::: worked-example WE-<number>
<!-- A worked example from the book, with every calculation recomputed by the script. -->
title: <required, max 14 words>
skip: <optional, max 40 words>  Only if this is not a worked example. Give the reason.
source: <required, must end with [p.N: "exact words"]>  Where the example is, quoting its first words.
problem: <required, must end with [p.N: "exact words"], max 90 words>  The problem as the book states it.
step: <required, up to 12 lines, at least 1, citations allowed, max 55 words>  One solution step per line, in order. Numbers must come from the problem or a calc: line.
calc: <optional, up to 14 lines>  Calculator line: 'dT = 35.0[degC] - 20.0[degC]' or 'q = m * c * dT => 15690[J]'.
result: <required, must end with [p.N: "exact words"]>  The book's final answer, cited.
:::
```

### figure

A figure or table from the book (the image itself is cropped from the PDF).

```
::: figure FIG-<number>
<!-- A figure or table from the book (the image itself is cropped from the PDF). -->
what: <required, must end with [p.N: "exact words"], max 50 words>  What the figure/table shows, cited.
look-for: <optional, up to 3 lines, must end with [p.N: "exact words"], max 40 words>  Detail worth noticing, cited.
skip: <optional, max 40 words>  Only if the figure is decorative. Give the reason.
:::
```

### question (new blocks allowed)

A self-test question with a verified answer key.

```
::: question Q-<section>-<nn>
<!-- A self-test question with a verified answer key. -->
type: <required one of: mcq | tf | numeric | cloze | short>
bloom: <required one of: remember | understand | apply | analyze | evaluate>
skip: <optional, max 40 words>  Only if the section cannot support another question.
ask: <required, max 90 words>  The question. Cloze: include ____ for the blank.
option a: <optional, max 30 words>
option b: <optional, max 30 words>
option c: <optional, max 30 words>
option d: <optional, max 30 words>
answer: <required>  mcq: A-D; tf: true/false; numeric: number[unit]; cloze: the missing word(s); short: <=60 words.
accept: <optional, up to 4 lines, max 20 words>  Other acceptable answers (cloze/short).
tolerance: <optional>  numeric only, e.g. 1% (default: rounding of the stated answer).
why: <required, must end with [p.N: "exact words"], max 70 words>  Why the answer is right, with the book's evidence.
why-not a: <optional, citations allowed, max 40 words>
why-not b: <optional, citations allowed, max 40 words>
why-not c: <optional, citations allowed, max 40 words>
why-not d: <optional, citations allowed, max 40 words>
calc: <optional, up to 10 lines>  numeric: the calculation that produces the answer.
covers: <optional>  IDs this question tests (LO-..., T-..., EQ-...).
:::
```

### compare (new blocks allowed)

A side-by-side table of two easily confused ideas.

```
::: compare CMP-<chapter>-<nn>
<!-- A side-by-side table of two easily confused ideas. -->
items: <required>  The two things compared: 'T-endothermic-process | T-exothermic-process' (IDs or names).
row: <required, up to 8 lines, at least 2, every cell after the first cited, max 70 words>  'aspect | fact about first [p.N: "..."] | fact about second [p.N: "..."]'
skip: <optional, max 40 words>
:::
```

### map

A concept map: each arrow is a cited claim.

```
::: map <chapter id>
<!-- A concept map: each arrow is a cited claim. -->
link: <required, up to 24 lines, at least 3, must end with [p.N: "exact words"]>  'T-a -> T-b | how they relate [p.N: "..."]' using IDs from this chapter.
:::
```

### must-know

The chapter's must-know list, checked against the book's own summary.

```
::: must-know <chapter id>
<!-- The chapter's must-know list, checked against the book's own summary. -->
point: <required, up to 12 lines, at least 4, must end with [p.N: "exact words"], max 45 words>  A must-know fact, cited, ending with (covers: SUM-...) for the summary items it covers.
:::
```

### overview

One-screen overview used in the course map.

```
::: overview <chapter id>
<!-- One-screen overview used in the course map. -->
answers: <required, must end with [p.N: "exact words"], max 60 words>  The questions this chapter answers, cited (use the intro or objectives).
big-picture: <required, must end with [p.N: "exact words"], max 70 words>  How the chapter fits the course, cited.
:::
```

### process (new blocks allowed)

An ordered process (biology pathways, lab procedures, mechanisms).

```
::: process PR-<nn>
<!-- An ordered process (biology pathways, lab procedures, mechanisms). -->
name: <required, max 12 words>
step: <required, up to 14 lines, at least 2, must end with [p.N: "exact words"], max 45 words>
:::
```

### timeline (new blocks allowed)

Dated events in order.

```
::: timeline TL-<nn>
<!-- Dated events in order. -->
name: <required, max 12 words>
event: <required, up to 20 lines, at least 2, must end with [p.N: "exact words"], max 45 words>  '1789 | what happened [p.N: "..."]'
:::
```

### chain (new blocks allowed)

Cause-and-effect chain.

```
::: chain CAUSE-<nn>
<!-- Cause-and-effect chain. -->
name: <required, max 12 words>
link: <required, up to 12 lines, at least 1, must end with [p.N: "exact words"], max 45 words>  'cause -> effect [p.N: "..."]'
:::
```

### rule (new blocks allowed)

A legal or formal rule with elements, exceptions and cases.

```
::: rule RU-<nn>
<!-- A legal or formal rule with elements, exceptions and cases. -->
name: <required, max 12 words>
rule: <required, must end with [p.N: "exact words"], max 70 words>
element: <optional, up to 10 lines, must end with [p.N: "exact words"], max 45 words>
exception: <optional, up to 6 lines, must end with [p.N: "exact words"], max 45 words>
case: <optional, up to 6 lines, must end with [p.N: "exact words"], max 45 words>
:::
```

### trace (new blocks allowed)

A code-tracing exercise (code goes in one fenced block).

```
::: trace TR-<nn>
<!-- A code-tracing exercise (code goes in one fenced block). -->
ask: <required, max 40 words>
lang: <required>
output: <required>  Exact output. Use \n for line breaks.
why: <required, must end with [p.N: "exact words"], max 60 words>
:::
```

### strategy

Problem-solving strategy table.

```
::: strategy <chapter id>
<!-- Problem-solving strategy table. -->
row: <required, up to 10 lines, at least 2, every cell after the first cited, max 60 words>  'when you see ... | what to do [p.N: "..."]'
:::
```

### outline (new blocks allowed)

An essay answer outline.

```
::: outline OUT-<nn>
<!-- An essay answer outline. -->
prompt: <required, max 40 words>
thesis: <required, must end with [p.N: "exact words"], max 45 words>
point: <required, up to 8 lines, at least 2, must end with [p.N: "exact words"], max 45 words>
counter: <optional, up to 2 lines, must end with [p.N: "exact words"], max 45 words>
:::
```

## Worksheet blocks (checker tasks)

Worksheets are written by the script; fill only the `<<FILL>>` lines and never change read-only lines.

### claim

Verify one claim against the book text.

```
::: claim <ID>
<!-- Verify one claim against the book text. -->
claim: (written by the script, do not change)
context: (written by the script, do not change)
verdict: <required one of: SUPPORTED | PARTIAL | NOT_SUPPORTED | CONTRADICTED>
span: <required>  Exact words copied from CONTEXT that support the claim, or NONE.
problem: <optional>  If not SUPPORTED: what is wrong, in one sentence.
:::
```

### formula-check

Check a LaTeX transcription against the book's formula.

```
::: formula-check <ID>
<!-- Check a LaTeX transcription against the book's formula. -->
latex: (written by the script, do not change)
book-line: (written by the script, do not change)
image: (written by the script, do not change)
verdict: <required one of: MATCH | MISMATCH | CANNOT_TELL>
problem: <optional>
:::
```

### solve

Answer a question without seeing the key.

```
::: solve <ID>
<!-- Answer a question without seeing the key. -->
type: (written by the script, do not change)
question: (written by the script, do not change)
option a: (written by the script, do not change)
option b: (written by the script, do not change)
option c: (written by the script, do not change)
option d: (written by the script, do not change)
context: (written by the script, do not change)
answer: <required>
only-one-correct: <optional one of: yes | no>
evidence: <required>  Exact words from CONTEXT that decide the answer.
calc: <optional, up to 10 lines>
:::
```

### reconcile

Compare an answer key with an independent answer.

```
::: reconcile <ID>
<!-- Compare an answer key with an independent answer. -->
question: (written by the script, do not change)
key-answer: (written by the script, do not change)
your-answer: (written by the script, do not change)
context: (written by the script, do not change)
judgement: <required one of: SAME | KEY_WRONG | MINE_WRONG | AMBIGUOUS>
reason: <required, max 60 words>
:::
```

### map-question

Map a past exam question to book sections.

```
::: map-question <ID>
<!-- Map a past exam question to book sections. -->
question: (written by the script, do not change)
candidates: (written by the script, do not change)
pick: <required>  1-3 IDs from CANDIDATES, or NONE.
reason: <required, max 40 words>
:::
```

### conflict

Compare the instructor's material with the book.

```
::: conflict <ID>
<!-- Compare the instructor's material with the book. -->
term: (written by the script, do not change)
book: (written by the script, do not change)
slides: (written by the script, do not change)
verdict: <required one of: CONSISTENT | DIFFERENT_NOTATION | CONFLICT | NOT_RELATED>
explain: <required, max 50 words>
:::
```

### scope-item

Map a syllabus line to book sections.

```
::: scope-item <ID>
<!-- Map a syllabus line to book sections. -->
syllabus: (written by the script, do not change)
candidates: (written by the script, do not change)
pick: <required>  Section IDs from CANDIDATES, or NONE.
:::
```
