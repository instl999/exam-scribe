"""Deterministic mutations that turn a true claim into a false one.

Used twice:
  * canaries: planted false claims mixed into verification worksheets. A checker that
    marks one SUPPORTED is not reading carefully, and its whole batch is redone.
  * the mutation-testing eval (tools/mutation_eval.py), which measures what the checks catch.
Each operator makes a change that the claim's own context contradicts. Operators exist for English, German,
French, Spanish, Italian, Portuguese, Russian, Chinese, Japanese, Korean, Arabic and Hindi; numbers and term
swaps work in any language.
"""
from __future__ import annotations

import random
import re

from .common import key_of

ANTONYMS = [
    ("increases", "decreases"), ("increase", "decrease"), ("increased", "decreased"), ("higher", "lower"),
    ("more", "less"), ("greater", "smaller"), ("larger", "smaller"), ("maximum", "minimum"), ("positive", "negative"),
    ("absorbs", "releases"), ("absorbed", "released"), ("absorb", "release"), ("gains", "loses"), ("gain", "loss"),
    ("before", "after"), ("above", "below"), ("inside", "outside"), ("into", "out of"), ("first", "last"),
    ("left", "right"), ("same", "different"), ("directly", "inversely"), ("direct", "inverse"), ("strong", "weak"),
    ("stronger", "weaker"), ("fast", "slow"), ("faster", "slower"), ("endothermic", "exothermic"),
    ("oxidation", "reduction"), ("acid", "base"), ("acidic", "basic"), ("anode", "cathode"), ("necessary", "sufficient"),
    ("input", "output"), ("top", "bottom"), ("rises", "falls"), ("rise", "fall"), ("warmer", "colder"), ("hot", "cold"),
    ("hotter", "colder"), ("expands", "contracts"), ("attract", "repel"), ("attracts", "repels"), ("heats", "cools"),
    ("early", "late"), ("earlier", "later"), ("majority", "minority"), ("dependent", "independent"),
    ("depends", "does not depend"), ("intensive", "extensive"), ("gained", "lost"), ("add", "remove"),
    ("adds", "removes"), ("north", "south"), ("east", "west"), ("upper", "lower"), ("most", "least"),
    ("minimum", "maximum"), ("constant", "changing"), ("stable", "unstable"), ("true", "false"),
    ("allowed", "forbidden"), ("legal", "illegal"), ("valid", "invalid"), ("plaintiff", "defendant"),
    ("increasing", "decreasing"), ("contract", "expand"), ("cooling", "heating"), ("heating", "cooling"),
]
QUANTIFIERS = [("always", "never"), ("all", "no"), ("every", "no"), ("only", "also"), ("must", "may"),
               ("cannot", "can"), ("none", "all"), ("both", "neither"), ("everything", "nothing")]
AUX = ("is", "are", "was", "were", "can", "does", "do", "has", "have", "will", "should", "must", "could")

