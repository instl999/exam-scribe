"""A small, safe, unit-aware calculator for `calc:` lines, numeric answers and formula checks.

Syntax (deliberately simple so any model can write it):
    calc: m = 250[g]
    calc: dT = 35.0[degC] - 20.0[degC]
    calc: q = m * 4.184[J/(g*degC)] * dT => 15690[J]
Numbers carry units in square brackets. `=>` asserts the result; the script recomputes it.
"""
from __future__ import annotations

import ast
import math
import random
import re
from dataclasses import dataclass

DIMS = ("m", "kg", "s", "A", "K", "mol", "cd")
Z = (0, 0, 0, 0, 0, 0, 0)


def _d(**kw) -> tuple:
    return tuple(kw.get(k, 0) for k in ("L", "M", "T", "I", "Th", "N", "J"))


ENERGY = _d(L=2, M=1, T=-2)
PRESSURE = _d(L=-1, M=1, T=-2)
UNITS: dict[str, tuple[float, tuple]] = {
    "m": (1.0, _d(L=1)), "g": (1e-3, _d(M=1)), "s": (1.0, _d(T=1)), "A": (1.0, _d(I=1)), "K": (1.0, _d(Th=1)),
    "mol": (1.0, _d(N=1)), "cd": (1.0, _d(J=1)),
    "N": (1.0, _d(L=1, M=1, T=-2)), "J": (1.0, ENERGY), "W": (1.0, _d(L=2, M=1, T=-3)), "Pa": (1.0, PRESSURE),
    "C": (1.0, _d(T=1, I=1)), "V": (1.0, _d(L=2, M=1, T=-3, I=-1)), "ohm": (1.0, _d(L=2, M=1, T=-3, I=-2)),
    "Ω": (1.0, _d(L=2, M=1, T=-3, I=-2)), "F": (1.0, _d(L=-2, M=-1, T=4, I=2)), "Hz": (1.0, _d(T=-1)),
    "T": (1.0, _d(M=1, T=-2, I=-1)), "Wb": (1.0, _d(L=2, M=1, T=-2, I=-1)), "H": (1.0, _d(L=2, M=1, T=-2, I=-2)),
    "S": (1.0, _d(L=-2, M=-1, T=3, I=2)), "Bq": (1.0, _d(T=-1)), "Gy": (1.0, _d(L=2, T=-2)), "Sv": (1.0, _d(L=2, T=-2)),
    "L": (1e-3, _d(L=3)), "atm": (101325.0, PRESSURE), "bar": (1e5, PRESSURE), "mmHg": (133.322387415, PRESSURE),
    "torr": (133.322368, PRESSURE), "Torr": (133.322368, PRESSURE), "cal": (4.184, ENERGY), "Cal": (4184.0, ENERGY),
    "eV": (1.602176634e-19, ENERGY), "kWh": (3.6e6, ENERGY), "min": (60.0, _d(T=1)), "h": (3600.0, _d(T=1)),
    "hr": (3600.0, _d(T=1)), "day": (86400.0, _d(T=1)), "yr": (3.15576e7, _d(T=1)), "year": (3.15576e7, _d(T=1)),
    "degC": (1.0, _d(Th=1)), "°C": (1.0, _d(Th=1)), "M": (1000.0, _d(L=-3, N=1)), "rad": (1.0, Z),
    "deg": (math.pi / 180, Z), "°": (math.pi / 180, Z), "%": (0.01, Z), "ppm": (1e-6, Z), "u": (1.66053906660e-27, _d(M=1)),
    "amu": (1.66053906660e-27, _d(M=1)), "Da": (1.66053906660e-27, _d(M=1)), "ft": (0.3048, _d(L=1)),
    "in": (0.0254, _d(L=1)), "mi": (1609.344, _d(L=1)), "lb": (0.45359237, _d(M=1)), "gal": (3.785411784e-3, _d(L=3)),
    "mph": (0.44704, _d(L=1, T=-1)), "1": (1.0, Z),
}
PREFIXES = {"Y": 1e24, "Z": 1e21, "E": 1e18, "P": 1e15, "T": 1e12, "G": 1e9, "M": 1e6, "k": 1e3, "h": 1e2,
            "da": 1e1, "d": 1e-1, "c": 1e-2, "m": 1e-3, "µ": 1e-6, "μ": 1e-6, "u": 1e-6, "n": 1e-9,
            "p": 1e-12, "f": 1e-15, "a": 1e-18}
NO_PREFIX = {"min", "h", "hr", "day", "yr", "year", "degC", "°C", "%", "ppm", "deg", "°", "atm", "mmHg",
             "torr", "Torr", "in", "ft", "mi", "lb", "gal", "mph", "rad", "1", "amu", "u", "Da"}
SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")


class CalcError(Exception):
    pass


class UnitError(CalcError):
    pass


def dims_name(d: tuple) -> str:
    if d == Z:
        return "(no unit)"
    parts = []
    for sym, e in zip(DIMS, d):
        if e:
            parts.append(sym if e == 1 else f"{sym}^{e:g}")
    return "*".join(parts)


def _lookup(sym: str) -> tuple[float, tuple, bool]:
    celsius = sym in ("degC", "°C")
    if sym in UNITS:
        f, d = UNITS[sym]
        return f, d, celsius
    for p in sorted(PREFIXES, key=len, reverse=True):
        if sym.startswith(p) and sym[len(p):] in UNITS and sym[len(p):] not in NO_PREFIX:
            f, d = UNITS[sym[len(p):]]
            return PREFIXES[p] * f, d, False
    raise UnitError(f"unknown unit '{sym}'")


def parse_unit(expr: str) -> tuple[float, tuple, bool]:
    """Parse 'J/(g*degC)', 'kg*m^2/s^2', 'm/s²', 'J·mol⁻¹' -> (factor, dims, is_plain_celsius)."""
    s = expr.strip().translate(SUPERSCRIPTS)
    s = s.replace("·", "*").replace("⋅", "*").replace("×", "*")
    s = re.sub(r"(?<=[A-Za-zΩ°])(-?\d+)(?![\w.])", r"^\1", s)   # m2 -> m^2, s-1 -> s^-1
    s = re.sub(r"\s*\^\s*", "^", s)
    s = re.sub(r"\s+", "*", s)
    if not s:
        return 1.0, Z, False
    tokens = re.findall(r"\^-?\d+(?:\.\d+)?|[()*/]|[A-Za-zµμΩ°%][A-Za-zµμΩ°]*|1", s)
    if "".join(tokens) != s:
        raise UnitError(f"cannot read unit '{expr}'")
    pos = 0

    def term() -> tuple[float, tuple]:
        nonlocal pos
        if pos >= len(tokens):
            raise UnitError(f"incomplete unit '{expr}'")
        t = tokens[pos]
        if t == "(":
            pos += 1
            f, d = product()
            if pos >= len(tokens) or tokens[pos] != ")":
                raise UnitError(f"missing ')' in unit '{expr}'")
            pos += 1
        else:
            f, d, _ = _lookup(t)
            pos += 1
        if pos < len(tokens) and tokens[pos].startswith("^"):
            e = float(tokens[pos][1:])
            pos += 1
            f, d = f ** e, tuple(x * e for x in d)
        return f, d

    def product() -> tuple[float, tuple]:
        nonlocal pos
        f, d = term()
        while pos < len(tokens) and tokens[pos] in ("*", "/"):
            op = tokens[pos]
            pos += 1
            f2, d2 = term()
            if op == "*":
                f, d = f * f2, tuple(a + b for a, b in zip(d, d2))
            else:
                f, d = f / f2, tuple(a - b for a, b in zip(d, d2))
        return f, d

    f, d = product()
    if pos != len(tokens):
        raise UnitError(f"cannot read unit '{expr}'")
    plain_c = s in ("degC", "°C")
    return f, tuple(round(x, 6) for x in d), plain_c


@dataclass
class Q:
    v: float
    d: tuple = Z
    celsius: bool = False      # an absolute Celsius reading (only differences may be multiplied)

    def _chk(self, other: "Q", op: str) -> None:
        if self.d != other.d:
            raise UnitError(f"cannot {op} {dims_name(self.d)} and {dims_name(other.d)}")

    def __add__(self, o):
        o = _as_q(o)
        self._chk(o, "add")
        return Q(self.v + o.v, self.d, self.celsius != o.celsius and (self.celsius or o.celsius))

    __radd__ = __add__

    def __sub__(self, o):
        o = _as_q(o)
        self._chk(o, "subtract")
        both = self.celsius and o.celsius
        return Q(self.v - o.v, self.d, False if both else (self.celsius or o.celsius))

    def __rsub__(self, o):
        return _as_q(o).__sub__(self)

    def _no_c(self, o: "Q") -> None:
        if self.celsius or o.celsius:
            raise UnitError("a Celsius temperature is used in a multiplication/division; subtract two Celsius "
                            "values first (a difference), or convert to kelvin: (T + 273.15)[K]")

    def __mul__(self, o):
        o = _as_q(o)
        self._no_c(o)
        return Q(self.v * o.v, tuple(a + b for a, b in zip(self.d, o.d)))

    __rmul__ = __mul__

    def __truediv__(self, o):
        o = _as_q(o)
        self._no_c(o)
        if o.v == 0:
            raise CalcError("division by zero")
        return Q(self.v / o.v, tuple(a - b for a, b in zip(self.d, o.d)))

    def __rtruediv__(self, o):
        return _as_q(o).__truediv__(self)

    def __pow__(self, o):
        o = _as_q(o)
        if o.d != Z:
            raise UnitError("an exponent must have no unit")
        if self.celsius:
            raise UnitError("a Celsius temperature is raised to a power; convert to kelvin first")
        return Q(self.v ** o.v, tuple(round(a * o.v, 6) for a in self.d))

    def __neg__(self):
        return Q(-self.v, self.d, self.celsius)

    def __pos__(self):
        return self


