# Subject profile: math and physics

- **Priorities:** every numbered equation (with the conditions under which it holds), definitions,
  theorems with ALL hypotheses, units, and the book's worked examples.
- **Formulas:** `holds-when:` matters most. A theorem without one of its hypotheses is false ("differentiable
  implies continuous", not the reverse; "for constant acceleration"; "for small angles"). Give `check:` and the
  useful `rearrange:` forms; the script tests each rearrangement numerically.
- **Units:** state units in `where:`; use unit-carrying `calc:` lines so the script catches unit slips
  (`9.81[m/s^2]`, `2.0[kg]`). Temperature differences may use `degC`; absolute temperatures must be kelvin.
- **Worked examples:** transcribe every step; every number must come from the problem or a `calc:` line.
  The notes add a faded copy automatically.
- **Questions:** numeric problems with new numbers (computed with `calc:`), mcq on which formula applies,
  true/false on conditions and sign conventions, "find the error" questions at the analyze level.
- **Strategy table** (exam format `problems`): "when you see ... do ...", e.g. "constant acceleration and no
  time given -> use v^2 = u^2 + 2as".
- **Watch for:** extraction damage in formulas (`_x` subscripts, `^x` superscripts, missing fraction bars).
  Compare with the equation image named in the draft comment when you can view images.
