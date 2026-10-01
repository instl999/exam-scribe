"""Stage 2: build a deterministic inventory (checklist) of what each chapter contains.

The inventory is the ground truth for coverage: every key term, numbered
equation, figure, worked example, learning objective and summary sentence
gets a stable ID. Notes are later checked against it, so omissions become
visible instead of silent.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

from . import lang as L
from .common import (ESError, Workspace, build_key, estimate_tokens, fix_ligatures, key_of, numbers_in, read_json,
                     slugify, split_sentences, write_json)
from .ingest import BULLET_RE, CAPTION_RE, END_MATTER, EQ_NUM_RE, section_paragraphs

NOT_TERMS = re.compile(r"^(?:(?:solution|answer|answers|example|examples|note|notes|step|steps|hint|figure|fig|table|"
                       r"check your learning|learning objectives?|learning outcomes|objectives?|key terms|summary|"
                       r"review|exercise|exercises|problem|problems|practice|strategy|discussion|significance|"
                       r"link to learning|chapter|section|unit|part|lesson|appendix|warning|caution|remember|"
                       r"tip|important|definition|theorem|proof|lemma|corollary|given|find|analysis)\b|"
                       r"(?:" + L._alt(L.NOT_TERM_WORDS + L.FIGURE + L.TABLE + L.EXAMPLE + L.CHAPTER_WORDS +
                                       L.INTRO_WORDS) + r")"
                       r"(?![^\W\d_]))", re.I)
LO_HEAD = L.head_re(L.OBJECTIVES)
EXAMPLE_HEAD = re.compile(r"^(?:" + L._alt(L.EXAMPLE) + r")\s*(?P<num>\d+(?:[.\-]\d+)*[a-z]?)(?!\d)"
                          r"\s*[:.：—-]?\s*(?P<title>.*)$", re.I)
SUMMARY_HEAD = L.head_re(L.SUMMARY)
KEYTERMS_HEAD = L.head_re(L.KEY_TERMS)
KEYEQ_HEAD = L.head_re(L.KEY_EQUATIONS)
EXERCISE_HEAD = L.head_re(L.EXERCISES)
SECTION_REF = re.compile(r"^(\d+(?:\.\d+)+)\s+\S")
XREF = re.compile(r"(?:\b(?:Chapters?|Sections?|Kapitel|Abschnitt|Chapitre|Capítulo|Sección|Capitolo|Sezione|Seção|"
                  r"Hoofdstuk|Глав[аеуы]|Раздел[ае]?|Rozdzia[łl]|Bölüm|Chương|Bab)\s+|第\s*|제\s*)(\d+)(?:\.(\d+))?",
                  re.I)
_KEEP_CASE = [False]         # set per book: German capitalises every noun


def _canon_term(raw: str) -> tuple[str, str, str]:
    """Return (canonical text, display text, symbol) for a bold run."""
    t = fix_ligatures(raw).strip(" \t,;:.—-?!¿¡")
    sym = ""
    m = re.match(r"^(.*?)\s*\(([^()]{1,14})\)$", t)
    if m and m.group(1):
        t, sym = m.group(1).strip(), m.group(2).strip()
    words = t.split()
    if not words:
        return "", "", ""
    # lower-case a sentence-initial capital unless the word looks like an acronym or a name (German nouns are
    # always capitalised, so German keeps the case)
    first = words[0]
    if first[:1].isupper() and first[1:].islower() and not _KEEP_CASE[0]:
        words[0] = first.lower()
    canon = " ".join(words)
    display = canon[:1].upper() + canon[1:]
    return canon, display, sym


def _sentence_at(text: str, offset: int) -> str:
    """The sentence of `text` that contains character `offset`."""
    pos = 0
    best = None
    for s in split_sentences(text):
        i = text.find(s[:15], pos)
        if i < 0:
            continue
        if i > offset:
            break
        best = s
        pos = i + max(1, len(s) - 5)
    return best or text[:300]


def _term_ok(canon: str) -> bool:
    if not canon or len(canon) > 60 or len(canon.split()) > 6:
        return False
    if (len(canon.replace(" ", "")) < 2 and not _CJK.search(canon)) or canon[0].isdigit():
        return False
    if NOT_TERMS.match(canon):
        return False
    if CAPTION_RE.match(canon):
        return False
    if re.fullmatch(r"[\W\d_]+", canon):
        return False
    if _HAN_KANA.search(canon) and not _cjk_term_ok(canon):
        return False
    # "x, y", "_x", "a b c": symbols and formula pieces from equations, not terms ("C++", "TCP/IP" are fine)
    words = re.findall(r"[^\W\d_]+", canon)
    if re.search(r"[_^{}=<>\\|]", canon) or (not _CJK.search(canon) and len(words) >= 2 and
                                              all(len(w) == 1 for w in words)):
        return False
    return True


_HAN_KANA = re.compile(r"[぀-ヿ㐀-䶿一-鿿]")
# Chinese / Japanese terms are short noun phrases: no punctuation, no spaces, no clause particles or verb endings
_CJK_PUNCT = re.compile(r"[，,、。．.！!？?：:；;「」『』（）()〈〉《》【】“”‘’\"'…\s]")
_JA_NOT_TERM = re.compile(r"[をがは]|(?:[うくぐすつぬぶむるたてでとにへやかもよねなしど]|こと|もの|ため|ように)$|"
                          r"^(?:ただし|また|しかし|さらに|そして|なお|例えば|特に|一方|つまり|すなわち|このような|そのような|"
                          r"これら|それら|この|その|あの|どの|ここ|そこ|[ぁ-ゖ])")


def _cjk_term_ok(canon: str) -> bool:
    if _CJK_PUNCT.search(canon) or len(canon) > 16:
        return False
    if re.search(r"[A-Za-z0-9][和与及或][A-Za-z0-9]", canon):    # "x和y": a list of symbols
        return False
    if re.search(r"[぀-ゟ]", canon) and _JA_NOT_TERM.search(canon):     # Japanese (has hiragana)
        return False
    return True


class _Ctx:
    def __init__(self, ws: Workspace, ch: dict):
        self.ws = ws
        self.ch = ch
        self.items: list[dict] = []
        self.ids: set[str] = set()

    def add(self, item: dict) -> dict:
        base = item["id"]
        n = 2
        while item["id"] in self.ids:
            item["id"] = f"{base}-{n}"
            n += 1
        self.ids.add(item["id"])
        self.items.append(item)
        return item


def _paras_for(ws: Workspace, sec: dict) -> list[tuple[dict, dict]]:
    return [(pg, p) for pg, p in section_paragraphs(ws, sec)]


def chapter_inventory(ws: Workspace, ch: dict, figures: list[dict], global_terms: dict[str, dict],
                      doc=None) -> dict:
    cx = _Ctx(ws, ch)
    content_secs = [s for s in ch["sections"] if s["kind"] == "content"]
    end_secs = [s for s in ch["sections"] if s["kind"] == "end"]
    sec_info = []
    # ---- chapter intro text (before the first section), useful for overview citations
    intro = None
    first = ch["sections"][0]["start"] if ch["sections"] else ch["end"]
    intro_pairs = section_paragraphs(ws, {"start": ch["start"], "end": first})
    intro_text = " ".join(p["text"] for _, p in intro_pairs if not p["heading"])
    if intro_text:
        intro = {"page": intro_pairs[0][0]["label"], "text": intro_text[:1500]}

    lo_terms_text = []
    # ---- end matter first (glossary / key equations / summary / exercises), used as signals
    glossary: list[dict] = []
    key_equations: list[dict] = []
    summary_items: list[dict] = []
    exercises: list[dict] = []
    exercise_counts: Counter = Counter()
    sum_n = 0
    for sec in end_secs + content_secs:
        pairs = _paras_for(ws, sec)
        mode = None
        if sec["kind"] == "end":
            t = sec["title"]
            mode = ("glossary" if KEYTERMS_HEAD.match(t) else "keyeq" if KEYEQ_HEAD.match(t) else
                    "summary" if SUMMARY_HEAD.match(t) else "exercise" if EXERCISE_HEAD.match(t) else None)
        cur_section = sec["id"] if sec["kind"] == "content" else None
        for page, p in pairs:
            text = p["text"].strip()
            if p["heading"]:
                if sec["kind"] == "content":
                    mode = ("summary" if SUMMARY_HEAD.match(text) else "exercise" if EXERCISE_HEAD.match(text)
                            else "glossary" if KEYTERMS_HEAD.match(text) else None) or \
                           (mode if mode in ("summary", "exercise", "glossary") and not SECTION_REF.match(text) else None)
                m = SECTION_REF.match(text)
                if m and sec["kind"] == "end":
                    cur_section = m.group(1)
                elif sec["kind"] == "end" and (KEYTERMS_HEAD.match(text) or KEYEQ_HEAD.match(text) or
                                               SUMMARY_HEAD.match(text) or EXERCISE_HEAD.match(text)):
                    mode = ("glossary" if KEYTERMS_HEAD.match(text) else "keyeq" if KEYEQ_HEAD.match(text) else
                            "summary" if SUMMARY_HEAD.match(text) else "exercise")
                continue
            if mode == "glossary":
                starts = [r for r in p["bold"]]
                if not starts:
                    continue
                for i, (a, b) in enumerate(starts):
                    nxt = starts[i + 1][0] if i + 1 < len(starts) else len(text)
                    canon, display, sym = _canon_term(text[a:b])
                    definition = text[b:nxt].strip(" :—-")
                    if canon:
                        glossary.append({"term": canon, "display": display, "symbol": sym, "definition": definition,
                                         "page": page["label"]})
            elif mode == "keyeq":
                for line in re.split(r"\s{2,}|\n", text):
                    if "=" in line:
                        key_equations.append({"text": line.strip(), "page": page["label"]})
            elif mode == "summary":
                for s in split_sentences(text):
                    if len(s) < 12:
                        continue
                    sum_n += 1
                    summary_items.append({"id": f"SUM-{ch['id']}-{sum_n}", "kind": "summary", "text": s,
                                          "page": page["label"], "section": cur_section})
            elif mode == "exercise":
                # numbered items, even when several were merged into one paragraph; numbers must run in sequence
                last_n = int(exercises[-1]["number"]) if exercises else 0
                cands = [m for m in re.finditer(r"(?:^|(?<=\s))(\d{1,3})(?:[.)]\s+|[．、]\s*)(?=[(¿¡«\"“„]?[^\W_])", text)
                         if not text[m.end():m.end() + 2].lstrip("(¿¡«\"“„")[:1].islower()]
                for i, m in enumerate(cands):
                    n = int(m.group(1))
                    if exercises and n != last_n + 1:
                        continue          # not the next exercise number: a number inside the text
                    end = cands[i + 1].start() if i + 1 < len(cands) else len(text)
                    exercises.append({"number": m.group(1), "text": text[m.end():end].strip()[:400],
                                      "section": cur_section, "page": page["label"]})
                    last_n = n
                    if cur_section:
                        exercise_counts[cur_section] += 1

    glossary_keys = {key_of(g["term"]): g for g in glossary}
    for s in summary_items:
        cx.add(s)

    # ---- content sections
    figs_by_page: dict[int, list[dict]] = defaultdict(list)
    for f in figures:
        figs_by_page[f["page_index"]].append(f)
    n_uneq = 0
    for sec in content_secs:
        pairs = _paras_for(ws, sec)
        pages = []
        for page, _ in pairs:
            if page["label"] not in pages:
                pages.append(page["label"])
        text_all = "\n".join(p["text"] for _, p in pairs)
        sec_info.append({"id": sec["id"], "title": sec["title"], "kind": "content", "pages": pages,
                         "tokens": estimate_tokens(text_all), "start": sec["start"], "end": sec["end"]})
        lo_mode = False
        lo_n = 0
        example_open: dict | None = None
        prev_text = ""
        sec_has_bold = False
        for idx, (page, p) in enumerate(pairs):
            text = p["text"].strip()
            if p.get("in_figure"):
                continue
            # learning objectives
            if LO_HEAD.match(text):
                lo_mode = True
                continue
            if lo_mode:
                if BULLET_RE.match(text):
                    lo_n += 1
                    lo_text = BULLET_RE.sub("", text, count=1).strip()
                    lo_terms_text.append(lo_text)
                    cx.add({"id": f"LO-{sec['id']}-{lo_n}", "kind": "objective", "text": lo_text,
                            "page": page["label"], "section": sec["id"]})
                    continue
                lo_mode = False
            # worked examples
            m = EXAMPLE_HEAD.match(text)
            if m and (p["heading"] or p["box"] >= 0 or len(text) < 90):
                example_open = cx.add({"id": f"WE-{m.group('num')}", "kind": "example",
                                       "number": m.group("num"), "title": (m.group("title") or "").strip(),
                                       "page": page["label"], "pages": [page["label"]], "section": sec["id"],
                                       "box": p["box"], "text": ""})
                continue
            if example_open is not None:
                same_box = example_open["box"] >= 0 and p["box"] == example_open["box"] and \
                    page["label"] in example_open["pages"][-1:]
                if same_box or (example_open["box"] < 0 and not p["heading"] and len(example_open["text"]) < 1500):
                    example_open["text"] = (example_open["text"] + " " + text).strip()
                    if page["label"] not in example_open["pages"]:
                        example_open["pages"].append(page["label"])
                    continue
                example_open = None
            # equations
            em = EQ_NUM_RE.search(text)
            if em and p.get("math"):
                num = em.group(1)
                eq_text = text[: em.start()].strip()
                after = pairs[idx + 1][1]["text"] if idx + 1 < len(pairs) else ""
                item = cx.add({"id": f"EQ-{num}", "kind": "equation", "number": num, "text": eq_text,
                               "page": page["label"], "section": sec["id"],
                               "context_before": split_sentences(prev_text)[-1] if prev_text else "",
                               "context_after": split_sentences(after)[0] if after else "",
                               "bbox": [p["x0"], p["y0"], p["x1"], p["y1"]], "page_index": page["index"]})
                _link_equation(ws, item)
            elif p.get("math") and p["box"] < 0 and prev_text.rstrip().endswith(":") and "=" in text and \
                    not re.search(r"=\s*[−-]?\d[\d.,\s]*(?:[^\W\d_][^\s=]{0,10}\s*){0,2}$", text):
                # (a result such as "ΔH = −153 kJ" is a worked answer, not an equation to learn)
                n_uneq += 1
                item = cx.add({"id": f"EQ-{ch['id']}-u{n_uneq}", "kind": "equation", "number": None, "text": text,
                               "page": page["label"], "section": sec["id"],
                               "context_before": split_sentences(prev_text)[-1] if prev_text else "",
                               "context_after": "", "bbox": [p["x0"], p["y0"], p["x1"], p["y1"]],
                               "page_index": page["index"]})
                _link_equation(ws, item)
            # key terms (bold runs in body text)
            if not p["heading"] and not p.get("caption"):
                for a, b in p["bold"]:
                    canon, display, sym = _canon_term(text[a:b])
                    if not _term_ok(canon):
                        continue
                    if a == 0 and b >= len(text) - 1:
                        continue          # a fully bold paragraph is a heading, not a term
                    sec_has_bold = True   # bold marks terms in this section (labels like "Example 2.1" do not count)
                    after = text[b:b + 20]
                    if not sym:
                        sm = re.match(r"^\s*\(([^()]{1,12})\)", after)
                        if sm and len(sm.group(1).split()) <= 2:
                            sym = sm.group(1)
                    k = key_of(canon)
                    if k in global_terms:
                        global_terms[k].setdefault("also_in", [])
                        if ch["id"] != global_terms[k]["chapter"] and ch["id"] not in global_terms[k]["also_in"]:
                            global_terms[k]["also_in"].append(ch["id"])
                        continue
                    item = cx.add({"id": "T-" + slugify(canon), "kind": "term", "text": canon, "display": display,
                                   "symbol": sym, "page": page["label"], "section": sec["id"],
                                   "context": _sentence_at(text, a), "boxed": p["box"] >= 0,
                                   "in_glossary": k in glossary_keys})
                    item["chapter"] = ch["id"]
                    global_terms[k] = item
            prev_text = text
        # no bold terms (OCR'd pages, or books that mark terms differently): fall back to defining phrases
        if not sec_has_bold:
            _definition_terms(cx, ch, sec, pairs, global_terms, glossary_keys)
        # figures in this section
        sec_pages_idx = {pg["index"] for pg, _ in pairs}
        for pidx in sorted(sec_pages_idx):
            for f in figs_by_page.get(pidx, []):
                ypos = next((p["y0"] for pg, p in pairs if pg["index"] == pidx and p["text"] == f["caption"]), None)
                if ypos is None:
                    continue
                cx.add({"id": f["id"], "kind": f["kind"], "number": f["number"], "caption": f["caption"],
                        "page": f["page"], "section": sec["id"], "image": f.get("image")})

    # glossary terms never bolded in the body: find their first use in this chapter
    known = {key_of(it["text"]) for it in cx.items if it["kind"] == "term"} | set(global_terms)
    for g in glossary:
        k = key_of(g["term"])
        if k in known:
            continue
        hit = None
        for sec in content_secs:
            for page, p in _paras_for(ws, sec):
                pk = p["text"].casefold()
                pos = pk.find(g["term"].casefold())
                if pos >= 0:
                    hit = (sec, page, p, pos)
                    break
            if hit:
                break
        item = {"id": "T-" + slugify(g["term"]), "kind": "term", "text": g["term"], "display": g["display"],
                "symbol": g["symbol"], "in_glossary": True, "boxed": False, "chapter": ch["id"]}
        if hit:
            sec, page, p, pos = hit
            item.update({"page": page["label"], "section": sec["id"], "context": _sentence_at(p["text"], pos)})
        else:
            item.update({"page": g["page"], "section": content_secs[0]["id"] if content_secs else None,
                         "context": f"{g['term']}: {g['definition']}", "glossary_only": True})
        cx.add(item)
        global_terms[k] = item
        known.add(k)

    # signals
    lo_blob = key_of(" ".join(lo_terms_text))
    sum_blob = key_of(" ".join(s["text"] for s in summary_items))
    keyeq_keys = [key_of(e["text"]) for e in key_equations]
    for it in cx.items:
        if it["kind"] == "term":
            k = key_of(it["text"])
            stem = k[:-1] if k.endswith("s") else k
            it["signals"] = {"bold": not it.get("glossary_only", False) and it.get("found_by") != "definition",
                             "boxed": it.get("boxed", False),
                             "in_glossary": bool(it.get("in_glossary")), "in_objectives": bool(stem and stem in lo_blob),
                             "in_summary": bool(stem and stem in sum_blob)}
        elif it["kind"] == "equation":
            k = key_of(it["text"])
            it["signals"] = {"numbered": bool(it.get("number")),
                             "in_key_equations": any(k and (k in ke or ke in k) for ke in keyeq_keys if ke)}
    return {"chapter": ch["id"], "number": ch["number"], "title": ch["title"],
            "sections": sec_info, "items": cx.items, "glossary": glossary, "key_equations": key_equations,
            "exercises": exercises, "exercise_counts": dict(exercise_counts), "intro": intro}


def _link_equation(ws: Workspace, item: dict) -> None:
    """Pictures of printed equations are made per chapter by media.py; link one that already exists."""
    rel = f"source/equations/{item['id']}.png"
    item["image"] = rel if (ws.root / rel).exists() else None


# Defining phrases, used when a section has no bold text (OCR'd pages have none; some books use colour instead).
_W = r"[^\W\d_][\w\-]*"
_P = r"(?:\s*\([^()]{1,12}\))?"                          # an optional symbol in parentheses after the term
DEFINITION_PATTERNS = [
    re.compile(rf"(?:^|(?<=[.!?]\s))(?:An?\s+|The\s+)?(?P<t>{_W}(?:\s+{_W}){{0,4}}?)\s+(?:is|are)\s+"
               rf"(?:defined\s+as|the\s+name\s+(?:given\s+)?(?:to|for))\b"),
    re.compile(rf"\b(?:is|are|was|were)\s+(?:called|known\s+as|termed|referred\s+to\s+as|named)\s+"
               rf"(?:an?\s+|the\s+)?[\"“‘']?(?P<t>{_W}(?:\s+{_W}){{0,5}}?)[\"”’']?(?=\s*[,.;:)(]|\s+(?:and|or|which|that|because|when|if)\b)"),
    re.compile(rf"\bwe\s+(?:call|define)\s+(?:this|it|these|them|such\s+\w+)\s+(?:an?\s+|the\s+)?[\"“‘']?"
               rf"(?P<t>{_W}(?:\s+{_W}){{0,5}}?)[\"”’']?(?=\s*[,.;:)])"),
    # a term introduced with its symbol: "... is the joule (J).", "An older unit, the calorie (cal), was ..."
    re.compile(rf"\b(?:is|are)\s+(?:the|an?)\s+(?P<t>{_W}(?:\s+{_W}){{0,2}})\s*\([^()\s]{{1,6}}\)\s*[.;]"),
    re.compile(rf",\s+the\s+(?P<t>{_W}(?:\s+{_W}){{0,2}})\s*\([^()\s]{{1,6}}\),"),
    # other languages: "... nennt man X", "... s'appelle X", "... se llama X", "... называется X", "称为X"
    re.compile(rf"\b(?:nennt\s+man|bezeichnet\s+man\s+als|heißt|s['’]appelle|appelée?s?|se\s+llama|se\s+denomina|"
               rf"llamad[oa]s?|si\s+chiama|dett[oa]|chama-se|denominad[oa]|называ(?:ется|ют)|называемая)\s+"
               rf"[\"“‘'«„]?(?P<t>{_W}(?:\s+{_W}){{0,3}}?)[\"”’'»“]?(?=\s*[,.;:)(]|$)"),
    re.compile(r"(?:称为|叫做|称作)[“\"「]?(?P<t>[一-鿿]{1,10}?)[”\"」]?(?=[，。；、：,.;:（(]|$)"),
    re.compile(r"所谓[“\"「]?(?P<t>[一-鿿]{2,10}?)[”\"」]?[，,]?(?:就是|是指|指的是|是)"),
    re.compile(r"(?:^|[。；]\s*)(?P<t>[一-鿿]{1,8}?)(?:[（(][^）)]{1,10}[）)])?(?:是指|(?:最初|通常)?被定义为)"),
    re.compile(r"を(?P<t>[^、。をは\s]{1,12}?)と(?:いう|よぶ|呼ぶ)"),
    re.compile(r"को\s+(?P<t>[ऀ-ॿ]+(?:\s+[ऀ-ॿ]+){0,2}?)\s+(?:कहते|कहा\s+जाता)"),
]
# "Kinetic energy is the energy that ...", "Energie ist die Fähigkeit ...", "Энергия — это ...", "能量是...的能力":
# only at the start of a sentence, where textbooks put definitions
COPULA_PATTERNS = [
    re.compile(rf"^(?:(?:The|A|An)\s+)?(?P<t>{_W}(?:\s+{_W}){{0,3}}?){_P}(?:\s+of\s+(?:an?|the)\s+{_W})?"
               rf"\s+(?:is|are)\s+(?:the|a|an)\s+(?:{_W}\s+){{0,3}}?{_W}\s+(?:that|which|who|of|to|used|needed|required|"
               rf"for|in\s+which|where|by\s+which|with)\b"),
    re.compile(rf"^(?:(?:Die|Der|Das|Eine?|Unter)\s+)?(?P<t>{_W}(?:\s+{_W}){{0,3}}?){_P}\s+(?:ist|sind)\s+"
               rf"(?:die|der|das|ein|eine|einen|diejenige)\s"),
    re.compile(rf"^(?:(?:La|Le|Les|Un|Une)\s+|L['’])?(?P<t>{_W}(?:\s+{_W}){{0,3}}?){_P}\s+(?:est|sont)\s+"
               rf"(?:la|le|les|un|une|l['’])"),
    re.compile(rf"^(?:(?:La|El|Los|Las|Un|Una)\s+)?(?P<t>{_W}(?:\s+{_W}){{0,3}}?){_P}\s+(?:es|son)\s+"
               rf"(?:la|el|los|las|un|una|lo)\s"),
    re.compile(rf"^(?:(?:La|Il|Lo|Gli|Le|I|Un|Una|Uno)\s+|L['’])?(?P<t>{_W}(?:\s+{_W}){{0,3}}?){_P}\s+(?:è|sono)\s+"
               rf"(?:la|il|lo|l['’]|un|una|uno|gli|le|i)\b"),
    re.compile(rf"^(?:(?:A|O|As|Os|Um|Uma)\s+)?(?P<t>{_W}(?:\s+{_W}){{0,3}}?){_P}\s+(?:é|são)\s+(?:a|o|as|os|um|uma)\s"),
    re.compile(rf"^(?P<t>{_W}(?:\s+{_W}){{0,3}}?){_P}\s*[—–-]\s*это\b"),
    # "X was (originally) defined as ...", in several languages (OCR'd pages have no bold to find terms by)
    re.compile(rf"^(?:(?:The|A|An)\s+)?(?P<t>{_W}(?:\s+{_W}){{0,3}}?){_P}\s+(?:is|are|was|were)\s+(?:\w+\s+)?"
               rf"defined\s+as\b"),
    re.compile(rf"^(?:(?:La|Le|Les|Un|Une)\s+|L['’])?(?P<t>{_W}(?:\s+{_W}){{0,3}}?){_P}\s+(?:est|sont|a\s+été|"
               rf"ont\s+été|fut)\s+défini(?:e|s|es)?\s+(?:\S+\s+){{0,3}}?comme\b"),
    re.compile(rf"^(?:(?:La|El|Los|Las|Un|Una)\s+)?(?P<t>{_W}(?:\s+{_W}){{0,3}}?){_P}\s+(?:se\s+define|se\s+definió|"
               rf"se\s+definen|(?:es|son|fue|fueron)\s+definid[oa]s?)\s+(?:\S+\s+){{0,2}}?como\b"),
    re.compile(rf"^(?:(?:Die|Der|Das|Eine?)\s+)?(?P<t>{_W}(?:\s+{_W}){{0,3}}?){_P}\s+(?:ist|sind|wird|werden|wurde|"
               rf"wurden)\s+(?:\S+\s+){{0,2}}?(?:definiert\s+als\b|als\s+[^.;]{{3,90}}?\s+definiert\b)"),
    re.compile(rf"^(?:(?:La|Il|Lo|Gli|Le|I|Un|Una|Uno)\s+|L['’])?(?P<t>{_W}(?:\s+{_W}){{0,3}}?){_P}\s+"
               rf"(?:è|sono|fu|(?:è|fu)\s+stat[oa])\s+(?:\S+\s+){{0,1}}?definit[oaie]\s+(?:\S+\s+){{0,2}}?come\b"),
    re.compile(rf"^(?:(?:A|O|As|Os|Um|Uma)\s+)?(?P<t>{_W}(?:\s+{_W}){{0,3}}?){_P}\s+(?:é|são|foi|foram)\s+"
               rf"(?:\S+\s+){{0,1}}?definid[oa]s?\s+(?:\S+\s+){{0,2}}?como\b"),
    re.compile(rf"^(?P<t>{_W}(?:\s+{_W}){{0,2}}?){_P}\s+(?:\S+\s+){{0,2}}?(?:определяется|определяются|"
               rf"был[аио]?\s+определен[аоы]?|определён|определена)\s+(?:\S+\s+){{0,2}}?как\b"),
    re.compile(r"^(?P<t>[一-鿿]{1,8}?)(?:[（(][^）)]{1,12}[）)])?是指"),
    # "(所谓)X，即Y" / "X就是Y" at the start of a sentence
    # "所谓X，即/就是Y", "X，即Y" (not 即使 "even if"; a bare "X就是Y" is ordinary speech, not a definition)
    re.compile(r"^所谓(?P<t>[一-鿿]{2,8}?)[，,]?就是(?=[^。]{4,})"),
    re.compile(r"^(?:所谓)?(?P<t>[一-鿿]{2,8}?)[，,]?即(?![使便将可刻时])(?=[^。]{4,})"),
    # "X是...的<kind>": the predicate must name what kind of thing X is (a kind-word, or a clause ending in
    # "...的<noun>"), or it is not a definition
    re.compile(r"^(?P<t>[一-鿿]{1,8}?)(?:[（(][^）)]{1,12}[）)])?是(?=[^。]*(?:过程|活动|现象|系统|方式|手段|能力|学科|科学|概念|总称|行为|关系|形式|方法|理论|机制|结构|状态|属性|特征|功能|作用|群体|组织|产业|事业|技术|媒介|符号|工具|体系|环节|要素|总和|整体|现象|规律|原理|模式|制度)|[^。，]*的[一-鿿]{1,6}(?:[。，；]|$))"),
    re.compile(r"^(?P<t>[^、。\s]{1,15}?)とは"),
    re.compile(r"^(?P<t>[^、。\s]{1,12}?)は(?=[^。]*(?:である|のことである|という|と定義され|として定義され)[^。]{0,4}[。]?$)"),
    re.compile(r"^(?P<t>[가-힣A-Za-z ]{1,15}?)(?:이란|란|은|는)\s(?=.*(?:이다|말한다|뜻한다|정의된다|정의되었다|정의한다|이라고 한다|라고 한다)\.?$)"),
    re.compile(r"^(?P<t>[؀-ۿ]+(?:\s+[؀-ۿ]+){0,2}?)\s+(?:هي|هو)\s"),
    re.compile(r"^(?P<t>[ऀ-ॿ]+(?:\s+[ऀ-ॿ]+){0,2}?)\s+(?:वह|वे)\s"),
    re.compile(r"^(?P<t>[ऀ-ॿ]+(?:\s+[ऀ-ॿ]+){0,2}?)\s+को\s(?=.*(?:परिभाषित|कहते|कहा\s+जाता))"),
]
NOT_DEFINED = {"this", "that", "these", "those", "it", "there", "here", "which", "what", "one", "each", "such", "other",
               "another", "result", "answer", "example", "solution", "figure", "table", "equation", "value", "reason",
               "goal", "purpose", "first", "second", "next", "last", "step", "problem", "question", "following", "we",
               "they", "he", "she", "you", "i", "all", "most", "some", "many", "both", "only", "chapter", "section",
               "where", "when", "if", "since", "because", "thus", "then", "so", "therefore", "hence", "however", "also",
               "its", "their", "his", "her", "our", "your", "my", "no", "any", "every", "same", "main", "key",
               "important", "difference", "idea", "point", "aim", "way", "unit", "amount", "number", "part",
               # German, French, Spanish, Italian, Portuguese, Russian
               "es", "er", "sie", "dies", "dieses", "diese", "dieser", "das", "man", "wir", "ergebnis", "beispiel",
               "auch", "denn", "doch", "aber", "nun", "dann", "dort", "hier", "fürs", "was", "wer", "wie", "wo",
               "noch", "schon", "nur", "sehr", "damit", "dabei", "dafür", "daher", "deshalb", "trotzdem", "jedoch",
               "zudem", "außerdem", "erst", "zuerst", "heute", "jetzt", "immer", "oft", "also", "ebenso", "sonst",
               "nicht", "kein", "keine", "jeder", "jede", "jedes", "alle", "viele", "einige", "beide", "wenn", "weil",
               "dass", "ob", "als", "dazu", "davon", "darin", "somit", "folglich", "zwar", "insbesondere", "etwa",
               "bereits", "gleichzeitig", "vielmehr", "hingegen", "allerdings", "dennoch", "zunächst", "schließlich",
               "zum", "zur", "im", "am", "vom", "beim", "ins", "sein", "seine", "ihr", "ihre", "unser", "unsere",
               "mein", "meine", "dein", "deine", "jener", "jene", "solche", "welche", "welcher",
               "il", "elle", "ce", "cela", "ceci", "on", "nous", "résultat", "exemple", "esto", "esta", "este",
               "plus", "moins", "quand", "lorsque", "comme", "si", "ainsi", "alors", "donc", "puis", "aussi", "mais",
               "car", "cuanto", "cuanta", "cuantos", "cuantas", "cuando", "donde", "como", "mientras", "aunque",
               "más", "menos", "también", "pero", "quanto", "quanta", "quando", "dove", "come", "più", "meno",
               "anche", "però", "mentre", "quanto", "mais", "menos", "também", "porém", "enquanto", "embora",
               "ello", "se", "resultado", "ejemplo", "questo", "questa", "risultato", "esempio", "isso", "isto",
               "это", "он", "она", "оно", "они", "мы", "результат", "пример",
               # Japanese, Korean
               "これ", "それ", "あれ", "この", "その", "ここ", "이것", "그것", "이", "그", "저", "이러한", "그러한"}
_CJK_NOT_DEFINED = re.compile(r"^(?:这|那|它|其|此|该|每|本|我|你|他|她|们|第|也|又|还|就|但|因|所|由于|如果|例如|结果|答案|下面|上面|值得|许多|很多|一些|有些|一种|一个|虽然|即使|只有|不仅|同时|首先|其次|最后|总之|可见)"
                              r"|[的所和与及或]|[又都就正既并也还才只却便即乃亦了不总然]$")
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")


def _definition_terms(cx: _Ctx, ch: dict, sec: dict, pairs: list[tuple[dict, dict]], global_terms: dict[str, dict],
                      glossary_keys: dict) -> None:
    for page, p in pairs:
        if p["heading"] or p.get("caption") or p.get("in_figure"):
            continue
        text = p["text"]
        found: list[tuple[int, str]] = []            # (offset in paragraph, term text)
        pos = 0
        for s in split_sentences(text):
            at = text.find(s[:15], pos)
            at = pos if at < 0 else at
            pos = at + max(1, len(s) - 5)
            for pat in COPULA_PATTERNS:
                cm = pat.match(s)
                if cm:
                    found.append((at + cm.start("t"), cm.group("t")))
                    break
        found += [(m.start("t"), m.group("t")) for pat in DEFINITION_PATTERNS for m in pat.finditer(text)]
        for offset, raw in sorted(found):
            canon, display, sym = _canon_term(raw)
            cjk = bool(_CJK.search(canon))
            if not _term_ok(canon) or canon.split()[0].lower() in NOT_DEFINED or (len(canon) < 3 and not cjk) or \
                    (cjk and _CJK_NOT_DEFINED.search(canon)):
                continue
            k = key_of(canon)
            if k in global_terms:
                continue
            item = cx.add({"id": "T-" + slugify(canon), "kind": "term", "text": canon, "display": display,
                           "symbol": sym, "page": page["label"], "section": sec["id"],
                           "context": _sentence_at(text, offset), "boxed": p["box"] >= 0,
                           "in_glossary": k in glossary_keys, "found_by": "definition"})
            item["chapter"] = ch["id"]
            global_terms[k] = item


def build_inventory(ws: Workspace) -> dict:
    outline = ws.outline
    figures = read_json(ws.source_dir / "figures.json", [])
    _KEEP_CASE[0] = (ws.config.get("book", {}).get("language") or "en").lower().startswith(("de", "lb"))
    global_terms: dict[str, dict] = {}
    summary = {}
    invs = {}
    for ch in outline["chapters"]:
        inv = chapter_inventory(ws, ch, figures, global_terms)
        invs[ch["id"]] = inv
    # cross-chapter links: later chapters that use terms defined earlier, plus explicit "Chapter N" references
    order = [c["id"] for c in outline["chapters"]]
    term_home = {key_of(it["text"]): it["chapter"] for it in global_terms.values()}
    links: dict[str, Counter] = {cid: Counter() for cid in order}
    for ch in outline["chapters"]:
        text = " ".join(p["text"] for sec in ch["sections"] if sec["kind"] == "content"
                        for _, p in section_paragraphs(ws, sec)).casefold()
        tkey = key_of(text)
        for k, home in term_home.items():
            if home != ch["id"] and order.index(home) < order.index(ch["id"]) and len(k) >= 4 and k in tkey:
                links[ch["id"]][home] += 1
        for m in XREF.finditer(text):
            target = f"ch{int(m.group(1)):02d}"
            if target in links and target != ch["id"]:
                links[ch["id"]][target] += 3
    for cid, inv in invs.items():
        inv["depends_on"] = [{"chapter": k, "weight": v} for k, v in links[cid].most_common() if v >= 2]
        write_json(ws.inventory_path(cid), inv)
        counts = Counter(it["kind"] for it in inv["items"])
        summary[cid] = dict(counts)
    ws.state.setdefault("stages", {})["inventory"] = {"done": True, "summary": summary}
    ws.save_state()
    return summary


def items_for_section(inv: dict, sec_id: str, kinds: tuple[str, ...] | None = None) -> list[dict]:
    return [it for it in inv["items"] if it.get("section") == sec_id and (kinds is None or it["kind"] in kinds)]


def find_item(ws: Workspace, item_id: str) -> dict | None:
    return ws.all_inventory_items().get(item_id)