# other languages: opposites and quantifiers common in textbooks
ANTONYMS_BY_LANG = {
    "de": [("erhöht", "verringert"), ("steigt", "sinkt"), ("zunimmt", "abnimmt"), ("nimmt zu", "nimmt ab"),
           ("höher", "niedriger"), ("mehr", "weniger"), ("größer", "kleiner"), ("Maximum", "Minimum"),
           ("positiv", "negativ"), ("aufnimmt", "abgibt"), ("nimmt auf", "gibt ab"), ("endotherm", "exotherm"),
           ("Oxidation", "Reduktion"), ("Säure", "Base"), ("vor", "nach"), ("oberhalb", "unterhalb"),
           ("innen", "außen"), ("schneller", "langsamer"), ("stark", "schwach"), ("wärmer", "kälter"),
           ("gleich", "verschieden"), ("direkt", "indirekt"), ("proportional", "umgekehrt proportional")],
    "fr": [("augmente", "diminue"), ("plus", "moins"), ("supérieur", "inférieur"), ("supérieure", "inférieure"),
           ("élevé", "faible"), ("maximum", "minimum"), ("positif", "négatif"), ("positive", "négative"),
           ("absorbe", "libère"), ("endothermique", "exothermique"), ("oxydation", "réduction"), ("acide", "base"),
           ("avant", "après"), ("au-dessus", "au-dessous"), ("rapide", "lent"), ("fort", "faible"),
           ("chaud", "froid"), ("même", "différent"), ("directement", "inversement")],
    "es": [("aumenta", "disminuye"), ("mayor", "menor"), ("más", "menos"), ("alto", "bajo"), ("alta", "baja"),
           ("máximo", "mínimo"), ("positivo", "negativo"), ("positiva", "negativa"), ("absorbe", "libera"),
           ("endotérmico", "exotérmico"), ("oxidación", "reducción"), ("ácido", "base"), ("antes", "después"),
           ("encima", "debajo"), ("rápido", "lento"), ("fuerte", "débil"), ("caliente", "frío"),
           ("mismo", "diferente"), ("directamente", "inversamente")],
    "it": [("aumenta", "diminuisce"), ("maggiore", "minore"), ("più", "meno"), ("alto", "basso"), ("massimo", "minimo"),
           ("positivo", "negativo"), ("assorbe", "rilascia"), ("endotermico", "esotermico"), ("ossidazione", "riduzione"),
           ("acido", "base"), ("prima", "dopo"), ("sopra", "sotto"), ("veloce", "lento"), ("forte", "debole"),
           ("caldo", "freddo"), ("stesso", "diverso")],
    "pt": [("aumenta", "diminui"), ("maior", "menor"), ("mais", "menos"), ("alto", "baixo"), ("máximo", "mínimo"),
           ("positivo", "negativo"), ("absorve", "libera"), ("endotérmico", "exotérmico"), ("oxidação", "redução"),
           ("ácido", "base"), ("antes", "depois"), ("acima", "abaixo"), ("rápido", "lento"), ("forte", "fraco"),
           ("quente", "frio"), ("mesmo", "diferente")],
    "ru": [("увеличивается", "уменьшается"), ("возрастает", "убывает"), ("повышается", "понижается"),
           ("больше", "меньше"), ("выше", "ниже"), ("максимум", "минимум"), ("положительный", "отрицательный"),
           ("положительная", "отрицательная"), ("поглощает", "выделяет"), ("поглощается", "выделяется"),
           ("эндотермический", "экзотермический"), ("окисление", "восстановление"), ("кислота", "основание"),
           ("до", "после"), ("быстрее", "медленнее"), ("сильный", "слабый"), ("теплее", "холоднее"),
           ("одинаковый", "разный"), ("прямо", "обратно")],
    "zh": [("增加", "减少"), ("升高", "降低"), ("增大", "减小"), ("大于", "小于"), ("高于", "低于"), ("最大", "最小"),
           ("吸收", "释放"), ("吸热", "放热"), ("氧化", "还原"), ("酸性", "碱性"), ("之前", "之后"), ("正电", "负电"),
           ("加快", "减慢"), ("变大", "变小"), ("升温", "降温"), ("相同", "不同"), ("正比", "反比"), ("较多", "较少"),
           ("上升", "下降"), ("增强", "减弱")],
    "ja": [("増加", "減少"), ("上昇", "低下"), ("高い", "低い"), ("大きい", "小さい"), ("多い", "少ない"),
           ("最大", "最小"), ("吸収", "放出"), ("吸熱", "発熱"), ("酸化", "還元"), ("酸性", "塩基性"),
           ("速い", "遅い"), ("強い", "弱い"), ("同じ", "異なる"), ("比例", "反比例"), ("上がる", "下がる")],
    "ko": [("증가", "감소"), ("높은", "낮은"), ("높다", "낮다"), ("큰", "작은"), ("크다", "작다"), ("많은", "적은"),
           ("최대", "최소"), ("흡수", "방출"), ("흡열", "발열"), ("산화", "환원"), ("산성", "염기성"), ("빠른", "느린"),
           ("강한", "약한"), ("같은", "다른"), ("비례", "반비례"), ("상승", "하강")],
    "ar": [("يزداد", "يقل"), ("تزداد", "تقل"), ("أكبر", "أصغر"), ("أعلى", "أدنى"), ("موجب", "سالب"),
           ("يمتص", "يطلق"), ("ماص", "طارد"), ("أكسدة", "اختزال"), ("حمض", "قاعدة"), ("قبل", "بعد")],
    "hi": [("बढ़ता", "घटता"), ("बढ़ती", "घटती"), ("अधिक", "कम"), ("ऊँचा", "नीचा"), ("अधिकतम", "न्यूनतम"),
           ("धनात्मक", "ऋणात्मक"), ("अवशोषित", "मुक्त"), ("ऊष्माशोषी", "ऊष्माक्षेपी"), ("ऑक्सीकरण", "अपचयन"),
           ("अम्ल", "क्षार"), ("पहले", "बाद")],
}
QUANTIFIERS_BY_LANG = {
    "de": [("immer", "nie"), ("alle", "keine"), ("jeder", "kein"), ("nur", "auch")],
    "fr": [("toujours", "jamais"), ("tous", "aucun"), ("toutes", "aucune"), ("seulement", "aussi")],
    "es": [("siempre", "nunca"), ("todos", "ninguno"), ("todas", "ninguna"), ("solo", "también")],
    "it": [("sempre", "mai"), ("tutti", "nessuno"), ("solo", "anche")],
    "pt": [("sempre", "nunca"), ("todos", "nenhum"), ("apenas", "também")],
    "ru": [("всегда", "никогда"), ("все", "никакие"), ("только", "также")],
    "zh": [("总是", "从不"), ("一定", "未必"), ("所有", "没有"), ("只有", "也有")],
    "ja": [("常に", "まれに"), ("必ず", "決して"), ("すべて", "一部")],
    "ko": [("항상", "결코"), ("모든", "일부"), ("반드시", "때때로")],
    "ar": [("دائما", "أبدا"), ("كل", "بعض")],
    "hi": [("हमेशा", "कभी नहीं"), ("सभी", "कोई नहीं")],
}
def _ko_subject(syllable: str) -> str:
    """Korean subject particle: 이 after a final consonant (능력이 아니다), 가 after a vowel (에너지가 아니다)."""
    code = ord(syllable) - 0xAC00
    return "이" if 0 <= code < 11172 and code % 28 else "가"


