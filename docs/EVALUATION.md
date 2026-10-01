# Evaluating ExamScribe

**English** | [简体中文](EVALUATION.zh-CN.md)

Four levels, from cheapest to most realistic.

## 1. Automated tests (seconds)

```
cd tests
python -m unittest
```

The suite (144 tests) builds a 19-page sample textbook (`tests/fixtures/make_book.py`: bookmarks, roman front matter,
running headers, bold terms, split equation numbers, subscripts, ligatures, a hyphenated line break, boxes,
vector and raster figures, a table, an answer key and a scanned page) and checks extraction, inventory, the
calculator, the notes format, quote checking, every linter rule for typical weak-model mistakes, canaries,
the whole pipeline (including a lazy checker being rejected and a fix loop), and every output file.

## 2. Mutation testing of the checks (a minute)

```
python tools/mutation_eval.py
```

Plants realistic errors into notes that passed every check and counts how many the deterministic layer
catches. Current results on the sample drafts:

| Planted error | Caught |
|---|---|
| changed number in a claim | 72 / 72 |
| wrong result on a `calc:` line | 12 / 12 |
| wrong page in a citation | 127 / 128 (the miss: identical words on both pages) |
| paraphrased quote | 124 / 126 (the misses: the edit landed in the claim text, not the quote) |

Errors that keep quotes and numbers intact (a swapped term, a dropped condition, a reversed implication)
need the independent checker. To measure a model in the checker role:

```
python tools/mutation_eval.py --worksheet checker-test.md    # 40 real claims + 20 planted errors
# give checker-test.md to the model under test with the verify-claims card rules, then:
python tools/mutation_eval.py --score checker-test.md
```

It reports the catch rate per error type and how many real claims the model wrongly rejected.

## 3. A real textbook (hours)

