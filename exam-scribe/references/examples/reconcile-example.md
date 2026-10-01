<!-- EXAMPLE of a finished reconcile worksheet. The first item was a planted wrong key. -->
# Reconcile answers — ch01
<!-- ROLE: judge. For each question, compare the answer key with the independent answer, using ONLY the context. -->
<!-- judgement: SAME = both answers say the same thing
                KEY_WRONG = the key is wrong, the independent answer is right
                MINE_WRONG = the independent answer is wrong, the key is right
                AMBIGUOUS = the question allows more than one answer or the context does not decide it -->
<!-- reason: one sentence quoting the context. Some items are deliberately wrong keys. -->

::: reconcile R-fdfcd5f3
question: Doubling an object's speed doubles its kinetic energy.
key-answer: true
your-answer: false
context: [p.1] KE = ½mv² (1.1) ¶ where m is the mass of the object in kilograms and v is its speed in meters per second. Because the speed is squared, doubling the speed of an object multiplies its kinetic energy by four.
judgement: KEY_WRONG
reason: The context says doubling the speed multiplies the kinetic energy by four, so the statement is false.
:::

::: reconcile R-d90b77cd
question: A food Calorie (with a capital C) equals 1000 calories.
key-answer: true
your-answer: false
context: [p.4] The Calorie (with a capital C) that appears on food labels is actually a kilocalorie: 1 Calorie = 1 kcal = 1000 cal. ¶ Example 1.2 Converting Calories to Joules
judgement: MINE_WRONG
reason: The context says 1 Calorie = 1 kcal = 1000 cal, so the statement is true.
:::
