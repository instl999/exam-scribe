---
name: exam-scribe
description: Turn a textbook (PDF, scanned or not, EPUB, Markdown, text, or photos of its pages) into verified exam-prep material - recall-first study notes, self-tests with independently checked answer keys, Anki flashcards, review sheets, interleaved practice, a timed mock exam, a cheat sheet, a spaced study calendar and a verification report. Every claim quotes the book and is checked by scripts plus an independent pass, and step-by-step task cards keep smaller models reliable. Its scripts read PDFs in any language in seconds, so never OCR or page-render a text PDF yourself. Use this whenever someone wants to study or prepare for an exam from a textbook or course PDF, asks for notes, summaries, flashcards, practice questions, a mock exam or a study plan from a book or its chapters, or says things like "help me revise chapter 4", "make study notes from this PDF" or "quiz me on this book", even if they never say "exam".
compatibility: Needs a code-execution environment with Python 3.9+ and PyMuPDF (or pdfplumber / pypdf as a slower text-only fallback), markdown-it-py, mdit-py-plugins (genanki optional). Check with scripts/examscribe.py doctor.
license: MIT. Complete terms in LICENSE.txt
---

# ExamScribe

ExamScribe turns a textbook into study material a student can trust. The notes are
built for **recall** (questions first, answers hidden until tried), not for re-reading,
because self-testing and spaced review are what actually move exam scores. Every
factual line quotes the book with a page number, a script checks each quote and
recomputes every number, and a separate checker pass (with planted false claims to
test its attention) confirms each claim. Anything that cannot be confirmed is shown
with a warning, never hidden.

`SKILL` below means the folder this file is in. Run everything as `python SKILL/scripts/examscribe.py ...`, using
the Python command that works on this computer (`python`, `python3`, or `py -3` on Windows).

## The loop (this is the whole method)

The workflow has many steps; the scripts track all of them, so you never need to
remember where you are or decide what comes next.

```
python SKILL/scripts/examscribe.py next  <workspace>     # prints ONE task card
    ... do exactly what the card says ...
python SKILL/scripts/examscribe.py check <workspace>     # PASS -> next card; FAIL -> numbered fixes
```

Repeat until the card says `TASK done`. If you lose track (new session, long pause),
run `next` again: it always shows the current task. `status <workspace>` shows progress.

## Starting a new book

1. `python SKILL/scripts/examscribe.py doctor` - if packages are missing, ask the user before installing:
   `python -m pip install -r SKILL/requirements.txt` (a sandbox without network cannot install: ask the user to
   allow it or to run the command). If PyMuPDF cannot be installed, go on anyway: text PDFs are then read with
   pdfplumber or pypdf (slower, no figure pictures, no OCR).
2. Pick a workspace folder (default: `./exam-prep/<short-book-name>`), then:
   `python SKILL/scripts/examscribe.py init <workspace> --book <file> [--tier strict]`
   It detects the book's language (override with `--language xx`) and prints a quick check of the file:
   text layer or scans, contents, and how long it will take.
   (`probe <file>` prints the same check without creating a workspace.)
3. Start the loop. The first cards extract the book, ask the user about the exam, read scanned pages of the
   exam's chapters with OCR if there are any, and show a study plan.

**Do not open, render or OCR the book yourself, not even "to have a look".** A PDF with a text layer (nearly
every textbook PDF, in any language) needs no OCR: the scripts read its text directly, about a second for 200
pages. If you cannot read PDFs, that is fine: you never need to. When you need the book's text outside the task
cards (a user question before the workspace exists, for example), run
`python SKILL/scripts/examscribe.py extract <file> --pages 30-45` and read the Markdown file it writes. Only
scans without a text layer need OCR, and the `run-ocr` card handles those. If the book reached you only as page
images in the chat (no file on disk), ask the user for the file.

**Long commands** (`ingest` of a huge book, `ocr`) print progress. `ocr` stops by itself after about 9 minutes
and keeps every page it has read: if it prints `NOT FINISHED`, run the same command again. If your command tool
has a short time limit, run it in the background or with a longer timeout, and follow it with `status`.

## Rules that keep the output trustworthy

