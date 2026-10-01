"""Check that quoted evidence really appears in the book, on the cited page.

Every citation is [p.N: "exact words"]. The words are compared with the
extracted page text using a normalized key (see common.build_key) that
ignores case, spacing, punctuation, ligatures and line-break hyphens but keeps
letters, digits, decimal points, minus signs and relation symbols. A quote that
is on another page is reported with the right page; a quote that is almost right
is shown next to the closest real text so the writer can copy it exactly.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from .common import Workspace, build_key, key_of, number_groups, numbers_in, word_count

REF_PATTERNS = re.compile(
    r"\b(?:fig(?:ure)?s?\.?|tables?|eqs?\.?|equations?|examples?|sections?|chapters?|ch\.|steps?|parts?|"
    r"problems?|exercises?|questions?|units?|lessons?|appendix|pages?|p\.|pp\.)\s*\(?[\dA-Z]+(?:[.\-]\d+)*[a-z]?\)?",
    re.I)
EQ_REF = re.compile(r"\(\d+(?:\.\d+)+[a-z]?\)")
ID_REF = re.compile(r"\b(?:T|EQ|WE|FIG|TAB|LO|SUM|Q|CMP|PR|TL|CAUSE|RU|TR|OUT)-[\w.\-]*\w")


@dataclass
class QuoteCheck:
    status: str                     # exact | approx | wrong-page | not-found | bad-page | too-short
    page: str
    quote: str
    score: float = 0.0
    found_pages: list[str] = field(default_factory=list)
    closest: str = ""
    context: str = ""
    page_index: int | None = None
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("exact", "approx")


_FULL_KEYS: dict[str, tuple[str, list[int]]] = {}


def _full_key(text: str) -> tuple[str, list[int]]:
    """build_key with a per-process cache: one `check` builds many QuoteIndex objects over the same pages.
    (The index list is shared; callers only read it.)"""
    hit = _FULL_KEYS.get(text)
    if hit is None:
        if len(_FULL_KEYS) > 2000:
            _FULL_KEYS.clear()
        hit = _FULL_KEYS[text] = build_key(text)
    return hit


class QuoteIndex:
    """Normalized keys for the pages of the book.

    Fast keys (key_of) are computed for any page that is searched; the slower key-with-positions
    (build_key) only for the one page where a quote was found and its context is needed.
    """

    def __init__(self, ws: Workspace):
        self.ws = ws
        self._fast: dict[int, str] = {}
        self._full: dict[int, tuple[str, list[int], str]] = {}
        self._body: dict[int, str] = {}

    def key(self, index: int) -> str:
        if index not in self._fast:
            self._fast[index] = key_of(self.ws.pages[index]["text"])
        return self._fast[index]

    def body_text(self, index: int) -> str:
        """The page's text without its footnotes (they come last, so this is a prefix of the page text)."""
        paras = self.ws.pages[index].get("paras") or []
        if not any(p.get("footnote") for p in paras):
            return self.ws.pages[index]["text"]
        return "\n\n".join(p["text"] for p in paras if not p.get("in_figure") and not p.get("footnote"))

    def body_key(self, index: int) -> str:
        if index not in self._body:
            self._body[index] = key_of(self.body_text(index))
        return self._body[index]

    def _joined(self, span_idx: list[int], last: int, body: bool) -> tuple[str, list[tuple[int, int]]]:
        joined_key, bounds = "", []           # bounds: (page_index, start offset in joined_key)
        for i in span_idx:
            k = self.body_key(i) if body and i != span_idx[-1] else self.key(i)
            if i == last + 1:
                k = k[:400]
            bounds.append((i, len(joined_key)))
            joined_key += k
        return joined_key, bounds

    def page_key(self, index: int) -> tuple[str, list[int], str]:
        if index not in self._full:
            text = self.ws.pages[index]["text"]
            key, idx = _full_key(text)
            self._full[index] = (key, idx, text)
            self._fast[index] = key
        return self._full[index]

    def _text_offset(self, page_index: int, key_pos: int) -> int:
        _, idx, _ = self.page_key(page_index)
        return idx[min(max(0, key_pos), len(idx) - 1)] if idx else 0

    # ---------------------------------------------------------------- core check
    def check(self, page_spec: str, quote: str, min_words: int = 4, max_words: int | None = None,
              approx: float = 0.94) -> QuoteCheck:
        pages = self.ws.pages_for_spec(page_spec)
        qkey = key_of(quote)
        res = QuoteCheck(status="not-found", page=page_spec, quote=quote)
        if not pages:
            res.status = "bad-page"
            hits = self.find_exact(qkey)
            res.found_pages = hits
            res.note = f"there is no page labeled '{page_spec}' in this book"
            return res
        if len(qkey) < 12 or word_count(quote) < min_words:
            res.status = "too-short"
            res.note = f"quotes need at least {min_words} words so they identify one place in the book"
            return res
        # search the cited pages (plus a spill-over into the next page for quotes that cross a page break)
        first = pages[0]["index"]
        last = pages[-1]["index"]
        span_idx = list(range(first, last + 1))
        if last + 1 < len(self.ws.pages):
            span_idx.append(last + 1)
        joined_key, bounds = self._joined(span_idx, last, body=False)
        pos = joined_key.find(qkey)
        if pos < 0 and len(span_idx) > 1:
            # a sentence running on to the next page has the page's footnotes between its two halves
            joined_key, bounds = self._joined(span_idx, last, body=True)
            pos = joined_key.find(qkey)

        def owner(p: int) -> tuple[int, int]:
            page, start = bounds[0]
            for b_page, b_start in bounds:
                if b_start <= p:
                    page, start = b_page, b_start
            return page, p - start
        if pos >= 0 and owner(pos)[0] in range(first, last + 1):
            p0, k0 = owner(pos)
            p1, k1 = owner(pos + len(qkey) - 1)
            res.status = "exact"
            res.score = 1.0
            res.page_index = p0
            if p1 != p0:
                res.note = "the quote continues onto the next page"
            a = self._text_offset(p0, k0)
            end = (p0, self._text_offset(p0, k1)) if p1 == p0 else (p1, 0)
            res.context = self._context(p0, a, end) if p1 == p0 else self._context_across(p0, a, p1)
            return res
        # elsewhere in the book?
        hits = self.find_exact(qkey)
        if hits:
            res.status = "wrong-page"
            res.found_pages = hits
            return res
        # fuzzy on the cited page(s)
        best = (0.0, 0, 0, first)
        for i in range(first, last + 1):
            score, s, e = _best_window(self.key(i), qkey)
            if score > best[0]:
                best = (score, s, e, i)
        score, s, e, i = best
        res.score = round(score, 3)
        if score > 0:
            k, idx, text = self.page_key(i)
            if idx:
                a = idx[min(s, len(idx) - 1)]
                b = idx[min(max(e - 1, s), len(idx) - 1)]
                res.closest = _clip_words(text, a, b + 1)
                res.page_index = i
                res.context = self._context(i, a, (i, b))
        if score >= approx:
            res.status = "approx"
            res.note = "nearly exact; copy the words exactly to remove this warning"
        return res

    def find_exact(self, qkey: str, limit: int = 3) -> list[str]:
        if len(qkey) < 12:
            return []
        hits = []
        for p in self.ws.pages:
            if qkey in self.key(p["index"]):
                hits.append(p["label"])
                if len(hits) >= limit:
                    break
        return hits

    def search(self, text: str, limit: int = 5, chapter_pages: set[int] | None = None) -> list[tuple[str, float, str]]:
        """Best pages for a phrase (for the `find` command)."""
        qkey = key_of(text)
        out = []
        if not qkey:
            return out
        for p in self.ws.pages:
            if chapter_pages is not None and p["index"] not in chapter_pages:
                continue
            k = self.key(p["index"])
            pos = k.find(qkey)
            if pos >= 0:
                _, idx, ptext = self.page_key(p["index"])
                a = idx[pos]
                b = idx[min(len(idx) - 1, pos + len(qkey) - 1)]
                out.append((p["label"], 1.0, _clip_words(ptext, max(0, a - 80), min(len(ptext), b + 120))))
            elif len(qkey) >= 12:
                score, s, e = _best_window(k, qkey)
                if score >= 0.75:
                    _, idx, ptext = self.page_key(p["index"])
                    if idx:
                        a = idx[min(s, len(idx) - 1)]
                        b = idx[min(max(e - 1, s), len(idx) - 1)]
                        out.append((p["label"], score, _clip_words(ptext, a, b + 1)))
        out.sort(key=lambda r: -r[1])
        return out[:limit]

    def _context(self, page_index: int, a: int, end: tuple[int, int] | int) -> str:
        """The paragraph around a match, plus a short neighbouring paragraph on each side (an equation line
        or a one-line lead-in often completes the meaning), capped at ~1000 characters."""
        text = self.page_key(page_index)[2]
        b = end[1] if isinstance(end, tuple) and end[0] == page_index else (end if isinstance(end, int) else len(text))
        body_end = len(self.body_text(page_index))
        if a < body_end:                     # a quote from the text: its context stops before the footnotes
            text = text[:body_end]
            b = min(b, body_end)
        start = text.rfind("\n\n", 0, a)
        start = 0 if start < 0 else start + 2
        stop = text.find("\n\n", b)
        stop = len(text) if stop < 0 else stop
        prev_start = text.rfind("\n\n", 0, max(0, start - 2))
        prev_start = 0 if prev_start < 0 else prev_start + 2
        if start > 0 and start - prev_start < 160:
            start = prev_start
        nxt_stop = text.find("\n\n", stop + 2)
        nxt_stop = len(text) if nxt_stop < 0 else nxt_stop
        if stop < len(text) and nxt_stop - stop < 160:
            stop = nxt_stop
        if stop - start > 1000:
            start = max(start, a - 450)
            stop = min(stop, b + 450)
        out = _clip_words(text, start, stop).replace("\n\n", " ¶ ")
        # the page's text stops in mid-sentence: the sentence (often a list the claim relies on) goes on overleaf
        if stop >= len(text) and a < body_end and page_index + 1 < len(self.ws.pages) and \
                not re.search(r"[.!?。！？:：\"”」』)）]\s*$", text):
            nxt = self.ws.pages[page_index + 1]["text"]
            cut = nxt.find("\n\n")
            cut = len(nxt) if cut < 0 else cut
            if cut:
                out += f" … [p.{self.ws.pages[page_index + 1]['label']}] " + _clip_words(nxt, 0, min(cut, 300))
        return out

    def _context_across(self, p0: int, a: int, p1: int) -> str:
        """Context of a quote that runs on to the next page: its paragraph up to the end of the page's text (not
        the footnotes below it), then the start of the next page."""
        text = self.body_text(p0)
        start = text.rfind("\n\n", 0, a)
        start = 0 if start < 0 else start + 2
        start = max(start, a - 450)
        nxt = self.ws.pages[p1]["text"]
        stop = nxt.find("\n\n")
        stop = len(nxt) if stop < 0 else stop
        return (_clip_words(text, start, len(text)).replace("\n\n", " ¶ ") + f" … [p.{self.ws.pages[p1]['label']}] " +
                _clip_words(nxt, 0, min(stop, 450)).replace("\n\n", " ¶ "))