OpenStax textbooks are free, peer-reviewed and openly licensed (most are CC BY 4.0; check the license on
the book's page). Their chapters end with key terms, key equations, summaries and review questions, which
give ready-made ground truth. Good choices: *Chemistry 2e* (chapter 5, Thermochemistry, overlaps the sample
book), *University Physics Volume 1* (chapters 2-3), *Biology 2e* (chapter 4), *Principles of Economics 3e*.

1. Download the PDF from openstax.org (the user must do this or approve the download).
2. `python exam-scribe/scripts/examscribe.py init ws-<model> --book <file.pdf> --tier strict`
3. Run the loop with the model under test until `done` (limit scope to 1-2 chapters to save time).
4. `python tools/eval_metrics.py ws-<model>`
5. Audit by hand: 20 random verified claims (are they true to the book?) and every flagged item.

Suggested bar for "good enough to hand to a student":

| Metric | Target |
|---|---|
| glossary terms, key equations, summary sentences covered | >= 95% |
| claims verified | >= 90%, flagged <= 10% |
| canary catch rate | >= 95% (lower: use a stricter tier or a stronger checker model) |
| answer keys disputed | <= 5% |
| hand audit of verified claims | >= 98% correct |

Compare models or tiers on the same chapters: the metrics are directly comparable.

### Scanned books

To measure OCR, make an image-only copy of a text PDF (render every page at 150-300 dpi and insert the images
into a new PDF, without the text layer and, to test outline guessing, without bookmarks), run the pipeline on
it, and compare the extracted text page by page with a workspace made from the original. Results so far
(Windows OCR engine, 200 dpi):

| Input | Characters | Words | Numbers kept | Outline |
|---|---|---|---|---|
| sample book, 150-dpi scan | 98.5% | 95.4% | 94% (132/141) | chapters and sections as in the bookmarks |
| 120 generated pages, 300-dpi noisy scan | 99.7% | 99.0% | 91% (324/355) | chapters and sections as in the bookmarks |

Key terms without bold (found from defining sentences): 14 of 18 on the sample book, no false terms. These
books were made for testing; a real scanned textbook (with photos, tables and formulas) will do worse, which is
why claims with numbers from OCR pages are always flagged for a human check.

### Other languages

`tests/fixtures/lang_books.py` writes the same small chemistry book as a text PDF in Chinese, Japanese, Korean,
Russian, German, French, Spanish, Arabic and Hindi (bookmarks, bold terms, figures, equations, examples,
end-of-chapter parts, printed page numbers); `tests/test_languages.py` checks them. Results:

| Languages | Result |
|---|---|
| zh, ja, ko, ru, de, fr, es | no OCR needed; every definition extracted verbatim; 4/4 sections and 6/6 end parts classified; figures, equations, examples, summaries, exercises and 8/8 key terms found (CJK without any bold: from defining sentences); quotes verify exactly |
| ar, hi | the generated PDFs have broken text layers (as many real Arabic/Indic PDFs do): detected as garbled and routed to OCR. Tesseract (fast models) then recovered the definition sentences exactly in 8/8 (Hindi) and 4/8 (Arabic) cases |
| zh scan (200 dpi) | RapidOCR and Tesseract both 8/8 definitions exact, 98.5-98.7% similarity |

Without PyMuPDF, the pdfplumber reader gives the same labels, outline, terms, figures, equations and examples as
PyMuPDF on the English, Chinese and German books (`tests/test_readers.py`).

Scanned versions of the same books (`tests/test_scanned_languages.py`: image-only PDFs whose OCR cache holds the
text lines an engine would return, with no fonts and no bold) give the same chapters, 4/4 sections, 6/6 end
parts, printed page numbers and 8/8 key terms in zh, ja, ko, ru, de, fr and es. With real Tesseract (fast
models from `ocr-setup`) on 200-dpi scans of the fr, de, ru and es books: every definition sentence exact,
8/8 key terms, both chapters and all sections; in Russian Tesseract lost one big chapter title, so the chapter
is named by its label ("Глава 1").

### Real books from the internet

`trials/realbook_eval.py <book.pdf> <work-folder> [--ocr-pages 9-40] [--chapters 3]` runs probe, init, ingest,
optional OCR of some pages and the inventory, and prints timings, the outline, flags, key terms, figures and a
sample page for a human to judge. `python trials/get_corpus.py` downloads the books (sources in
`trials/corpus/README.md`). Books used (open-licensed or public domain) and what they showed after fixes:

| Book | Pages | Result |
|---|---|---|
| OpenStax *Química 2e* (es) | 1,223, text | ingest 22-30 s; 21 chapters from bookmarks with 4-14 sections and 3-4 end parts each; terms such as *hipótesis*, *método científico*, *materia*; examples, figures, 99 exercises in chapter 1 |
| *Dive into Deep Learning* (zh) | 797, text, maths | ingest 11-14 s; 17 chapters; no maths page wrongly marked garbled; definition terms 模型, 学习算法, 损失函数, 训练数据集 |
| MEXT 情報I teacher's guide (ja) | 43, text | body set in a bold face recognised; 11 terms (情報, メディア, 電子マネー, データマイニング ...), 図表 figures |
| bpb *Demokratie* (de) | 84, two columns | soft hyphens joined, "19. Jahrhundert" kept in one sentence, contents/editorial not study sections |
| *Elementary Household Chemistry* (en, 1914) | 361, scan | Windows OCR 1.2 s/page; printed page numbers from the running heads; chapters I-VII with their titles although OCR read II and III as "11" and "111" and a title as "DEFm1TE" |

Remaining weak spots seen there: German and Japanese copula sentences still yield a few non-terms ("Justitia",
"現時点での方向性"), and bold labels inside Japanese diagrams become terms.

Beyond extraction, `tests/test_languages.py` writes the first section of the German, Chinese, French and Korean
books from the book's own sentences (`helpers.oracle_write_section`), lints it with the real `check`, and builds
the checker worksheet. All pass the linter, and every worksheet carries the tier's full number of planted false
claims made in the notes' language (e.g. "Energie ist nicht die Fähigkeit …", "能量不是…", "에너지가 아니다").
Before language-specific operators existed, only claims with numbers could be planted outside English (2 of 16
test sentences per language); now 12-16 of 16 can, and a mismatched-passage canary covers the rest.

### A small model end to end

The brief in `trials/haiku-brief.md` gives a small model (Claude Haiku) the skill folder, a book and the
student's answers, and asks it to work until `TASK done`, reporting every confusing instruction. The book is a
scanned Chinese university textbook (292 pages, the exam covering chapter 1, printed pages 1-16).

What the first runs showed, and what changed because of it:

| Seen | Change |
|---|---|
| chapter 1 ran to the end of the book (only its pages were read), so 259 page pictures were rendered and `plan --confirm` took over 2 minutes | chapters stop at the last read page; pictures only for the exam scope, at most 60 per chapter |
| the OCR card promised "30 seconds" for 16 pages that took 9 minutes | estimates by engine and CPU count, then from the speed measured on the computer |
| `status` took 20-40 s while OCR ran | no PowerShell or onnxruntime start just to list engines; `status` renders nothing |
| two terms of a page shared by two parts were demanded in both, but their text was only in one | each item belongs to the part whose text holds it |
| context ran low after 4 of 7 sections; the model then rewrote drafts with PowerShell (destroying the Chinese text), deleted blocks to get under the skip limit and used `--accept-flags` early | `check` recognises damaged drafts; `restore-draft` puts the script's draft back; deleted blocks come back as reported skips under `--accept-flags`; SKILL.md: running out of context is fine, rushing is not - stop at a PASS and continue in a new session |
| the notes were written in English for a student who asked for Chinese | every writer card states the notes language; the linter rejects English prose in Chinese, Japanese, Korean, Russian, Arabic, Hindi ... notes |
| a part without key terms still had to name inventory IDs in every question's `covers:`, so good questions were skipped | such parts get `covers: NONE` in the skeleton; NONE is refused where terms exist |
| a checker retyping its answers changed the read-only claim and context lines of a worksheet | the script puts read-only lines back itself and says so |
| a sentence cut by a page break, with the page's footnotes between its halves, could not be quoted; the checker saw half a list; running heads read by OCR as "Title 7", "7 Title", "Title" stayed in the text | footnotes are recognised, quotes may run past them, contexts continue overleaf; running heads are counted without their numbers |

A hand audit of the first drafted sections (before any checker pass): every quote verbatim and on the right page
(the script guarantees that), one wrong label on a timeline and one mcq whose premise the book does not state, and
several `plain`/`why` claims citing a sentence that does not support them. These are what the claim checker
and the blind solver are for.

The run on the fixed skill reached `TASK done` in six Haiku sessions of up to about 150k tokens each (a session
stops when its context is full and the next one continues with `next`; one session was cut short by an API usage
limit). The trial workspace is not in the repository because it contains the book's text. Results for the chapter
(16 scanned pages, Chinese notes):

| Metric | Result | Bar |
|---|---|---|
| claims verified | 97 of 107 (90.7%); the other 10 flagged: 8 claims with numbers (years) on OCR pages, which are always flagged for a look at the printed page, 2 approximate quotes | >= 90% |
| planted false claims caught | 39 of 39 | >= 95% |
| answer keys | 22 confirmed by blind solving, 0 disputed | disputed <= 5% |
| key terms covered | 14 of 14 | >= 95% |
| hand audit of 20 verified claims (not verbatim copies) | 18 right; 2 with a small addition the book does not make | >= 98% |

So with a small model in every role the material is usable and honest about its gaps, but the checker lets
through some additions; the writer and checker cards now name that case explicitly, and a stronger checker
model remains the better choice.

## 4. Skill-creator evals (with-skill vs. baseline)

`exam-scribe/evals/evals.json` holds three realistic prompts with checkable expectations, using the sample
book in `exam-scribe/evals/files/`. Run them with the skill-creator workflow (with-skill and without-skill
runs, then the review viewer) to compare against an agent without the skill.
