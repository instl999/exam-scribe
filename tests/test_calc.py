import unittest

import helpers  # noqa: F401  (sets sys.path)
from examscribe_lib.calc import (CalcError, UnitError, evaluate, formula_consistent, parse_quantity, parse_unit,
                                 rounding_tolerance, run_calc_lines)


class UnitTests(unittest.TestCase):
    def test_parse_units(self):
        f, d, c = parse_unit("J/(g*degC)")
        self.assertAlmostEqual(f, 1000.0)
        self.assertFalse(c)
        self.assertEqual(parse_unit("kJ")[0], 1000.0)
        self.assertAlmostEqual(parse_unit("mL")[0], 1e-6)
        self.assertEqual(parse_unit("m/s^2")[1], parse_unit("m*s^-2")[1])
        self.assertEqual(parse_unit("m²")[1], parse_unit("m^2")[1])
        self.assertTrue(parse_unit("degC")[2])

    def test_unknown_unit(self):
        with self.assertRaises(UnitError):
            parse_unit("florps")

    def test_quantities(self):
        self.assertAlmostEqual(parse_quantity("15.7[kJ]").v, 15700)
        self.assertAlmostEqual(parse_quantity("15.7 kJ").v, 15700)
        self.assertAlmostEqual(parse_quantity("-890[kJ]").v, -890000)


class CalcLineTests(unittest.TestCase):
    def test_worked_example(self):
        res = run_calc_lines(["dT = 35.0[degC] - 20.0[degC] => 15.0[degC]",
                              "q = 250[g] * 4.184[J/(g*degC)] * dT => 15690[J]", "q => 15.7[kJ]"])
        self.assertTrue(all(r.ok for r in res), [r.message for r in res])

    def test_wrong_result_detected(self):
        res = run_calc_lines(["q = 250[g] * 4.184[J/(g*K)] * 15[K] => 15.6[kJ]"])
        self.assertFalse(res[0].ok)
        self.assertIn("15.69", res[0].message)

    def test_unit_mismatch(self):
        self.assertFalse(run_calc_lines(["x = 1[J] + 1[K]"])[0].ok)
        self.assertIn("units do not match", run_calc_lines(["x = 2[kg] => 2[J]"])[0].message)

    def test_celsius_multiplication_rejected(self):
        res = run_calc_lines(["bad = 25[degC] * 2[g]"])
        self.assertFalse(res[0].ok)
        self.assertIn("Celsius", res[0].message)

    def test_conversions(self):
        self.assertTrue(run_calc_lines(["E = 250[cal] => 1046[J]"])[0].ok)
        self.assertTrue(run_calc_lines(["p = 1[atm] => 101.325[kPa]"])[0].ok)
        self.assertTrue(run_calc_lines(["n = 1.5[mol/L] * 2[L] => 3[mol]"])[0].ok)

    def test_rounding_tolerance(self):
        self.assertEqual(rounding_tolerance("15.7"), 0.05)
        self.assertEqual(rounding_tolerance("15690"), 0.5)
        self.assertEqual(rounding_tolerance("1.57e4"), 50.0)
        self.assertEqual(rounding_tolerance("16000"), 50.0)

    def test_unsafe_expressions_rejected(self):
        for expr in ("__import__('os')", "(1).real", "open('x')", "[1,2]"):
            with self.assertRaises(CalcError):
                evaluate(expr)

    def test_formula_consistency(self):
        self.assertTrue(formula_consistent("q = m * c * dT", "dT = q / (m * c)")[0])
        self.assertFalse(formula_consistent("q = m * c * dT", "dT = q * m / c")[0])
        self.assertTrue(formula_consistent("KE = 1/2 * m * v^2", "v = sqrt(2 * KE / m)")[0])


if __name__ == "__main__":
    unittest.main()