1. **The book is the only source.** Your own knowledge is never evidence: textbooks differ in
   definitions, notation and sign conventions, and the exam follows the course's book.
   Every claim ends with `[p.N: "exact words"]` copied from the source file the card names,
   where N is the number in the `======== PAGE N ========` marker above those words.
2. **Copy, do not paraphrase, definitions.** `definition:` is only the book's sentence in one citation.
3. **Never invent a number.** Put every computed number on a `calc:` line
   (`calc: q = 250[g] * 4.184[J/(g*degC)] * 15.0[degC] => 15690[J]`); the script recomputes it.
4. **UNSURE beats a guess.** If the book does not say it, write `UNSURE: <reason>`. A wrong note
   costs the student marks; a flagged gap only costs a minute of checking.
5. **Only scripts grant trust.** Never add ✅ ⚠️ 💡 marks, and never tell the user something is
   verified unless the report or a card says so.
6. **Do the card, nothing else.** Edit only the file in `EDIT`, with your file-editing tool (`apply_patch` in
   Codex, Edit in Claude Code; never shell commands: on Windows they destroy non-English text), keep every `:::`
   line and ID, and do not write ahead. On FAIL, fix exactly the listed lines. If attempts run out,
   `check --accept-flags` marks what still fails as UNSURE for a human; nothing is silently dropped. Never delete
   a block to get past a check.
7. **Do the reading and judging yourself.** Never write or run a program that fills drafts or worksheets:
   copying quotes into fields, generating questions or options, setting verdicts or spans. The only programs to
   run are the `examscribe.py` commands (shell commands that just read files are fine). A fill-in script cannot
   tell what the book means: its notes teach the student nothing and its verdicts vouch for nothing.
8. **Keep going; stop only for a reason.** After PASS, start the next card at once. Do not end your turn to report
   progress or to ask whether to continue. Stop only where a card says to talk to the user, at `TASK done`, or when
   your context or token budget runs low: then finish the current card, tell the user where you are, and stop -
   a new session continues with `next`. Never skip blocks, write minimal notes, or use `--accept-flags` early to
   save tokens.
9. **Checker tasks need fresh eyes.** Cards marked *fresh context* (claim checks, formula checks,
   blind solving, reconciling) should run in a subagent or a new session when you can start one:
   give it the card text. If you cannot, do them yourself but look only at the worksheet, never the
   drafts. Some claims in these worksheets are planted false claims; missing one means the batch is redone.
10. **Never touch the skill or the script-owned files.** Do not edit any file in SKILL, and do not edit, create
   or open the workspace's `state.json`, `.integrity.json`, top-level `source/` folder, `inventory/` or
   `verify/*.json` (`.keys.json` included). The files a card names under READ (such as
   `chapters/ch01/source/1.1.md`) and EDIT are yours to use. Before every command the scripts compare their own
   files and these records with what they wrote, and stop with `STOP:` if anything differs. Then run
   `restore <ws>`: it puts the scripts' version back, and the verification report lists the incident.

## Talking to the user

- **Intake card:** ask all its questions in one message; save answers with `config set`. If the user
  says "you decide", use the defaults printed on the card. For scanned books the scope decides how many
  pages are read with OCR, so ask precisely which chapters or pages the exam covers.
- **Chapter list after OCR:** for a scanned book without contents, the chapters are rebuilt from the OCR text;
  show them to the user and confirm with `outline <ws> --confirm` (or correct them, see the card).
- **Plan card:** show the plan (priorities with their reasons, time needed vs available); confirm with `plan --confirm`.
- **Chapter ready:** a card will tell you when a chapter is verified and built. Send the user the link
  right away so they can start studying while you continue.
- **Done:** give the index link, the flashcard and calendar files, and the report summary. Say how many
  items are marked ⚠ and that those should be checked in the book.
- If the user asks something mid-way ("quiz me", "what's on page 40?"), answer from the built pages or the
  book text via `find`/`page`, and say which page it comes from.

## Model tiers

The same checks run in every tier; weaker tiers get smaller tasks and more attention tests.

| Tier | Use for | Task size | Canaries | AI extras |
|---|---|---|---|---|
| `strict` (default) | small, local or untested models | one section (≤3.5k tokens of book text) | 3 per 12 claims | memory aids only |
| `standard` | capable mid-size models | larger sections | 3 per 20 claims | + analogies, exam tips |
| `frontier` | the strongest models | whole chapters when they fit | 3 per 30 claims | + extra examples |

