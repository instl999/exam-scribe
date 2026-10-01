# Past papers, syllabus and lecture slides

Instructor materials make priorities much more reliable. Add each file during intake (or any time):

```
python SKILL/scripts/examscribe.py add-material <ws> past-paper-2024.pdf --kind past-paper --label 2024
python SKILL/scripts/examscribe.py add-material <ws> syllabus.pdf --kind syllabus
python SKILL/scripts/examscribe.py add-material <ws> week3-slides.pdf --kind slides
```

PDF, TXT and Markdown work; PPTX needs `python-pptx` (or export the slides as PDF). Each file creates one
`map-material` task. The script does the searching; the model makes small choices from a closed list.

## Past papers (`--kind past-paper`)

- The paper is split into numbered questions (`1.`, `2)`, `Question 3`...). For each question the script
  ranks the book sections that share its key terms and words, and lists up to five as `candidates:`.
- Task: `pick:` 1-3 section numbers from the candidates (or `NONE`) and a one-line `reason:`.
- Effect: each hit raises that section's priority, and the plan shows it ("3 past-paper questions").

## Syllabus (`--kind syllabus`)

- Each syllabus line (three words or more) gets candidate sections.
- Task: `pick:` the sections the line covers, or `NONE`.
- Effect: listed sections get a priority boost; the plan names them ("listed in the syllabus").
  Use the result to discuss `scope.chapters` with the user.

## Lecture slides (`--kind slides`)

- For every key term from the book that appears in the slides, the worksheet shows the book's sentence and
  the slide's sentence side by side.
- Task: `verdict:` `CONSISTENT`, `DIFFERENT_NOTATION` (same idea, other symbols or names), `CONFLICT`
  (the slides say something different) or `NOT_RELATED`, plus a one-sentence `explain:`.
- Effect: differences appear on the concept card as an instructor note ("Your instructor's material says ...
  For the exam, follow your instructor.") and in the report. The book text is never overwritten.

## Why instructor material outranks the book (on scope and notation only)

Exams are written by the instructor. When the slides use different notation or a different convention,
the student must know both and use the instructor's on the exam. ExamScribe shows the conflict rather than
choosing silently; the facts in the notes still come from the book, with citations.
