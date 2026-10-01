import unittest

import helpers
from examscribe_lib.citations import QuoteIndex, claim_numbers
from examscribe_lib.common import build_key, number_groups, numbers_in


class KeyTests(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(build_key("Speciﬁc heat")[0], build_key("specific   HEAT")[0])
        self.assertEqual(build_key("tempera-\nture")[0], build_key("temperature")[0])
        self.assertEqual(build_key("“q = m × c”")[0], build_key('"q = m * c"')[0])
        self.assertNotEqual(build_key("4.184 J")[0], build_key("41.84 J")[0])
        self.assertNotEqual(build_key("−890 kJ")[0], build_key("890 kJ")[0])

    def test_numbers(self):
        self.assertEqual(number_groups("15,690 J and −890 kJ and 250. g and 0.500 kg"),
                         [["15690", "15.69"], ["-890"], ["250"], ["0.5"]])
        self.assertEqual(claim_numbers("See Figure 2.1 and Equation (2.3): 4.184 J in Chapter 2"), [["4.184", "4184"]])
        # decimal commas (German, French, Russian ...) and dot or thin-space thousands
        self.assertEqual(number_groups("4,184 J; 9,00 J; 2,5 kg; 1.234,56; 1,234.56; 10 000; 1, 2, 3"),
                         [["4184", "4.184"], ["9"], ["2.5"], ["1234.56"], ["1234.56"], ["10000"], ["1"], ["2"], ["3"]])
        from examscribe_lib.citations import unsupported_numbers
        self.assertEqual(unsupported_numbers(number_groups("c = 4,184 J/(g·K)"), set(numbers_in("4.184"))), [])
        self.assertEqual(unsupported_numbers(number_groups("c = 4,284 J/(g·K)"), set(numbers_in("4.184"))), ["4284"])


class QuoteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ws = helpers.new_workspace()
        cls.qi = QuoteIndex(cls.ws)

    @classmethod
    def tearDownClass(cls):
        helpers.cleanup(cls.ws)

    def test_exact(self):
        r = self.qi.check("1", "Energy is the capacity to supply heat or do work.")
        self.assertEqual(r.status, "exact")
        self.assertIn("Energy is the capacity", r.context)

    def test_ligature_page_text(self):
        self.assertEqual(self.qi.check("8", "Specific heat is an intensive property").status, "exact")

    def test_wrong_page(self):
        r = self.qi.check("1", "Thermal energy is the kinetic energy associated with the random motion")
        self.assertEqual(r.status, "wrong-page")
        self.assertEqual(r.found_pages, ["2"])

    def test_paraphrase_not_found(self):
        r = self.qi.check("1", "Energy is the ability to provide heat or perform work.")
        self.assertIn(r.status, ("not-found", "approx"))
        self.assertNotEqual(r.status, "exact")
        self.assertIn("capacity", r.closest)

    def test_bad_page_and_short(self):
        self.assertEqual(self.qi.check("999", "Energy is the capacity to supply heat").status, "bad-page")
        self.assertEqual(self.qi.check("1", "energy").status, "too-short")

    def test_page_spill(self):
        # quote that runs from the end of one page into the next is accepted on the first page
        p1 = self.ws.page_by_label("1")["text"].split()[-6:]
        p2 = self.ws.page_by_label("2")["text"].split()[:4]
        r = self.qi.check("1", " ".join(p1 + p2))
        self.assertEqual(r.status, "exact")


if __name__ == "__main__":
    unittest.main()
