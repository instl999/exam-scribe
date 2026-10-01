# Writing good questions and flashcards

Questions are the heart of the notes: students learn more from answering than from re-reading. A bad
question (ambiguous, trivial, or with a wrong key) does real harm, so every key is re-solved blind.

## Contents
1. Types and when to use them
2. Bloom levels
3. Rules for every question
4. Multiple choice: distractors
5. Numeric questions
6. Cloze and short answer
7. Flashcards (built automatically)

## 1. Types and when to use them

| Type | Good for | Checked by |
|---|---|---|
| `mcq` | discriminating between similar ideas, common mistakes | exact letter match + "only one correct?" |
| `tf` | common misconceptions, sign conventions | exact match |
| `numeric` | applying a formula to a new case | calculator (1% tolerance) |
| `cloze` | key terms and must-know statements (one missing word or phrase) | normalised text match |
| `short` | explaining why; comparing; causes | independent judge (costlier, so limited per section) |

The skeleton picks the mix from the exam format; keep it unless the section truly cannot support a type.

## 2. Bloom levels

- `remember`: recall a definition or fact ("What is ...?", cloze).
- `understand`: explain, classify, compare ("Which statement correctly distinguishes ...?").
- `apply`: use a rule or formula on a new case (numeric problems, classify a new example).
- `analyze`: find the error, the cause, or the relevant piece of information.
- `evaluate`: choose the best option and justify it.

Each section needs at least two different levels, and every learning objective should be covered by some
question (`covers:`).

## 3. Rules for every question

1. Exactly one defensible answer, taken from this section of the book. The blind solver answers from the
   book text only; if it cannot reach your key, the question is disputed.
2. Ask one thing. No "and/or" questions, no double negatives, no "all/none of the above".
3. Use the book's terms and notation (the exam will).
4. `why:` gives the evidence with a citation. It is shown after the student answers, so it should teach.
5. New numbers in a practice problem are fine (and good), but compute the answer with `calc:` lines.

## 4. Multiple choice: distractors

- Write three wrong options that a student who half-understands would pick: the most common mistake, a swapped
  pair (endothermic/exothermic), a missing condition, a unit or sign slip.
- Make options similar in length and grammar so the right one does not stand out.
- `why-not X:` explains each wrong option in one sentence. It turns every wrong answer into a lesson.

## 5. Numeric questions

```
ask: How much heat is needed to warm 50.0 g of aluminum from 25.0 °C to 75.0 °C? Use c = 0.897 J/(g·°C).
calc: dT = 75.0[degC] - 25.0[degC] => 50.0[degC]
calc: q = 50.0[g] * 0.897[J/(g*degC)] * dT => 2242.5[J]
answer: 2.24[kJ]
```

Give every value the student needs in `ask:`, state the unit expected, and round the answer to sensible
significant figures. `tolerance: 2%` widens the accepted range when the book's data are rounded.

## 6. Cloze and short answer

- Cloze: take a key sentence from the book and replace the key term with `____`. The answer must appear in
  the quoted evidence. Add `accept:` lines for equivalent forms ("joule (J)").
- Short answer: at most 60 words, containing the points the book makes. Prefer "Explain why ..." over
  "Describe ...".

## 7. Flashcards (built automatically)

The deck follows the minimum-information principle (one fact per card; Wozniak's "20 rules of formulating
knowledge"): a definition card and a cloze card per concept, a formula card and a "when does it hold?" card
per formula, a true/false card per misconception, a card per comparison row, "what comes next?" cards for
processes, and one card per verified question. You do not write cards; write good blocks and they follow.
