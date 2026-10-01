# Book extraction (ingest) and scanned books (OCR)

## Supported input

- **PDF** (best), plus EPUB, MOBI, XPS and CBZ through PyMuPDF.
- **Markdown or text.** Pages are split at page markers if present (`<!-- page 12 -->`, Marker's paginated
  `{11}------` markers, or `=== PAGE 12 ===`); otherwise every ~3,000 characters. `**bold**` marks key terms
  and `#` headings form the outline. This is the route for math-heavy books (see below).
- **Photos or scans of pages** (JPG, PNG, TIFF, BMP, GIF, WebP, a multi-page TIFF), or a folder of them: `init`
  puts them into one PDF in file-name order (page2 before page10) and the book is read like any scanned book.
- DjVu files cannot be read: convert them to PDF first (`ddjvu -format=pdf book.djvu book.pdf`); the error
  message says so. The same goes for Word or PowerPoint files (save as PDF).
- Password-protected PDFs cannot be read: ask the user for an unlocked copy.

`probe <file>` (and `init`) report in a few seconds what a file needs: how many pages have a text layer, how
many are scans or have a broken text layer, the language, whether there is a table of contents, and how long
extraction and OCR will take.

## A text PDF never needs OCR

Nearly every textbook PDF, in any language, has a text layer: the characters are stored in the file and are read
directly, a 200-page book in about 2 seconds. OCR (recognising text from page images) is only for scans and for
the rare PDFs whose text layer is broken. An agent that cannot open PDFs itself should not fall back to
rendering pages as images or running OCR: run `init` + `next`, or `extract <file> [--pages 30-45]` for the plain
text as Markdown (page markers, headings and **bold** terms kept; the file also works as the book for `init`).

## Without PyMuPDF

PyMuPDF is the fast reader and the only one that makes pictures and runs OCR. If it cannot be installed (some
sandboxes block pip or compiled packages), text PDFs are still read:

| Reader | Speed | Keeps |
|---|---|---|
| PyMuPDF | ~6-10 ms per page | everything |
| pdfplumber (+ pypdfium2, installed with it) | ~50 ms per page | fonts, sizes, bold, layout, bookmarks, page labels: same inventory as PyMuPDF in the tests |
| pypdf | ~50 ms per page | text, bookmarks, page labels; no bold or layout (key terms come from defining sentences) |

`doctor` and `probe` say which reader is used. Without PyMuPDF there are no figure pictures and no OCR. As a last
resort, `pdftotext book.pdf book.txt` (poppler) output works as the book too: its page breaks keep page numbers.

## Languages

Extraction and the inventory work for books in other languages: tested with Chinese, Japanese, Korean, Russian,
German, French and Spanish text PDFs (every definition sentence extracted verbatim, chapters, sections,
end-of-chapter parts, figures, equations, examples, exercises and key terms found, quotes verified), with scanned
versions of the same books (OCR text: same chapters, sections, end parts and key terms), and with real books from
the internet (a Spanish chemistry textbook, a Chinese machine-learning book, a Japanese ministry textbook, a
German civics booklet, a 1914 English scan and a scanned Chinese communication-studies textbook). What makes this work:

- Chinese and Japanese lines are joined without a space; sentences split at 。！？, ।, ؟ as well as . ! ?, with
  common abbreviations in several languages (z. B., p. ex., т. е., Abb. 3 ...).
- Structure words in 17 languages (`scripts/examscribe_lib/lang.py`): Figure/Abbildung/图/図/그림/Рис., Example/
  Beispiel/例题, Summary/Zusammenfassung/本章小结/まとめ/요약, Key terms, Exercises/Aufgaben/习题/演習問題, Chapter/Kapitel/
  第3章/제3장/Глава ... Add words there for more languages.
- Key terms: bold type, synthetic bold (text drawn filled + stroked) and, in Chinese/Japanese books, the Hei/Gothic
  face used for emphasis; without any of these, defining sentences in each language ("X is the ...",
  "X was defined as ...", "X ist die ...", "X wurde als ... definiert", "X a été définie comme ...",
  "X — это ...", "X是...的", "XとはYである", "X는 ...이다", "X هي", "X वह ..."). A book whose running text is
  itself set in a bold face (some Japanese and Chinese books) is recognised: its bold marks nothing. Chinese and
  Japanese terms must be short noun phrases (no punctuation, clauses or verb endings); symbols and formula pieces
  ("x, y", "_x") are never terms.
- German ordinals ("im 19. Jahrhundert") do not end sentences; soft hyphens at line ends are rejoined.
- Numbers with decimal commas (4,184 J in German, French, Russian ...) are read both ways, so checks accept the
  book's form; `calc:` lines always use a decimal point.