# (pattern that finds an affirmative verb, its negation) and (pattern of a negation, what to put back)
NEGATION_BY_LANG = {
    "de": ([(r"\b(ist|sind|wird|werden|kann|können|hat|haben)\b", r"\1 nicht")], [(r"\s+nicht\b", "")]),
    "fr": ([(r"\best\b", "n'est pas"), (r"\bsont\b", "ne sont pas"), (r"\bpeut\b", "ne peut pas")],
           [(r"\bn['’](\w+) pas\b", r"\1"), (r"\bne (\w+) pas\b", r"\1")]),
    "es": ([(r"\b(es|son|puede|pueden|tiene|tienen)\b", r"no \1")], [(r"\bno\s+", "")]),
    "it": ([(r"(?<!\w)(è|sono|può|possono|ha|hanno)(?!\w)", r"non \1")], [(r"\bnon\s+", "")]),
    "pt": ([(r"(?<!\w)(é|são|pode|podem|tem|têm)(?!\w)", r"não \1")], [(r"(?<!\w)não\s+", "")]),
    "ru": ([(r"(—\s*это)\b", r"\1 не"), (r"(?<!\w)(является|являются|может|могут)(?!\w)", r"не \1")],
           [(r"(?<!\w)не\s+", "")]),
    # 能 is left out: it starts 能量 (energy) and 能力; 是 and 会 skip common compounds (但是, 总是, 社会, 学会)
    "zh": ([(r"(?<![但于总就凡倒还也都即若或])是", "不是"), (r"(?<![社机学开体领理])会(?![议员])", "不会"),
            (r"可以", "不可以")],
           [(r"不(?=[是会能可])", "")]),
    "ja": ([(r"である", "ではない"), (r"できる", "できない"), (r"する。", "しない。")],
           [(r"ではない", "である"), (r"できない", "できる")]),
    "ko": ([(r"([가-힣])이다", lambda m: m.group(1) + _ko_subject(m.group(1)) + " 아니다"), (r"한다", "하지 않는다")],
           [(r"([가-힣])[이가] 아니다", r"\1이다"), (r"하지 않는다", "한다")]),
    "ar": ([(r"(?<!\w)هي(?!\w)", "ليست"), (r"(?<!\w)هو(?!\w)", "ليس")], [(r"(?<!\w)لا\s+", "")]),
    "hi": ([(r"(?<!नहीं )(?<![\u0900-\u097f])है(?=\s|[।॥.,;]|$)", "नहीं है")], [(r"नहीं\s+", "")]),
}
_NOSPACE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\u0e00-\u0eff]")


def _swap_word(text: str, a: str, b: str) -> str | None:
    # languages written without spaces have no word boundaries: match the plain string there
    rx = re.compile(re.escape(a) if _NOSPACE.search(a) else rf"(?<!\w){re.escape(a)}(?!\w)", re.I)
    m = rx.search(text)
    if not m:
        return None
    rep = b
    if m.group(0)[:1].isupper():
        rep = b[:1].upper() + b[1:]
    return text[: m.start()] + rep + text[m.end():]


_VOWEL = re.compile(r"[aeiouyhàâäéèêëîïôöùûüœæ]", re.I)
_ELIDING = re.compile(r"(?:^|\s)(?:le|la|de|que|je|ne|se|ce|me|te|lo|una|della|dello|nella)\s$", re.I)