Keep `strict` unless the user or operator says the model is frontier-class
(`config <ws> set tier frontier`). Details: `references/model-tiers.md`.

## When something goes wrong

| Problem | What to do |
|---|---|
| "I can't read this PDF" | you don't need to: `init` + `next`, or `extract <file>` for plain text. Never OCR a PDF that has text |
| Scanned PDF (flag `scanned-no-text`) or broken text layer (flag `garbled`, common in Arabic/Indic PDFs) | nothing special: a `run-ocr` card appears; it uses the OCR built into Windows, or Tesseract / RapidOCR. No engine for the language: the card lists the user's options (with their OK, `ocr-setup <ws>` downloads a few MB of Tesseract data and works on any computer) |
| Scan without page numbers in the file | the intake card says so: ask for pages as the PDF viewer numbers them; printed numbers are found once pages are read |
| Book as photos or scans of pages (JPG, PNG, TIFF), or a folder of them | `init <ws> --book <file-or-folder>` makes one PDF (pages in file-name order) and reads it like a scan. DjVu: the error message gives the conversion command |
| Processing feels slow | `status` shows progress; OCR only reads the exam scope, so narrow `scope.chapters` or `scope.pages` |
| Book not in English | nothing special: `init` detects the language (check the line it prints); extraction, key terms and the checkers' planted false claims work in other languages |
| Chapters detected wrongly | `outline <ws>` prints the outline; edit it and load it with `outline <ws> --from-text <file>` |
| A quote "not found" but you are sure | `find <ws> "a few words"` shows where the words really are (and the right page) |
| Draft damaged or rewritten (check says so, or blocks no longer match) | `restore-draft <ws>` puts the script's draft back (yours is kept as `.bak`); fill it in again |
| Formula text looks garbled | open the image named in the draft comment if you can see images; else `UNSURE: ...` |
| Password-protected or unreadable file | tell the user; ExamScribe cannot fix it |
| Huge book, little time | set `scope.chapters` (or `scope.pages 45-120`) to what the exam covers |
| `STOP: ... changed` | a script-owned file or the skill was edited. Workspace records: `restore <ws>`, then `next`. Skill files: undo the edit or reinstall the skill. Never edit them to get past a check |
| Permission, read-only or network errors (sandboxed agents such as Codex) | keep the workspace inside the folder you may write to (the default `./exam-prep/...` is); installing packages and `ocr-setup` need network: ask the user to allow it or to run the command |
| `python` not found | use `py -3` (Windows) or `python3`; the commands are the same |

## Commands

`next`, `check [--accept-flags]`, `status`, `restore-draft`, `restore`, `config <ws> show|get|set`, `plan [--confirm]`,
`add-material <ws> <file> --kind past-paper|syllabus|slides`, `find <ws> "words"`, `page <ws> <label> [--image]`,
`format <kind>`, `build [--pdf]`, `report`, `mistakes <ws> add|import|due`, `outline [--confirm|--from-text]`,
`probe <file>`, `extract <file>`, `ingest`, `ocr`, `ocr-setup`, `inventory`, `doctor`. Run `python SKILL/scripts/examscribe.py help`
for details.

## Reference files (read only when needed)

- `references/workflow.md` - every stage, what each file is for, how to recover a stuck workspace.
- `references/format.md` - the notes format and every block kind (or run `format <kind>`).
- `references/examples/` - finished, passing examples: read the one a card points to before writing.
- `references/verification.md` - how claims, formulas and answer keys are checked; canaries; fix rounds.
- `references/model-tiers.md` - the weak-model safeguards and why each exists.
- `references/question-design.md` - good questions, distractors and flashcards.
- `references/learning-science.md` - why the material is structured this way (for explaining it to users).
- `references/exam-formats.md` - how mcq, problem, short-answer, essay and open-book exams change the output.
- `references/materials.md` - using past papers, a syllabus or lecture slides.
- `references/ingest.md` - PDF extraction, speed, scanned books and OCR engines, math-heavy books (Marker/MinerU).
- `references/subjects/` - subject profiles (math-physics, chemistry, biology-medicine, history-social, law,
  computer-science, economics-business, languages, general).
