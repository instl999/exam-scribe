# Finished examples

These files are real outputs that passed every check, made from a short sample chemistry book used for
testing ("Foundations of Chemistry: Energy and Change"). Copy their style, not their content.

| File | Task | Shows |
|---|---|---|
| `section-example.md` | write-section | concepts with exact definitions, a formula with conditions, `check:` and rearrangements, a worked example with `calc:` lines (including a °C difference), a table and a figure, all four question types with `why-not` lines |
| `chapter-example.md` | write-chapter | overview, a must-know list covering every summary item, a concept map, four comparison tables, a strategy table |
| `verify-example.md` | verify-claims | SUPPORTED with a copied span; PARTIAL for a dropped qualifier; CONTRADICTED for a changed number; NOT_SUPPORTED for a swapped term |
| `solve-example.md` | solve | mcq with only-one-correct, cloze, true/false, numeric with a calc line |
| `reconcile-example.md` | reconcile | MINE_WRONG when the independent answer was wrong; KEY_WRONG for a wrong key |

Notice what good notes do:

- Each claim is short and ends with the smallest quote that proves it.
- Conditions are kept ("without changing phase", "at constant pressure").
- Every number is either printed in the book or produced by a `calc:` line.
- `UNSURE:` is used when the book is silent, e.g. `holds-when: UNSURE: the book gives no conditions for this formula`.
- Wrong mcq options are plausible mistakes, and each has a `why-not` line.