def _elision_ok(text: str, start: int, replacement: str) -> bool:
    """French/Italian elide before vowels (l'énergie, d'acqua): a swapped term must not leave "d'calorie" or
    "de énergie", which would give the planted claim away."""
    vowel = bool(_VOWEL.match(replacement))
    if start > 0 and text[start - 1] in "'’":
        return vowel
    if vowel and _ELIDING.search(text[max(0, start - 8):start]):
        return False
    return True


def _changed_number(num: str, rng: random.Random) -> str:
    neg = num.startswith("-")
    core = num.lstrip("-")
    sep = "." if "." in core else ("," if "," in core else "")
    if sep:
        ip, fp = core.split(sep, 1)
        digits = list(ip + fp)
        if len(digits) >= 2 and digits[-1] != digits[-2]:
            digits[-1], digits[-2] = digits[-2], digits[-1]
            new = "".join(digits[: len(ip)]) + sep + "".join(digits[len(ip):])
        else:
            new = f"{float(ip + '.' + fp) * rng.choice([2, 3, 0.5]):.{len(fp)}f}".replace(".", sep)
    else:
        val = int(core)
        choices = [val * 2, val + (10 if val >= 20 else 1), max(1, val // 2) if val > 2 else val + 3]
        new = str(rng.choice([c for c in choices if c != val] or [val + 1]))
    return ("-" if neg else "") + new


LABEL_RE = re.compile(r"^(?P<label>.{2,120}?(?:—|→|When you see:).{0,120}?:\s)(?P<body>.+)$", re.S)


def mutate_claim(claim: str, context: str, terms: list[str] | None = None, seed: int = 0,
                 lang: str = "en") -> tuple[str, str] | None:
    """Return (false_claim, operator) or None if no safe mutation exists.

    Table, map and strategy claims look like '<label>: <content>'; only the content is mutated so the
    planted claim reads as naturally as the real ones."""
    m = LABEL_RE.match(claim)
    if m:
        out = _mutate(m.group("body"), context, terms, seed, lang)
        return (m.group("label") + out[0], out[1]) if out else None
    return _mutate(claim, context, terms, seed, lang)


def _base(lang: str) -> str:
    lang = (lang or "en").lower()
    return "zh" if lang.startswith("zh") else lang.split("-")[0]


def _mutate(claim: str, context: str, terms: list[str] | None, seed: int, lang: str = "en") -> tuple[str, str] | None:
    rng = random.Random(seed)
    ckey = key_of(context)
    base = _base(lang)
    ops = ["number", "antonym", "negation", "quantifier", "term"]
    rng.shuffle(ops)
    # most natural-sounding first: changed numbers, swapped opposites, negations; term swaps last
    ops.sort(key=lambda o: {"number": 0, "antonym": 1, "negation": 2, "quantifier": 3, "term": 4}[o] + 1.5 * rng.random())
    for op in ops:
        if op == "number":
            nums = list(re.finditer(r"(?<![\w.,])-?\d+(?:[.,]\d+)?(?![\w])", claim))
            rng.shuffle(nums)
            for m in nums:
                new = _changed_number(m.group(0), rng)
                if new == m.group(0) or key_of(new) in ckey:
                    continue
                return claim[: m.start()] + new + claim[m.end():], "number"
        elif op == "antonym":
            pairs = (ANTONYMS if base == "en" else ANTONYMS_BY_LANG.get(base, []))[:]
            rng.shuffle(pairs)
            for a, b in pairs:
                for x, y in ((a, b), (b, a)):
                    out = _swap_word(claim, x, y)
                    if out and key_of(y) not in ckey:
                        return out, "antonym"
        elif op == "quantifier":
            for a, b in (QUANTIFIERS if base == "en" else QUANTIFIERS_BY_LANG.get(base, [])):
                for x, y in ((a, b), (b, a)):
                    out = _swap_word(claim, x, y)
                    if _NOSPACE.search(y):
                        in_context = key_of(y) in ckey
                    else:
                        in_context = re.search(rf"(?<!\w){re.escape(y)}(?!\w)", context, re.I) is not None
                    if out and not in_context:
                        return out, "quantifier"
        elif op == "negation":
            if base == "en":
                if re.search(r"\bnot\b", claim, re.I):
                    out = re.sub(r"\s+not\b", "", claim, count=1, flags=re.I)
                    if out != claim:
                        return out, "negation"
                for aux in AUX:
                    m = re.search(rf"\b{aux}\b", claim)
                    if m and not re.search(rf"\b{aux}\s+not\b", context, re.I):
                        return claim[: m.end()] + " not" + claim[m.end():], "negation"
            elif base in NEGATION_BY_LANG:
                add, remove = NEGATION_BY_LANG[base]
                for pat, rep in remove:
                    out = re.sub(pat, rep, claim, count=1)
                    if out != claim and key_of(out) != key_of(claim):
                        return out, "negation"
                for pat, rep in add:
                    out = re.sub(pat, rep, claim, count=1)
                    if out != claim and key_of(out) not in ckey:
                        return out, "negation"
        elif op == "term" and terms:
            nospace = bool(_NOSPACE.search(claim))
            minlen = 2 if nospace else 4
            has = (lambda t, s: t.casefold() in s.casefold()) if nospace else \
                (lambda t, s: re.search(rf"(?<!\w){re.escape(t)}(?!\w)", s, re.I) is not None)
            present = [t for t in terms if len(t) >= minlen and has(t, claim)]
            # never swap a word inside a longer term ("energy" inside "kinetic energy")
            present = [t for t in present if not any(t != u and has(t, u) for u in present)]
            others = [t for t in terms if t not in present and len(t) >= minlen]
            rng.shuffle(present)
            rng.shuffle(others)
            for t in present:
                for o in others:
                    if key_of(o) in ckey:
                        continue
                    # a sub-type or super-type ("energy" -> "thermal energy") can make a claim that is arguably
                    # still true; such canaries would punish careful checkers, so only swap unrelated terms
                    if set(o.lower().split()) & set(t.lower().split()) or (nospace and (t in o or o in t)):
                        continue

                    pat = re.escape(t) if nospace else rf"(?<!\w){re.escape(t)}(?!\w)"
                    m = re.search(pat, claim, re.I)
                    if not m or not _elision_ok(claim, m.start(), o):
                        continue
                    # keep the capitalization of the replaced word so the canary has no visual tell
                    rep = o[:1].upper() + o[1:] if m.group(0)[:1].isupper() else o
                    out = claim[: m.start()] + rep + claim[m.end():]
                    if out != claim:
                        return out, "term"
    return None


def mismatched_context(claim: str, contexts: list[str], rng: random.Random) -> str | None:
    """A context from elsewhere in the book that shares little with the claim: shown next to the claim it makes
    a planted false item in any language (the context does not say what the claim says)."""
    ck = key_of(claim)
    grams = {ck[i:i + 3] for i in range(max(0, len(ck) - 2))}
    cands = []
    for ctx in contexts:
        kk = key_of(ctx)
        if not kk or not grams:
            continue
        overlap = sum(1 for g in grams if g in kk) / len(grams)
        if overlap < 0.2:
            cands.append(ctx)
    return rng.choice(cands) if cands else None


def mutate_latex(latex: str, seed: int = 0) -> tuple[str, str] | None:
    """A wrong transcription of a formula (for formula-check canaries)."""
    rng = random.Random(seed)
    cands = []
    if "+" in latex:
        cands.append((latex.replace("+", "-", 1), "sign"))
    if "-" in latex:
        cands.append((latex.replace("-", "+", 1), "sign"))
    m = re.search(r"\^\{?(\d)\}?", latex)
    if m:
        new_exp = "3" if m.group(1) == "2" else "2"
        cands.append((latex[: m.start()] + "^" + new_exp + latex[m.end():], "exponent"))
    m = re.search(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", latex)
    if m:
        cands.append((latex[: m.start()] + f"\\frac{{{m.group(2)}}}{{{m.group(1)}}}" + latex[m.end():], "fraction"))
    letters = re.findall(r"(?<![\\A-Za-z])([A-Za-z])(?![A-Za-z])", latex)
    uniq = [l for l in dict.fromkeys(letters)]
    if len(uniq) >= 2:
        a, b = uniq[-1], uniq[-2]
        swapped = re.sub(rf"(?<![\\A-Za-z]){a}(?![A-Za-z])", "\u0000", latex)
        swapped = re.sub(rf"(?<![\\A-Za-z]){b}(?![A-Za-z])", a, swapped).replace("\u0000", b)
        if swapped != latex:
            cands.append((swapped, "swap"))
    if "=" in latex:
        lhs, rhs = latex.split("=", 1)
        cands.append((f"{lhs}= 2 {rhs.strip()}", "factor"))
    rng.shuffle(cands)
    for out, op in cands:
        if key_of(out) != key_of(latex):
            return out, op
    return None
