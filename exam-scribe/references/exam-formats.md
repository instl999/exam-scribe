# How the exam format changes the output

Set with `config <ws> set exam.formats mcq,short-answer,problems,essay` and
`config <ws> set exam.book_policy closed|open|cheat-sheet`.

| Setting | Effect on skeletons and outputs |
|---|---|
| `mcq` | more mcq slots; distractor explanations required; mock exam weighted to mcq/tf |
| `problems` | numeric questions with `calc:` lines in every section with formulas or examples; a `strategy` table per chapter ("when you see ... do ..."); worked examples get faded "your turn" copies; mock exam weighted to numeric |
| `short-answer` | cloze and short questions; must-know list phrased as answer-ready statements |
| `essay` | an `outline` block per chapter (prompt, thesis, cited points, counterpoint); short questions |
| `closed` book | emphasis on flashcards and recall mode; memory aids allowed (`ai-mnemonic`, labeled as AI-added) |
| `open` book | adds a lookup index (term -> book page -> notes) for finding things fast during the exam |
| `cheat-sheet` | the cheat sheet page is designed to be rewritten by hand onto the one allowed sheet |

Other settings:

- `exam.date`: the calendar counts back from it (without a date, a 4-week plan is assumed).
- `exam.duration_minutes` and `exam.question_count`: size and timer of the mock exam.
- `scope.chapters`: only these chapters are processed; use it for partial exams or when time is short.

If the formats change after writing started, existing drafts are kept; only new skeletons follow the change.
