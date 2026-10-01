# Brief for the Haiku trial run (what the subagent is told)

The brief given to a small model (Claude Haiku) for the end-to-end trial in `docs/EVALUATION.md`. Fill in the
angle-bracket placeholders for your own computer and book; the answers below are the ones used in the trial.

You are an AI agent helping a university student prepare for an exam. The student gave you a textbook PDF and
asked for exam-prep study material. You have the ExamScribe skill for exactly this.

- Skill folder (SKILL below): `<repo>\exam-scribe` - read SKILL.md there first and follow it
  exactly. It tells you everything: the next/check loop, the rules, and when to talk to the user.
- Python: `<python.exe>` (use this full path; `python` may not be on PATH). Example:
  `& "<python.exe>" "<repo>\exam-scribe\scripts\examscribe.py" next "<workspace>"`
- Shell: Windows PowerShell. Quote paths. The book path contains Chinese characters.
- Book: `<book.pdf>` (in the trial: a scanned Chinese communication-studies textbook, 292 pages)
- Workspace to create: `<repo>\trials\<workspace>`

The student cannot be reached during this run, so here are their answers to anything the skill tells you to ask:
- Exam date: 2026-12-18. Question formats: short-answer, essay and multiple choice. Closed book.
- What the exam covers: only Chapter 1 (第一章), printed pages 1-16 of the book.
- Subject: communication studies (a social science). Study time: 3 hours per day.
- Notes language: Chinese (zh), the book's language. No past papers, syllabus or slides.
- If you are shown a detected chapter list: it is right if it has Chapter 1 (第一章) with its sections
  (第一节, 第二节, 第三节); then confirm it. Otherwise report the problem instead of guessing.
- If you are shown a study plan: the student accepts it.

Work until a task card says `TASK done`. Do not stop early to ask whether to continue. Do not edit any file of
the skill itself (scripts, references); if a script fails with an error, stop and report the exact command and
error. At the end, report: the final `status` output, the `report` summary, the path of the study site index,
how many task cards you did, and every problem or confusing instruction you ran into (task id + what happened).