- Broken text layers are detected (replacement characters and private-use codes inside words, Latin letters
  inside Arabic, Hebrew or Indic words, which is how broken Arabic and Hindi PDFs usually look, and Chinese or
  Cyrillic text decoded with the wrong code page, "ÄÜÁ¿") and read with OCR instead. Lone unmapped maths symbols
  and the bracket pieces of big matrices are not counted: a maths-heavy page is not "garbled".
- `init` detects the book's language from its text (override with `--language xx`). It decides the OCR language
  and the default language of the notes, and which words the planted false claims use (negations and opposites
  exist for 12 languages; in any language a claim shown next to an unrelated passage is used as well).

## Speed: what takes time and what does not

| Step | Cost | When |
|---|---|---|
| Extraction of a text PDF | ~6 ms per page (a 640-page book in ~4 s) | once, at the start |
| Inventory (terms, equations, examples) | ~2 ms per page | after extraction |
| Figure, equation and page pictures | ~25 ms per picture | only for the chapters being studied |
| OCR of a scanned page | ~0.3-1 s (Windows), ~1-3 s (Tesseract, per worker), ~2-40 s (RapidOCR, depends on the CPU) | only for scanned pages in the exam scope |
| Writing and checking notes | minutes per section | per section, the real work |

So: a text PDF is never the slow part. A scanned book is slow only if every page is read, which is why OCR
waits for the intake questions and then reads only the exam's chapters or pages (`scope.chapters`,
`scope.pages`). Small scanned books (whole book in about 2 minutes or less) are read before the intake, so the
chapter list shown to the user is complete. **The model must never read the PDF itself**: rendering pages as
images for a model costs far more time and tokens than the scripts, and quotes are checked against the
scripts' text anyway.

## What ingest does

1. Reads every text span with its font, size, bold/italic flags and position, and the page's drawing log
   (images and vector paths) in one pass. Big books on machines with 4+ cores use parallel processes.
2. Rebuilds reading order: merges pieces on the same baseline (an equation and its number) but never across
   the gutter of a two-column page, handles two-column pages, and marks subscripts `_x` and superscripts `^x`.
3. Removes running headers, footers and page numbers (lines repeated in the page margins; on scans, whose
   margins include the paper's, also the first and last line of a page when it repeats or carries the page
   number, as in "12 BOOK TITLE").
4. Rejoins paragraphs, removes line-break hyphens (keeping real compounds such as "coffee-cup"), and
   replaces ligatures (ﬁ -> fi).
5. **Page numbers:** uses the PDF's own page labels (so p.12 means the printed page 12, including roman
   front matter); otherwise printed page numbers found in the margins (also in OCR text, also inside a running
   head); otherwise PDF page positions. A scan without page labels has no known printed numbers until some pages
   are read, so the intake card then asks for pages as the PDF viewer numbers them.
6. **Outline:** from the PDF bookmarks (lists that only number the pages, as some scanning tools make, are
   ignored); otherwise from headings: big titles (joined with a "Chapter 3" line printed above them, also when
   the title is set in plain capitals of the text size, as in old books), numbered section headings ("2.1 ...",
   "第三节 ...") and end-of-chapter headings (Summary, Key Terms, ...). Contents pages are skipped. A section
   number seen again later (summaries, review questions) is not a new section. Front matter inside a chapter
   (contents, preface, imprint) is not a study section, and a chapter that starts with the book's own
   introduction gets no second, automatic one. A guessed outline is shown to the user for confirmation.
   For OCR text: roman chapter numbers misread as digits ("CHAPTER 11" for II, "1V" for IV) and a big "第二章"
   misread as "第一章" are repaired from the order of the chapters; a "Chapter 3" line whose big title OCR lost
   stands for the chapter; specks read as letters are never titles. A chapter guessed from headings stops at
   the last page that has been read: scanned pages that have not been read with OCR yet are listed apart as
   "Pages X-Y (scanned, not read yet)" instead of being swallowed by the chapter before them.
7. **Figures and tables:** captions ("Figure 2.1 ...", "Table 2.1 ...", "図表3 ...") are paired with the images
   or vector drawings next to them and a crop rectangle is recorded. The pictures (`source/figures/`, printed
   equations in `source/equations/`, renders of doubtful and OCR pages of the exam scope in
   `source/page-images/`, at most 60 per chapter) are made the first time a chapter is worked on, not for the
   whole book.
8. **Quality flags** per page: `scanned-no-text`, `garbled`, `math-heavy`, `two-column`, `ocr`.
9. **Footnotes** at the foot of a page (set smaller, or on scans recognised by what they cite: 《书名》 with
   pages, a publisher or a year; "p. 12", "Press") are marked. Source files show them under a line "footnotes of
   this page"; a quote may run across a page break past them ("…群体传播、组" + "织传播和大众传播"), and a
   checker gets the rest of a sentence that goes on overleaf.