def _as_q(x) -> Q:
    return x if isinstance(x, Q) else Q(float(x))


def _q(value: float, unit: str) -> Q:
    f, d, c = parse_unit(unit)
    return Q(value * f, d, c)


def _fn(name: str, need_dimless: bool = True):
    real = {"sqrt": math.sqrt, "ln": math.log, "log": math.log10, "log10": math.log10, "exp": math.exp,
            "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin, "acos": math.acos,
            "atan": math.atan, "abs": abs}[name]

    def f(x):
        x = _as_q(x)
        if name == "sqrt":
            return Q(math.sqrt(x.v), tuple(a / 2 for a in x.d))
        if name == "abs":
            return Q(abs(x.v), x.d, x.celsius)
        if x.d != Z:
            raise UnitError(f"{name}() needs a value with no unit, got {dims_name(x.d)}")
        return Q(real(x.v))
    return f


FUNCS = {n: _fn(n) for n in ("sqrt", "ln", "log", "log10", "exp", "sin", "cos", "tan", "asin", "acos", "atan", "abs")}
CONSTS = {"pi": Q(math.pi), "e": Q(math.e)}
QTY_RE = re.compile(r"(?P<num>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*\[(?P<unit>[^\]]*)\]")
NUM_RE = re.compile(r"^\s*(?P<num>[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*(?:\[(?P<unit>[^\]]*)\])?\s*$")


def _prep(expr: str) -> str:
    s = expr.replace("−", "-")
    s = re.sub(r"(?<=\d),(?=\d{3}\b)", "", s)            # 15,690 -> 15690
    quantities: list[str] = []

    def hold(m: re.Match) -> str:
        unit = m.group("unit").replace('"', "")
        quantities.append(f'_q({m.group("num")}, "{unit}")')
        return f" __Q{len(quantities) - 1}__ "
    s = QTY_RE.sub(hold, s)
    s = s.replace("×", "*").replace("·", "*").replace("÷", "/").replace("^", "**")
    return re.sub(r"__Q(\d+)__", lambda m: quantities[int(m.group(1))], s).strip()


_ALLOWED = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load, ast.Call, ast.Add, ast.Sub,
            ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd)


def evaluate(expr: str, env: dict[str, Q] | None = None) -> Q:
    env = env or {}
    src = _prep(expr)
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError:
        raise CalcError(f"cannot read the expression '{expr.strip()}'")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            raise CalcError(f"'{expr.strip()}' uses something the calculator does not allow")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or (node.func.id not in FUNCS and node.func.id != "_q"):
                raise CalcError(f"unknown function in '{expr.strip()}'. Allowed: {', '.join(FUNCS)}")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float, str)):
            raise CalcError("only numbers are allowed")

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant):
            return n.value if isinstance(n.value, str) else Q(float(n.value))
        if isinstance(n, ast.Name):
            if n.id in env:
                return env[n.id]
            if n.id in CONSTS:
                return CONSTS[n.id]
            raise CalcError(f"'{n.id}' is not defined yet (define it on an earlier calc: line)")
        if isinstance(n, ast.UnaryOp):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.BinOp):
            a, b = ev(n.left), ev(n.right)
            op = type(n.op)
            if op is ast.Add:
                return _as_q(a) + b
            if op is ast.Sub:
                return _as_q(a) - b
            if op is ast.Mult:
                return _as_q(a) * b
            if op is ast.Div:
                return _as_q(a) / b
            return _as_q(a) ** b
        if isinstance(n, ast.Call):
            args = [ev(a) for a in n.args]
            if n.func.id == "_q":
                return _q(args[0].v, args[1])
            return FUNCS[n.func.id](*args)
        raise CalcError("unsupported expression")
    try:
        out = ev(tree)
    except (OverflowError, ValueError, ZeroDivisionError) as exc:
        raise CalcError(f"math error in '{expr.strip()}': {exc}")
    return _as_q(out)


