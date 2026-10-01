import unittest

import helpers  # noqa: F401
from examscribe_lib.common import key_of
from examscribe_lib.mutate import mutate_claim, mutate_latex

CTX = ("The SI unit of energy is the joule (J). A joule is a small amount of energy, so chemists often report "
       "energies in kilojoules (kJ); 1 kJ = 1000 J. An endothermic process absorbs heat from the surroundings.")
TERMS = ["energy", "joule", "kinetic energy", "thermal energy", "calorie", "enthalpy", "heat capacity"]


class MutateTests(unittest.TestCase):
    def test_number_mutation_not_in_context(self):
        for seed in range(20):
            out = mutate_claim("1 kJ = 1000 J, so kilojoules are handy.", CTX, TERMS, seed)
            self.assertIsNotNone(out)
            self.assertNotEqual(out[0], "1 kJ = 1000 J, so kilojoules are handy.")
            if out[1] == "number":
                changed = [w for w in out[0].split() if w not in "1 kJ = 1000 J, so kilojoules are handy.".split()]
                self.assertTrue(all(key_of(w) not in key_of(CTX) for w in changed))

    def test_antonym(self):
        out = mutate_claim("An endothermic process absorbs heat.", CTX, [], 3)
        self.assertIsNotNone(out)
        self.assertNotEqual(key_of(out[0]), key_of("An endothermic process absorbs heat."))

    def test_term_swap_avoids_related_terms(self):
        for seed in range(30):
            out = mutate_claim("Energy is never created or destroyed.", "Energy is never created or destroyed.",
                               ["energy", "thermal energy", "kinetic energy", "calorie"], seed)
            if out and out[1] == "term":
                self.assertNotIn("thermal energy", out[0].lower())
                self.assertNotIn("kinetic energy", out[0].lower())
                self.assertTrue(out[0][0].isupper(), out[0])

    def test_label_is_preserved(self):
        claim = "Kinetic energy — Comes from: the object's motion and speed of 4 m/s"
        out = mutate_claim(claim, "motion", TERMS, 1)
        self.assertTrue(out[0].startswith("Kinetic energy — Comes from: "))

    def test_other_languages(self):
        cases = {
            "de": ("Die Temperatur ist ein Maß für die mittlere kinetische Energie der Teilchen.",
                   "Die Temperatur ist ein Maß für die mittlere kinetische Energie der Teilchen eines Stoffes."),
            "fr": ("L'énergie est la capacité à fournir un travail ou de la chaleur.",
                   "L'énergie est la capacité à fournir un travail ou de la chaleur."),
            "es": ("La energía es la capacidad de realizar trabajo.", "La energía es la capacidad de realizar trabajo."),
            "ru": ("Энергия — это способность совершать работу.", "Энергия — это способность совершать работу."),
            "zh": ("能量是做功或提供热量的能力。", "能量是做功或提供热量的能力。在实验室中，我们通常用温度计测量温度的变化。"),
            "ja": ("エネルギーとは、仕事をする能力である。", "エネルギーとは、仕事をする能力である。"),
            "ko": ("에너지는 일을 하는 능력이다.", "에너지는 일을 하는 능력이다."),
            "hi": ("ऊर्जा कार्य करने की क्षमता है।", "ऊर्जा कार्य करने की क्षमता है।"),
        }
        for lang, (claim, ctx) in cases.items():
            made = set()
            for seed in range(12):
                out = mutate_claim(claim, ctx, [], seed, lang=lang)
                self.assertIsNotNone(out, lang)
                self.assertNotEqual(key_of(out[0]), key_of(claim), lang)
                made.add(out[1])
                if lang == "zh":
                    self.assertIn("能量", out[0])           # never "不能量"
            self.assertIn("negation", made, lang)

    def test_grammar_of_planted_claims(self):
        # Korean particle agrees with the last syllable; French elision is respected in term swaps
        neg = [mutate_claim(c, c, [], s, lang="ko")[0] for c in ("에너지는 일을 하는 에너지이다.", "그것은 능력이다.")
               for s in range(6)]
        self.assertTrue(any("에너지가 아니다" in n for n in neg), neg)
        self.assertTrue(any("능력이 아니다" in n for n in neg), neg)
        self.assertFalse(any("에너지이 아니다" in n for n in neg), neg)
        for seed in range(15):
            out = mutate_claim("Schéma de la conversion entre formes d'énergie", "formes d'énergie",
                               ["énergie", "calorie", "joule"], seed, lang="fr")
            if out and out[1] == "term":
                self.assertNotIn("d'calorie", out[0])
                self.assertNotIn("d'joule", out[0])

    def test_numbers_with_decimal_comma_and_cjk_terms(self):
        out = mutate_claim("c = 4,184 J/(g·K)", "Wasser hat c = 4,184 J/(g·K).", [], 1, lang="de")
        self.assertEqual(out[1], "number")
        self.assertRegex(out[0], r"c = \d+,\d+ J")
        self.assertNotIn("4,184", out[0])
        terms = ["动能", "焦耳", "热容"]
        claim = "动能与物体的质量和速度有关。"          # nothing to negate: the term swap is used
        out = mutate_claim(claim, claim, terms, 3, lang="zh")
        self.assertEqual(out[1], "term")
        self.assertTrue(out[0].startswith(("焦耳", "热容")), out[0])

    def test_mismatched_context(self):
        import random
        from examscribe_lib.mutate import mismatched_context
        claim = "能量是做功或提供热量的能力。"
        contexts = ["能量是做功或提供热量的能力。在实验室中，我们通常用温度计测量温度的变化。", "焦耳是国际单位制中的能量单位。"]
        self.assertEqual(mismatched_context(claim, contexts, random.Random(1)), contexts[1])
        self.assertIsNone(mismatched_context(claim, contexts[:1], random.Random(1)))

    def test_latex_mutation_differs(self):
        for latex in ("q = m c \\Delta T", "KE = \\frac{1}{2} m v^2", "H = U + PV"):
            out = mutate_latex(latex, 1)
            self.assertIsNotNone(out)
            self.assertNotEqual(key_of(out[0]), key_of(latex))


if __name__ == "__main__":
    unittest.main()