## Scanned books (OCR)

Pages without a usable text layer (`scanned-no-text`, or `garbled` characters) are read with OCR by the
`ocr` command, which the `run-ocr` card asks for. Engines, first available wins (`config set ocr.engine` to choose):

| Engine | Install | Speed | Notes |
|---|---|---|---|
| `windows` | nothing (Windows 10/11) | fastest | languages = the Windows display/OCR languages installed; add more in Settings > Time & language > Language & region |
| `tesseract` | language data only: PyMuPDF contains the engine. `ocr-setup <ws>` downloads the book's language (1-5 MB from github.com/tesseract-ocr/tessdata_fast) into `~/.examscribe/tessdata/`; an installed Tesseract works too | ~1-3 s per page per worker, parallel (Chinese slower) | 100+ languages, any OS; the choice for Arabic, Hindi and other scripts Windows lacks. Very large title type is sometimes missed |
| `rapidocr` | `python -m pip install rapidocr_onnxruntime` | ~2-5 s per page on a laptop (20-40 s on a slow 2-core VM) | Chinese and English; the most accurate for Chinese |

How a run works:

- Pages are rendered in gray (default 200 dpi; `ocr.dpi 300` for small print) and read by several workers in
  parallel (`ocr.jobs`). For the Windows engine, pixels are passed raw (no PNG compression, which costs more
  than the OCR itself on noisy scans).
- Time estimates start from typical speeds for the engine and the number of CPU cores, and after the first run
  use the speed measured on this computer (remembered in `~/.examscribe/ocr-speed.json` for every book).
- Every page is saved to `source/ocr/pNNNN.json` the moment it is read. A run stops by itself after about 9
  minutes (`--budget SECONDS`, 0 = no limit) and prints `NOT FINISHED`; running the same command again
  continues. A killed run loses nothing either: its workers stop on their own and finished pages are kept.
- After a run the book is re-extracted with the OCR text, so page numbers printed in the scans, headings and
  the outline become available. Pictures of scanned figures are cut from the scan as for text PDFs.
- Useful options: `ocr <ws> --pages 45-120` (specific pages), `--all` (every scanned page, including front
  matter and appendices), `--force` (read again, e.g. after changing `ocr.dpi`).

What OCR text means for trust: on clean scans the text is very accurate (in our tests 98.5-99.7% of
characters, 95-99% of words; Chinese scans 98.5-98.7% with RapidOCR or Tesseract; Hindi 97%, Arabic 82% with
Tesseract's fast models), but digits, decimal points, signs, sub/superscripts and formulas are where it slips
(91-94% of numbers survived). So claims with numbers on OCR pages are always shown with ⚠ "check the numbers
against the printed page", `page <ws> <n> --image` renders the page, and OCR pages have no bold, so key terms are
found from defining sentences ("X is the ... that ...", "is called X", "X (sym)") instead of bold type.

If no engine can read the book's language, the `need-ocr-engine` card lists the user's options: download the
Tesseract language data (`ocr-setup <ws>`, a few MB, no admin rights, any OS), add the language to Windows,
install RapidOCR (Chinese, English), use a PDF that already has a text layer (for example made with OCRmyPDF),
or go on without the scanned pages (`config set ocr.skip true`). Downloads need the user's OK.

## Math-heavy books

Formula-dense PDFs often extract badly (symbols, fractions, sub/superscripts), and OCR does not read formulas
at all. Options, best first:

1. Convert the PDF with a math-aware converter such as **Marker** (`marker_single book.pdf --output_format
   markdown --paginate_output`) or **MinerU**, then run `init` with the resulting Markdown file. Page markers
   keep page numbers; formulas arrive as LaTeX. Both run much faster on a GPU.
2. Keep the PDF and let a vision-capable model read the equation crops and page images when writing `latex:`.
3. Otherwise, write what the text shows and let the formula check flag it (`CANNOT_TELL`) for a human.

## Useful commands

- `probe <file>` checks a file before anything else is done.
- `page <ws> 12` prints the extracted text of printed page 12; `page <ws> 12 --image` renders it.
- `find <ws> "words"` shows every page containing the words (or the most similar text).
- `outline <ws>` shows the chapters and sections; `outline <ws> --from-text file` replaces them;
  `outline <ws> --confirm` accepts a guessed outline.
- `ocr <ws>` reads the scanned pages of the exam scope; `status <ws>` shows how many are done.
- `ocr-setup <ws>` (or `ocr-setup --language xx`) gets the Tesseract language data for a book's language.
