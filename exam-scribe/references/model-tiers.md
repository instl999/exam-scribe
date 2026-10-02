# Model tiers and weak-model safeguards

ExamScribe is designed so that a small or local model produces notes close in quality to a frontier
model's. The method: move every decision that can be made by a script into a script, shrink what is left
into small, checkable tasks, and measure the model's diligence instead of trusting it.

## Contents
1. What changes between tiers
2. Weakness -> safeguard map
3. Choosing a tier
4. What a weaker model will still do worse

## 1. What changes between tiers

The checks are identical in every tier. Only the size of each task and the creative freedom change.

| Setting | strict (default) | standard | frontier |
|---|---|---|---|
| Book text per writing task | ~3,500 tokens (one section or part of one) | ~9,000 | ~30,000 (whole chapter when it fits) |
| Questions per section | 4 | 5 | 6 |
| Short-answer questions per section (hard to auto-check) | max 1 | max 2 | max 3 |
| Claims per checker worksheet | 12 + 3 canaries | 20 + 3 | 30 + 3 |
| Questions per blind-solve worksheet | 6 | 12 | 20 |
| Attempts before `--accept-flags` | 4 | 3 | 3 |
| AI-added extras (always labeled) | memory aids | + analogies, exam tips | + extra examples |
| Allowed share of skipped items | 25% | 35% | 40% |

Set it with `config <ws> set tier strict|standard|frontier`.

## 2. Weakness -> safeguard map

| Typical weakness | Safeguard | Where |
|---|---|---|
| Loses track of a long workflow | `next` prints exactly one self-contained task card; state lives in files, so any session can resume | pipeline.py |
| Ignores rules buried in a long prompt | each card repeats only the 5-7 rules for that task, next to the exact files and the command that must pass | task cards |
| Skips content | the skeleton already has one block per inventory item; deleting one fails the check; skips need a reason and are capped | skeleton.py, lint.py |
| Invents facts or citations | every claim needs a quote; the script finds it on the cited page or reports the real page / the closest real text | citations.py |
| Paraphrase drift in definitions | `definition:` must be the book's own sentence, matched exactly, and must name the term | lint.py |
| Invents or miscopies numbers | numbers in a claim must appear on the cited page or come from a `calc:` line | lint.py |
| Arithmetic and unit slips | `calc:` lines are recomputed with units (J vs kJ, °C differences); rearranged formulas are tested numerically | calc.py |
| Sloppy format | line-oriented format, auto-fix of harmless slips (curly quotes, `Option A:`, bullets, wrapped lines), and error messages with line, cause and fix | esm.py, lint.py |
| Loops forever on a hard item | attempt limits per task, then `--accept-flags` turns remaining problems into visible `UNSURE` items | pipeline.py |
| Rubber-stamps its own work | checking happens in separate worksheets that never show the writer's reasoning; fresh-context instruction; `span:` must be copied from the context | verify.py |
| Lazy checking | planted false claims (canaries) in every worksheet; one missed canary discards the worksheet | verify.py, mutate.py |
| Wrong or ambiguous answer keys | blind solving without the key; disagreements judged in a reconcile worksheet with its own canary | verify.py |
| Guesses when unsure | `UNSURE: <reason>` is always accepted (up to a cap) and shown honestly as a gap | lint.py, render.py |
| Adds outside knowledge | the book is the only source; AI extras only in labeled `ai-*` fields, restricted by tier | schema.py, tiers.py |
| Claims success too early | only `check` advances the state; the final report is computed from verdicts, not from the model's words | pipeline.py, report.py |
| Small context window | writing tasks are split at paragraph boundaries to fit the tier's budget; worksheets are small | skeleton.py |
| Cannot see images | formula checks accept `CANNOT_TELL`; such formulas are flagged, not trusted | verify.py |
| Ends its turn to report progress or to ask whether to continue | every card says "On PASS, start the next card right away"; stopping is only for user questions, `TASK done` or a full context | pipeline.py, SKILL.md |
| Writes its own program to fill drafts or worksheets | forbidden on every card; a SUPPORTED `span:` must share words with its claim and one span cannot serve many claims; `plain:` may not repeat the definition | pipeline.py, lint.py |
| Edits the checker or the records to get past a check | `scripts/integrity.json` lists the skill's files; script-owned workspace files are recorded as the scripts write them; any other change stops every command until `restore`, and the report lists the incident | integrity.py |
| Peeks at the canary keys | the cards forbid opening `verify/` files other than the worksheet; keys are stored salted and hashed (a deterrent, not a vault) | verify.py |
| Rewrites files with shell commands (non-English text destroyed) | damaged drafts are detected and `restore-draft` puts the script's version back | pipeline.py |

## 3. Choosing a tier

- Keep **strict** unless you know the model is frontier-class. Strict costs more steps, not more quality.
- Tiers describe capability, not vendor: the same rules hold for Claude, GPT, Gemini or local models. A large model
  run with low reasoning effort (a common default in coding agents) behaves like a smaller one: keep strict.
- **standard** suits capable mid-size models that pass the checks on the first or second attempt most of the time.
- **frontier** is for the strongest models; bigger tasks save time without weakening any check.
- A useful signal: the `canary_stats` in `chapters/chNN/verify/verdicts.json` and the number of `FAIL`s per task.
  Many rejected worksheets or repeated FAILs mean the tier is too loose for this model.

## 4. What a weaker model will still do worse

The safeguards stop errors from getting through; they do not make weak writing good. Expect from a weaker
model: blander explanations, fewer good misconceptions and comparisons, more `UNSURE` items, easier questions,
and more fix rounds. All of these show up in the report, so the student knows what to double-check.