def parse_quantity(text: str) -> Q:
    """'15.7[kJ]' or '15.7 kJ' or '4.00' -> Q."""
    t = text.strip().replace("−", "-").replace(",", "")
    m = NUM_RE.match(t)
    if m:
        unit = m.group("unit")
        return _q(float(m.group("num")), unit) if unit else Q(float(m.group("num")))
    m2 = re.match(r"^\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*([^\d\s].*)$", t)
    if m2:
        return _q(float(m2.group(1)), m2.group(2).strip())
    raise CalcError(f"'{text.strip()}' is not a number with an optional [unit]")


def rounding_tolerance(num_text: str) -> float:
    """Half a unit in the last non-zero digit of a stated number (in the number's own units)."""
    t = num_text.strip().lower().replace(",", "")
    m = re.match(r"^[-+]?(\d*)(?:\.(\d*))?(?:e([-+]?\d+))?", t)
    if not m:
        return 0.0
    ip, fp, ex = m.group(1) or "", m.group(2), int(m.group(3) or 0)
    if fp is not None and fp != "":
        place = -len(fp)
    else:
        # trailing zeros of an integer are ambiguous; assume all but one of them are placeholders
        stripped = ip.rstrip("0")
        zeros = len(ip) - len(stripped) if stripped else 0
        place = max(0, zeros - 1)
    return 0.5 * 10 ** (place + ex)


@dataclass
class CalcResult:
    ok: bool
    message: str = ""
    value: Q | None = None
    name: str | None = None


def run_calc_lines(lines: list[str], env: dict[str, Q] | None = None) -> list[CalcResult]:
    """Evaluate calc lines in order, sharing variables. Each result reports problems in plain words."""
    env = dict(env or {})
    out: list[CalcResult] = []
    for raw in lines:
        line = raw.strip()
        stated = None
        if "=>" in line:
            line, stated = [x.strip() for x in line.split("=>", 1)]
        name = None
        m = re.match(r"^([A-Za-z_]\w*)\s*=(?!=)\s*(.+)$", line)
        if m:
            name, line = m.group(1), m.group(2)
        try:
            val = evaluate(line, env)
        except CalcError as exc:
            out.append(CalcResult(False, str(exc), None, name))
            continue
        if name:
            env[name] = val
        if stated is not None:
            try:
                exp = parse_quantity(stated)
            except CalcError as exc:
                out.append(CalcResult(False, f"the result after '=>' {exc}", val, name))
                continue
            if exp.d != val.d:
                out.append(CalcResult(False, f"units do not match: the calculation gives {dims_name(val.d)} but the "
                                             f"stated result is in {dims_name(exp.d)}", val, name))
                continue
            num_part = re.match(r"\s*([-+]?[\d.,]+(?:[eE][-+]?\d+)?)", stated)
            factor = exp.v / float(num_part.group(1).replace(",", "")) if num_part and float(num_part.group(1).replace(",", "")) else 1.0
            tol = abs(rounding_tolerance(num_part.group(1)) * factor) if num_part else 0.0
            tol = max(tol, 1e-9 * max(abs(exp.v), 1e-30))
            if abs(val.v - exp.v) > tol * 1.0001:
                shown = val.v / factor if factor else val.v
                out.append(CalcResult(False, f"the calculation gives {shown:.6g} but the line states {stated}", val, name))
                continue
        out.append(CalcResult(True, "", val, name))
    return out


def formula_consistent(check: str, rearranged: str, trials: int = 6) -> tuple[bool, str]:
    """Numerically test that `rearranged` (e.g. 'dT = q/(m*c)') follows from `check` ('q = m*c*dT')."""
    def split(eq: str) -> tuple[str, str]:
        m = re.match(r"^\s*([A-Za-z_]\w*)\s*=(?!=)\s*(.+)$", eq)
        if not m:
            raise CalcError(f"'{eq}' must look like 'name = expression'")
        return m.group(1), m.group(2)
    try:
        lhs, rhs = split(check)
        lhs2, rhs2 = split(rearranged)
    except CalcError as exc:
        return False, str(exc)
    names = set(re.findall(r"[A-Za-z_]\w*", rhs)) - set(FUNCS) - set(CONSTS)
    names2 = set(re.findall(r"[A-Za-z_]\w*", rhs2)) - set(FUNCS) - set(CONSTS)
    allv = names | {lhs}
    if lhs2 not in allv or not names2 <= allv:
        return False, f"'{rearranged}' uses names that are not in '{check}'"
    rng = random.Random(7)
    for _ in range(trials):
        env = {n: Q(rng.uniform(0.6, 4.0)) for n in names}
        try:
            env[lhs] = evaluate(rhs, env)
            got = evaluate(rhs2, env)
        except CalcError as exc:
            return False, str(exc)
        want = env[lhs2]
        if abs(got.v - want.v) > 1e-7 * max(1.0, abs(want.v)):
            return False, f"'{rearranged}' does not follow from '{check}'"
    return True, ""
