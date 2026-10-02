# Verification reference

How ExamScribe decides what to trust, and how to do the checker tasks well.

## Contents
1. Layers of checking
2. Claim checks (verify-claims)
3. Formula checks (verify-formulas)
4. Blind solving and reconciling (solve, reconcile)
5. Fix rounds
6. Trust marks shown to the student

## 1. Layers of checking

| Layer | Done by | Catches |
|---|---|---|
| Quote check | script | quotes that are not in the book, or are on another page (it names the right page) |
| Number check | script | numbers in a claim that appear neither on the cited page nor in a `calc:` line |
| Calculator | script | arithmetic and unit errors in every `calc:` line; wrong rearranged formulas |
| Coverage | script | inventory items without a block, objectives without a question, summary items missing from must-know |
| Claim check | independent checker + canaries | claims that twist, over-generalise or drop a condition from what the quote says |
| Formula check | independent checker + canary | LaTeX that differs from the printed formula |
| Blind solve | independent solver | wrong or ambiguous answer keys |
| Reconcile | independent judge + canary | who is right when key and independent answer differ |

Scripts cannot judge meaning, and models are unreliable judges of their own work. So every claim is
checked twice in different ways: mechanically (the words exist, the numbers exist, the math is right), and
semantically by a separate pass that did not write it.

## 2. Claim checks

Each item shows a `claim:` and a `context:`, the book text around the cited quote (a neighbouring short
paragraph such as an equation line is included). Judge only from the context.

| Verdict | Use when | Example |
|---|---|---|
| `SUPPORTED` | the context says the same thing, including numbers, signs, direction and conditions | claim "Energy changes form but is never created or destroyed" vs. "it is never created or destroyed" |
| `PARTIAL` | the idea is right but a condition or qualifier is missing, added or changed, or the claim says more than the context | claim "more mass means more kinetic energy" vs. context "depends on both its mass and its speed" (direction not stated) |
| `NOT_SUPPORTED` | the context does not say it | claim about "calories" when the context is about energy |
| `CONTRADICTED` | the context says the opposite or a different number | "1 kJ = 1010 J" vs. "1 kJ = 1000 J" |

- For `SUPPORTED`, copy at least 3 words from the context into `span:`: the words that say what this claim says.
  The script checks that the span is in the context, that it shares words with the claim, and that one span is not
  pasted under more than three claims, so a rubber-stamp (or a script that fills spans) is detected.
- Judge every block by reading it; never let a program fill the worksheet, and never open `.keys.json` or the other
  files in `verify/`.
- For anything else write `span: NONE` and one sentence in `problem:` saying what is wrong. The writer will see it.
- Claims that repeat their whole quote word for word are verified automatically and never reach you.
- **Canaries.** Every worksheet contains a few planted false claims made by changing a real one: a number
  (4.184 → 4.148), an opposite (absorbs → releases), a negation, a quantifier (always → sometimes), or a
  different term. If any canary is marked `SUPPORTED`, the whole worksheet is discarded and regenerated with new
  items. After the tier's attempt limit, its claims stay "unverified" and are listed for a human.
  Canaries are never related terms (energy / thermal energy), so a careful checker is never punished.
  Opposites, quantifiers and negations exist for English, German, French, Spanish, Italian, Portuguese,
  Russian, Chinese, Japanese, Korean, Arabic and Hindi (`能量不是…`, `Energie ist nicht…`); numbers and term swaps
  work in any language. When a claim cannot be changed safely, a real claim is shown next to an unrelated
  passage from elsewhere in the book, so every worksheet keeps its attention test in every language.

## 3. Formula checks

`MATCH` only if symbols, signs, powers, fractions and subscripts agree. `book-line` is extracted text:
subscripts appear as `_x`, superscripts as `^x`, and some symbols may be garbled. If you can view images,
open `image:` and compare with the printed formula. `CANNOT_TELL` is honest when the text is garbled and you
cannot see the image; the formula is then shown to the student with a warning. One item is a deliberately
wrong formula.

## 4. Blind solving and reconciling

- The solver sees each question with the book context, never the key. mcq: one letter and
  `only-one-correct: yes|no`. numeric: `answer: 15.7[kJ]` plus `calc:` lines. `evidence:` quotes the context.
- The script compares answers: exact for mcq/tf, 1% for numeric, normalised text for cloze. Short answers
  and disagreements go to **reconcile**, where the judge sees the key and the independent answer side by side:
  `SAME`, `KEY_WRONG`, `MINE_WRONG` or `AMBIGUOUS`. One item is a planted wrong key; accepting it
  (`SAME` / `MINE_WRONG`) discards the worksheet.
- `only-one-correct: no` (two defensible options) makes the question disputed even if the letters match:
  ambiguous questions train guessing.
- Changing only a question's `why:` does not trigger re-solving; changing the question, options or answer does.

## 5. Fix rounds

Rejected claims, mismatched formulas and disputed questions come back to the writer as a `fix` task, with the
checker's reason and the book text. The writer corrects the line (better quote, restored condition, corrected
number) or marks it `UNSURE:`. Changed items are verified again. Rejections are counted per place in the
notes, not per wording: after the third rejection at the same place it stops being sent back and stays marked
for a human. This bounds the work and prevents endless rewording.

## 6. Trust marks shown to the student

| Mark | Meaning |
|---|---|
| ✓ | quote found on the cited page by the script, and the claim confirmed by the independent checker |
| ⚠ | rejected and not fixed, approximate quote, doubtful page (scanned/garbled), unverified after failed attention tests, or a disputed answer key (hover for the reason) |
| ○ | not verified yet |
| 💡 | AI-added memory aid or tip; not from the book |

Only verified questions go into practice sets, the mock exam and the Anki deck (unless
`anki.include_unverified` is true). The verification report lists every ⚠ item with its file, line and page.
