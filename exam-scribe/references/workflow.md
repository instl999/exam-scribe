# Workflow reference

Read this when something looks stuck, when you need to explain the process to the user,
or when you are orchestrating several subagents. In normal use, `next` and `check` are enough.

## Contents
1. Stages
2. The workspace folder
3. Task kinds
4. Recovering and redoing things
5. Fixing the outline
6. Running tasks in parallel (orchestrators)

## 1. Stages

| # | Stage | Who | What happens |
|---|---|---|---|
| 1 | `init` | model runs a command | workspace created, book copied into `source/`, quick check of the file printed |
| 2 | `run-ingest` | model runs a command | text, page labels, outline, figure positions and quality flags are extracted (seconds) |
| 3 | inventory | automatic | per-chapter checklist: key terms, equations, figures, examples, objectives, summary sentences |
| 3a | `run-ocr` | model runs a command | only for scanned books small enough to read whole in ~2 minutes |
| 4 | `intake` | model asks the user | exam date, formats, book policy, scope (chapters or pages), subject, hours per day, language, materials |
| 4a | `run-ocr` / `need-ocr-engine` | model runs a command / asks the user | scanned pages of the exam scope are read with OCR (resumable) |
| 4b | `confirm-outline` | model asks the user | only when the chapter list was rebuilt from OCR text |
| 5 | `map-material` | model (worksheet) | only if past papers / syllabus / slides were added |
| 6 | `confirm-plan` | model asks the user | priorities with reasons, time needed vs available |
| 7 | per chapter: `write-section` | writer | one task per section (or section part); the chapter's figure and equation pictures are made first |
| 8 | per chapter: `write-chapter` | writer | overview, must-know list, concept map, comparisons, strategy/outline blocks |
| 9 | per chapter: `verify-claims` | checker, fresh context | claim worksheets with planted false claims |
| 10 | per chapter: `verify-formulas` | checker, fresh context | LaTeX vs. the printed formula |
| 11 | per chapter: `solve` | solver, fresh context | every question answered without the key |
| 12 | per chapter: `reconcile` | judge, fresh context | key vs. independent answer when they differ |
| 13 | per chapter: `fix` | writer | revise what the checks rejected (at most two fix attempts per place) |
| 14 | per chapter: notify | model tells the user | the chapter's pages are built; the student can start |
| 15 | `done` | model tells the user | everything built: index, practice, mock exam, cheat sheet, deck, calendar, report |

Chapters are processed in plan order. Each chapter is delivered as soon as it is verified,
so the student can study chapter 1 while later chapters are still being written.

## 2. The workspace folder

```
<workspace>/
  examscribe.json          settings (change them only with `config set`)
  state.json               pipeline state (script-owned)
  source/                  book copy, pages.jsonl, outline.json, quality.json, figures.json;
                           figures/, equations/, page-images/ (pictures, made per studied chapter);
                           ocr/pNNNN.json (OCR text per scanned page, kept across runs)
  inventory/chNN.json      the checklist per chapter (script-owned)
  chapters/chNN/
    source/<part>.md       the book text for one writing task (read this)
    draft/<part>.md        the notes you write (edit this); draft/chapter.md for chapter blocks
    verify/*.md            worksheets for checker tasks (edit only the <<FILL>> lines)
    verify/verdicts.json   results of all checks (script-owned)
  materials/<name>/        past papers, syllabus, slides and their worksheets
  site/                    the study website (index.html is the start page)
  export/                  flashcards.apkg / .tsv, study-plan.ics / .md, obsidian/*.md, verification-report.md, pdf/
  progress/mistakes.json   the student's mistake log
```

The drafts are the source of truth. Everything in `site/` and `export/` is rebuilt from them.

## 3. Task kinds

- **Writer tasks** (`write-section`, `write-chapter`, `fix`): fill `<<FILL ...>>` slots in a draft. The skeleton
  already contains one block per inventory item, the right IDs, hints quoting the likely sentence, and
  question slots with a type and Bloom level. Delete `<<OPTIONAL ...>>` lines you do not use.
- **Checker tasks** (`verify-claims`, `verify-formulas`, `solve`, `reconcile`): fill verdicts in a worksheet.
  They are marked *fresh context* because a checker that saw the draft tends to agree with it.
- **User tasks** (`intake`, `confirm-outline`, `need-ocr-engine`, `confirm-plan`, notify, `done`): talk to the
  user, then run the command on the card.
- **Runner tasks** (`run-ingest`, `run-ocr`): run one command. `ocr` stops by itself after about 9 minutes and
  prints `NOT FINISHED` if pages are left: run it again (finished pages are kept). Run it in the background if
  your command tool has a shorter time limit, and watch `status`.

## 4. Recovering and redoing things

- **Lost track:** `next` always prints the current task. `status` shows every chapter.
- **A draft was edited after it passed** (for example during a fix): the next `next` re-checks it silently;
  if it no longer passes, you get the write task again with the errors.
- **A worksheet was rejected** (a planted false claim was marked SUPPORTED): it is regenerated with new
  items automatically. Do it again, carefully. After the tier's attempt limit the claims stay "unverified".
- **Out of attempts on a writer task:** `check --accept-flags` turns what still fails into `UNSURE` / `skip`
  lines that are listed in the report for a human.
- **Settings changed after writing started** (e.g. exam formats): existing drafts are kept. Only new
  skeletons use the new settings.
- **Start a chapter over:** delete `chapters/chNN/` and remove the chapter from `state.json` under
  `chapters` (ask the user first: this discards finished work).

## 5. Fixing the outline

If the book has no usable bookmarks, chapters are guessed from headings and the intake card warns you.
Print the current outline, edit it, and load it back:

```
python SKILL/scripts/examscribe.py outline <ws>                  # prints the outline in the format below
python SKILL/scripts/examscribe.py outline <ws> --from-text outline.txt
```

```
chapter ch01 | 1 | Energy and Its Units
  section 1.1 | 1 | What Is Energy?
  section 1.2 | 3 | Units of Energy
  end ch01-end1 | 4 | Key Terms
chapter ch02 | 6 | Thermochemistry
  section 2.1 | 6 | Heat and Temperature
other | 15 | Answer Key
```

Columns: kind and ID, the printed page label where the part starts, and the title (used to find the exact
position on that page). `end` marks end-of-chapter material (key terms, summary, exercises): it feeds the
inventory but gets no writing task. Loading an outline resets the inventory and all chapter progress.
An outline loaded this way is kept when the book is extracted again (for example after OCR).

For a scanned book without bookmarks, the chapter list is rebuilt from the OCR text after the exam's pages are
read, and a `confirm-outline` card asks the user to check it: `outline <ws> --confirm` accepts it. If the
exam scope was given as chapters of an earlier guess, it is kept as the same page ranges (`scope.pages`).

## 6. Running tasks in parallel (orchestrators)

A strong orchestrating model may run independent tasks in parallel subagents: sections of different
chapters, or verification of one chapter while another is being written. The state machine hands out one
task at a time, so the simplest safe pattern is: run `next`, give the card to a subagent, run `check` when it
reports back, repeat. Two subagents must never edit the same file. Checker tasks should always go to a
subagent that has not seen the drafts.