def _clip_words(text: str, a: int, b: int) -> str:
    a = max(0, a)
    b = min(len(text), b)
    while a > 0 and not text[a - 1].isspace():
        a -= 1
    while b < len(text) and not text[b].isspace():
        b += 1
    return re.sub(r"[ \t]+", " ", text[a:b]).strip()


def _best_window(page_key: str, qkey: str) -> tuple[float, int, int]:
    n, m = len(page_key), len(qkey)
    if n == 0 or m == 0:
        return 0.0, 0, 0
    if n <= m:
        return difflib.SequenceMatcher(None, page_key, qkey, autojunk=False).ratio(), 0, n
    grams = {qkey[i:i + 4] for i in range(max(1, m - 3))}
    step = max(1, m // 8)
    scored = []
    for s in range(0, n - m + step, step):
        w = page_key[s:s + m]
        hit = sum(1 for i in range(0, max(1, len(w) - 3), 2) if w[i:i + 4] in grams)
        scored.append((hit, s))
    scored.sort(reverse=True)
    best = (0.0, 0, 0)
    for _, s in scored[:6]:
        for delta in (-step, 0, step):
            a = max(0, s + delta)
            for size in (int(m * 0.9), m, int(m * 1.1)):
                b = min(n, a + size)
                r = difflib.SequenceMatcher(None, page_key[a:b], qkey, autojunk=False).ratio()
                if r > best[0]:
                    best = (r, a, b)
    return best


def claim_numbers(claim: str) -> list[list[str]]:
    """Numbers stated in a claim, each with its possible readings (a decimal comma makes '4,184' either 4184 or
    4.184), ignoring references like 'Figure 2.1', '(2.3)', 'Chapter 4' and IDs."""
    t = ID_REF.sub(" ", claim)
    t = REF_PATTERNS.sub(" ", t)
    t = EQ_REF.sub(" ", t)
    t = re.sub(r"[_^]\{?\w+\}?", " ", t)       # sub/superscript markers such as q_p, 10^3
    t = re.sub(r"\b\d+(?:st|nd|rd|th)\b", " ", t)
    return number_groups(t)


def unsupported_numbers(groups: list[list[str]], allowed: set[str]) -> list[str]:
    """Numbers none of whose readings is allowed (shown in their first reading)."""
    return [g[0] for g in groups if not any(n in allowed or n.lstrip("-") in allowed for n in g)]


def page_numbers(ws: Workspace, labels: list[str]) -> set[str]:
    nums: set[str] = set()
    for lab in labels:
        for p in ws.pages_for_spec(lab):
            nums.update(numbers_in(p["text"]))
            nums.update(n.lstrip("-") for n in numbers_in(p["text"]))
    return nums
