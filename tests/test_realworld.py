"""Regressions found on real books from the internet (a 1914 English scan, a scanned Chinese textbook, a Japanese
ministry textbook, a Chinese machine-learning book, a German civics booklet, a Spanish chemistry book).

Each test rebuilds the smallest input that showed the problem.
"""
import json
import os
import shutil
import tempfile
import time
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (sets sys.path)

import pymupdf

from examscribe_lib import ingest as I
from examscribe_lib import lang as L
from examscribe_lib import ocr as O
from examscribe_lib.common import split_sentences
from examscribe_lib.inventory import COPULA_PATTERNS, _term_ok


def para(text, size=10.0, heading=False, y=100.0):
    return {"text": text, "size": size, "heading": heading, "y0": y, "y1": y + size, "x0": 72.0, "x1": 500.0,
            "bold": [], "italic": [], "box": -1, "caption": False, "math": False}


BODY = "This is ordinary body text of the book, long enough to set the size of the running text. " * 3


def line(text, size, y, x0=72.0, x1=None, bold=False):
    x1 = x1 if x1 is not None else x0 + 5.0 * len(text)
    return {"x0": x0, "x1": x1, "y0": y, "y1": y + size, "size": size, "text": text,
            "bold": [[0, len(text)]] if bold else [], "italic": []}


class OutlineTests(unittest.TestCase):
    def test_chapter_stops_at_unread_scanned_pages(self):
        # a scan read with OCR only for chapter 1: chapter 1 must not run on to the end of the book
        pages = [[] for _ in range(10)]
        pages[2] = [para("Chapter 1 Energy", 20, True, 60), para("1.1 What Is Energy", 14, True, 120),
                    para(BODY, y=150)]
        pages[3] = [para("1.2 Units", 14, True, 60), para(BODY, y=100)]
        labels = [str(i + 1) for i in range(10)]
        outline = I.build_outline([], pages, labels, 10, None, unread=set(range(4, 10)))
        ch = outline["chapters"][0]
        self.assertEqual((ch["start"]["page"], ch["end"]["page"]), (2, 3))
        self.assertEqual(max(s["end"]["page"] for s in ch["sections"]), 3)
        unread = [o for o in outline["other"] if o.get("unread")]
        self.assertEqual(len(unread), 1)
        self.assertEqual((unread[0]["start"]["page"], unread[0]["end"]["page"]), (4, 9))
        # without unread pages (a text PDF) nothing changes
        outline = I.build_outline([], pages, labels, 10, None)
        self.assertEqual(outline["chapters"][0]["end"]["page"], 9)

    def test_ocr_misread_roman_chapter_numbers_and_caps_titles(self):
        # "CHAPTER 11" / "CHAPTER 111" are OCR's reading of II / III; the title under the label is plain capitals
        heads = [("CHAPTER 1", "THE SUBJECT MATTER OF CHEMISTRY"), ("CHAPTER 11", "DECOMPOSITION AND COMBINATION"),
                 ("CHAPTER 111", "ELEMENTS"), ("CHAPTER 1V", "COMPOUNDS")]
        pages = [[para(label, 10, True, 110), para(title, 10, False, 130), para(BODY, y=160)] for label, title in heads]
        outline = I.build_outline([], pages, [str(i + 1) for i in range(4)], 4)
        self.assertEqual([(c["id"], c["title"]) for c in outline["chapters"]],
                         [("ch01", "THE SUBJECT MATTER OF CHEMISTRY"), ("ch02", "DECOMPOSITION AND COMBINATION"),
                          ("ch03", "ELEMENTS"), ("ch04", "COMPOUNDS")])
        # a real chapter 11 after chapter 10 stays chapter 11
        entries = [{"level": 1, "title": f"Chapter {n} T{n}", "page": n} for n in (9, 10, 11)]
        I._fix_misread_numerals(entries)
        self.assertEqual(entries[-1]["title"], "Chapter 11 T11")
        self.assertIsNone(I.CHAPTER_LABEL.match("Lesson 1C"))       # language-course numbering is left alone
        self.assertTrue(I.CHAPTER_LABEL.match("CHAPTER V1"))
        self.assertEqual(I._roman_value("XIV"), "14")
        self.assertEqual(I._roman_value("12"), "12")

    def test_ocr_misread_cjk_chapter_number(self):
        # 第二章 in big display type read as 第一章: a new title with the previous number is the next chapter
        pages = [[para("细胞的结构与功能 第一章", 60, True, 80), para("正文" * 60, 11, y=200)],
                 [para("第一节 从显微镜看细胞的组成", 16, True, 80), para("正文" * 60, 11, y=200)],
                 [para("遗传与变异 第一章", 60, True, 80), para("正文" * 60, 11, y=200)]]
        outline = I.build_outline([], pages, ["1", "2", "3"], 3)
        self.assertEqual([(c["id"], c["title"]) for c in outline["chapters"]],
                         [("ch01", "细胞的结构与功能"), ("ch02", "遗传与变异")])
        # the same title again (a running head in big type) is still dropped
        pages[2] = [para("细胞的结构与功能 第一章", 60, True, 80), para("正文" * 60, 11, y=200)]
        outline = I.build_outline([], pages, ["1", "2", "3"], 3)
        self.assertEqual([c["id"] for c in outline["chapters"]], ["ch01"])

    def test_front_matter_sections_and_book_introduction(self):
        ch = {"id": "ch01", "number": "1", "title": "Demokratie", "start": {"page": 0, "y": 0},
              "end": {"page": 5, "y": 1e9}}
        pages = [[para("Inhalt", 14, True, 60), para(BODY, y=100)], [para("Editorial", 14, True, 60)],
                 [para("1.1 Athen", 14, True, 60)], [para("Literaturhinweise", 14, True, 60)], [], []]
        subs = [{"level": 2, "title": t, "page": p} for p, t in ((0, "Inhalt"), (1, "Editorial"), (2, "1.1 Athen"),
                                                                (3, "Literaturhinweise"))]
        kinds = [(s["title"], s["kind"]) for s in I._sections_for(ch, subs, pages, "de")]
        self.assertEqual(kinds, [("Inhalt", "other"), ("Editorial", "other"), ("Athen", "content"),
                                 ("Literaturhinweise", "end")])
        # the book's own "Introducción" starts the chapter; no second, automatic introduction is added
        ch_es = dict(ch, start={"page": 0, "y": 0})
        pages_es = [[para("CAPÍTULO 1 Ideas esenciales", 20, True, 40), para(BODY * 2, y=100),
                     para("Introducción", 14, True, 600)], [para("1.1 La química", 14, True, 60)], [], [], [], []]
        subs_es = [{"level": 2, "title": "Introducción", "page": 0}, {"level": 2, "title": "1.1 La química", "page": 1}]
        secs = I._sections_for(ch_es, subs_es, pages_es, "es")
        self.assertEqual([s["title"] for s in secs], ["Introducción", "La química"])
        self.assertEqual(secs[0]["start"], {"page": 0, "y": 0})
        # an automatic introduction is named in the book's language
        subs_zh = [{"level": 2, "title": "1.1 La química", "page": 1}]
        secs = I._sections_for(ch_es, subs_zh, pages_es, "zh")
        self.assertEqual(secs[0]["title"], "引言")

    def test_other_titles_whole_word_only(self):
        for t in ("Soluciones", "Lösungen", "Respuestas", "Inhalt", "Editorial", "Clave de respuestas", "Blank Page"):
            self.assertTrue(I.OTHER_TITLES.match(t), t)
        for t in ("Soluciones y coloides", "Lösungen und Gemische", "Solutions and Colloids", "Thermochemistry"):
            self.assertFalse(I.OTHER_TITLES.match(t), t)


class LineTests(unittest.TestCase):
    def test_wrapped_latin_heading(self):
        pe = I.PageExtract(0, 390, 562)
        pe.lines = [line("ELEMENTARY HOUSEHOLD", 17, 107.6, 80, 310), line("CHEMISTRY", 16, 135.3, 150, 240),
                    line("CHAPTER 1", 10, 177.4, 170, 220, bold=True)] + \
                   [line("Chemistry is a science. The word science is derived from a Latin word here.", 10,
                         200 + 12 * k, 55, 335) for k in range(8)]
        paras = I._build_paragraphs(pe, set(), Counter(), 10)
        self.assertEqual(paras[0]["text"], "ELEMENTARY HOUSEHOLD CHEMISTRY")
        self.assertEqual(paras[1]["text"], "CHAPTER 1")
        # a chapter title and the section heading under it stay apart; so do a title and "Learning Objectives"
        for second in ("1.1 What Is Energy?", "Learning Objectives"):
            pe.lines = [line("Energy and Its Units", 18, 100, 72, 300, True), line(second, 17, 125, 72, 280, True)]
            paras = I._build_paragraphs(pe, set(), Counter(), 10)
            self.assertEqual(len(paras), 2, second)

    def test_scan_running_heads_and_page_numbers(self):
        # scans keep the paper margins: the running head sits at ~9-11% of the page height, number and title in
        # one line; it is furniture, and its number gives the printed page labels
        pages = []
        for i in range(8):
            pe = I.PageExtract(i, 390, 562)
            n = i + 5
            head = f"{n} ELEMENTARY HOUSEHOLD CHEMISTRY" if n % 2 == 0 else f"THE SUBJECT MATTER OF CHEMISTRY {n}"
            pe.lines = [line(head, 10, 50, 80, 330)] + [line(f"Body text line {k} of page {n}, plain words.", 10,
                                                             75 + 14 * k, 55, 335) for k in range(20)]
            pages.append(pe)
        opening = I.PageExtract(8, 390, 562)                      # a chapter's first page: its label stays
        opening.lines = [line("CHAPTER 2", 10, 50, 170, 220)] + [line("More body text here.", 10, 75, 55, 335)]
        opening2 = I.PageExtract(9, 390, 562)
        opening2.lines = [line("CHAPTER 3", 10, 50, 170, 220)] + [line("More body text here.", 10, 75, 55, 335)]
        pages += [opening, opening2]
        marked = I._furniture_keys(pages)
        self.assertTrue(all((i, 0) in marked for i in range(8)), sorted(marked))
        self.assertNotIn((8, 0), marked)
        self.assertNotIn((9, 0), marked)
        furn = {}
        for pidx, i in marked:
            furn.setdefault(pidx, []).append(pages[pidx].lines[i]["text"])
        labels, method = I._assign_labels(pages, furn)
        self.assertEqual(method, "printed-page-numbers")
        self.assertEqual(labels[:3], ["5", "6", "7"])

    def test_bold_faces(self):
        # Japanese ministry textbook: all body text in "KozMinPro-Bold" -> nothing is emphasis there
        body = "KozMinPro-Bold"
        self.assertFalse(I._is_bold({"font": body, "flags": 20, "char_flags": 24, "text": "情報"}, body))
        self.assertTrue(I._is_bold({"font": "KozGoPr6N-Bold", "flags": 20, "char_flags": 24, "text": "情報"}, body))
        self.assertTrue(I._is_bold({"font": body, "flags": 20, "char_flags": 48 | 8, "text": "情報"}, body))
        # a regular body face made bold by the PDF writer (same name, bold flag) still counts
        self.assertTrue(I._is_bold({"font": "CharisSIL", "flags": 16, "char_flags": 24, "text": "Калория"},
                                   "CharisSIL"))
        self.assertFalse(I._is_bold({"font": "CharisSIL", "flags": 4, "char_flags": 16, "text": "text"}, "CharisSIL"))

    def test_body_font_of_a_short_book(self):
        doc = pymupdf.open()
        p = doc.new_page()
        p.insert_htmlbox(pymupdf.Rect(72, 72, 540, 300), "<h1><b>A Very Long Title Page Heading Here</b></h1>")
        for _ in range(2):
            p = doc.new_page()
            p.insert_htmlbox(pymupdf.Rect(72, 72, 540, 720),
                             "<p>" + "Plain running text of the chapter with a <b>term</b> inside it. " * 30 + "</p>")
        font = I._body_font(doc)
        self.assertNotIn("bold", font.lower())

    def test_garble_ratio_ignores_math_glyphs(self):
        self.assertEqual(I.garble_ratio("• �: 连加  • �: 连乘"), 0.0)          # lone unmapped symbols
        self.assertEqual(I.garble_ratio("  x_1   x_2  "), 0.0)   # bracket pieces
        self.assertGreater(I.garble_ratio("Th� qu�ck br�wn fox jumps"), 0.01)
        self.assertGreater(I.garble_ratio("传�学的对象和�本问题"), 0.01)

    def test_soft_hyphens_and_equation_numbers(self):
        self.assertEqual(I._dehyphen_join("die Po­", "litisierung der Frage", Counter()),
                         "die Politisierung der Frage")
        ln = {"x0": 0, "x1": 200, "y0": 0, "y1": 10, "size": 10,
              "spans": [{"text": "Bundes­tag und Po­", "bbox": (0, 0, 200, 10), "size": 10, "font": "F",
                         "flags": 0}]}
        self.assertEqual(I._line_text(ln)["text"], "Bundestag und Po­")
        self.assertIsNone(I.EQ_NUM_RE.search("Jean-Jacques Rousseau (1712-1778)"))
        self.assertEqual(I.EQ_NUM_RE.search("q = m c ΔT (5.12)").group(1), "5.12")

    def test_no_subscript_marks_on_cjk_labels(self):
        ln = {"x0": 0, "x1": 300, "y0": 0, "y1": 12, "size": 10,
              "spans": [{"text": "要素を確保する", "bbox": (0, 0, 100, 12), "size": 10, "font": "F", "flags": 0},
                        {"text": "許可", "bbox": (110, 6, 130, 13), "size": 7, "font": "F", "flags": 0}]}
        self.assertNotIn("_{", I._line_text(ln)["text"])


class TextTests(unittest.TestCase):
    def test_german_ordinals_do_not_end_sentences(self):
        s = split_sentences("Gegen Ende des 19. Jahrhunderts wuchs die Stadt. Am 3. Oktober 1990 kam die Einheit. "
                            "Das waren 12. Danach kam mehr.")
        self.assertEqual(s[0], "Gegen Ende des 19. Jahrhunderts wuchs die Stadt.")
        self.assertEqual(s[1], "Am 3. Oktober 1990 kam die Einheit.")
        self.assertEqual(s[2], "Das waren 12.")

    def test_cjk_and_symbol_terms(self):
        for bad in ("必要とする状況」など", "指定した言語で作成する」", "持つ", "ダウンロードに際して", "可視化させる",
                    "ただし，問題解決", "完全性 可用性", "x和y", "x, y", "_x", "a b c"):
            self.assertFalse(_term_ok(bad), bad)
        for good in ("電子マネー", "データマイニング", "情報", "力", "传播", "Kinetic energy", "C++", "TCP/IP", "pH",
                     "Vitamin C"):
            self.assertTrue(_term_ok(good), good)

    def test_chinese_even_if_is_no_definition(self):
        def terms(s):
            for pat in COPULA_PATTERNS:
                m = pat.match(s)
                if m:
                    return m.group("t")
            return None
        self.assertIsNone(terms("在这些情况下，即使是顶级程序员也无法提出完美的解决方案。"))
        self.assertIsNone(terms("换句话说，即使我们不知道如何编写计算机程序来识别这个词。"))
        self.assertEqual(terms("所谓光合作用，即绿色植物利用光能把二氧化碳和水合成有机物的过程。"), "光合作用")

    def test_chinese_jiushi_and_ji(self):
        from examscribe_lib.inventory import _CJK_NOT_DEFINED

        def term(s):                     # the patterns plus the filters the inventory applies to their matches
            for pat in COPULA_PATTERNS:
                m = pat.match(s)
                if m:
                    t = m.group("t")
                    return None if _CJK_NOT_DEFINED.search(t) or not _term_ok(t) else t
        self.assertIsNone(term("一座城市本身就是一台精密的机器，规划师常这样比喻。"))   # "X就是Y": speech
        self.assertEqual(term("蒸腾作用即植物体内的水分以水蒸气状态散失到大气中的过程。"), "蒸腾作用")
        self.assertEqual(term("所谓食物链，就是生物之间由于吃与被吃的关系而形成的联系。"), "食物链")

    def test_items_on_a_page_split_between_parts(self):
        from examscribe_lib.skeleton import _items_in_part
        pg = lambda lab: {"label": lab}
        p1 = {"section": "1.2", "part": 1, "pairs": [(pg("7"), {"text": "森林里的树木、动物和微生物彼此依存。"}),
                                                     (pg("8"), {"text": "湖泊、沼泽和河口地带合称湿地，生态学家称之为湿地生态系统。"})]}
        p2 = {"section": "1.2", "part": 2, "pairs": [(pg("8"), {"text": "物质循环决定了一个生态系统能否长期保持稳定。"}),
                                                     (pg("9"), {"text": "农业生产离不开土壤和水源的持续供给。"})]}
        p1["siblings"] = p2["siblings"] = [p1, p2]
        items = [{"id": "T-湿地生态系统", "kind": "term", "section": "1.2", "page": "8",
                  "context": "湖泊、沼泽和河口地带合称湿地，生态学家称之为湿地生态系统。"},
                 {"id": "T-物质循环", "kind": "term", "section": "1.2", "page": "8",
                  "context": "物质循环决定了一个生态系统能否长期保持稳定。"},
                 {"id": "FIG-1", "kind": "figure", "section": "1.2", "page": "8", "caption": "图1 不在正文里"}]
        inv = {"items": items}
        self.assertEqual([it["id"] for it in _items_in_part(inv, p1)], ["T-湿地生态系统", "FIG-1"])   # unknown: first part
        self.assertEqual([it["id"] for it in _items_in_part(inv, p2)], ["T-物质循环"])

    def test_language_words(self):
        self.assertTrue(L.is_introduction("Introducción"))
        self.assertTrue(L.is_introduction("引言"))
        self.assertFalse(L.is_introduction("Introductory Chemistry Problems"))
        self.assertEqual(L.introduction("de"), "Einleitung")
        self.assertTrue(I.CAPTION_RE.match("図表1　情報の成り立ち"))


class ScanOutlineTests(unittest.TestCase):
    def test_chapter_page_with_sections_is_not_a_contents_page(self):
        # "Chapitre 1", "1.1 ...", "Figure 1.1 ...", "1.2 ..." on one page: a chapter start, not a table of contents
        page = [para("Chapitre 1", 12, True, 60), para("L'énergie et ses unités", 22, True, 85), para(BODY, 12, y=120),
                para("1.1 Qu'est-ce que l'énergie ?", 15, True, 165), para(BODY, 12, y=190),
                para("Figure 1.1 Schéma de la conversion", 12, False, 430), para("1.2 Les unités", 15, True, 458),
                para(BODY, 12, y=483)]
        toc = [para("Table des matières", 16, True, 40)] + \
              [para(f"{c}.{s} Section {c}.{s} ........ {c * 10 + s}", 12, False, 80 + 20 * (c * 3 + s))
               for c in (1, 2) for s in (1, 2, 3)]
        outline = I.build_outline([], [toc, page], ["i", "1"], 2)
        self.assertEqual([c["title"] for c in outline["chapters"]], ["L'énergie et ses unités"])
        self.assertEqual([s["id"] for s in outline["chapters"][0]["sections"]][-2:], ["1.1", "1.2"])

    def test_lost_or_noisy_titles_under_a_chapter_label(self):
        # OCR lost the big title ("Глава 1" alone opens the page) or read specks as a title ("a e", "2 e")
        pages = [[para("Глава 1", 11, True, 64), para("a e", 18, True, 84), para(BODY, 11, y=119),
                  para("1.1 Что такое энергия", 14, True, 182), para(BODY, 11, y=207)],
                 [para("Глава 2", 11, True, 64), para(BODY, 11, y=119), para("2.1 Теплота", 14, True, 182),
                  para(BODY, 11, y=207)],
                 [para("Capítulo 3", 12, True, 63), para("La energía", 29, True, 79), para("2 e", 18.5, True, 84),
                  para(BODY, 12, y=119), para("3.1 Calor", 15, True, 165), para(BODY, 12, y=190)]]
        outline = I.build_outline([], pages, ["1", "2", "3"], 3)
        self.assertEqual([(c["id"], c["title"]) for c in outline["chapters"]],
                         [("ch01", "Глава 1"), ("ch02", "Глава 2"), ("ch03", "La energía")])
        # a capitals title under "CHAPTER VII" with a letter OCR read as small, in the body size
        pages = [[para("CHAPTER VI", 10, True, 60), para("THE ATOMIC THEORY", 10, False, 80), para(BODY, 10, y=110)],
                 [para("CHAPTER VII", 10, True, 60), para("THE LAW OF DEFm1TE PROPORTIONS", 10, False, 80),
                  para(BODY, 10, y=110)]]
        outline = I.build_outline([], pages, ["32", "40"], 2)
        self.assertEqual([c["title"] for c in outline["chapters"]],
                         ["THE ATOMIC THEORY", "THE LAW OF DEFm1TE PROPORTIONS"])
        # a small "Chapter 3" inside a page is a cross-reference, not a chapter
        pages = [[para("Chapter 1 Energy", 20, True, 40), para(BODY, y=100), para("Chapter 3", 10, True, 300),
                  para(BODY, y=320)]]
        self.assertEqual(len(I.build_outline([], pages, ["1"], 1)["chapters"]), 1)

    def test_mis_encoded_text_layer_is_garbled(self):
        mojibake = "ÄÜÁ¿ÊÇ×ö¹¦»òÌá¹©ÈÈÁ¿µÄÄÜÁ¦¡£ ¶¯ÄÜÊÇÎïÌåÓÉÓÚÔË¶¯¶ø¾ßÓÐµÄÄÜÁ¿¡£ ÈÈÊÇÔÚ²»Í¬ÎÂ¶ÈµÄÎïÌåÖ®¼ä´«µÝµÄÈÈÄÜ"
        self.assertGreater(I.garble_ratio(mojibake), 0.01)
        cyr = "Ýíåðãèÿ — ýòî ñïîñîáíîñòü ñîâåðøàòü ðàáîòó èëè ïåðåäàâàòü òåïëîòó."
        self.assertGreater(I.garble_ratio(cyr), 0.01)
        for fine in ("L'énergie cinétique est l'énergie que possède un corps du fait de son mouvement à grande vitesse.",
                     "Die Wärmekapazität ist die Wärmemenge, die nötig ist, um die Temperatur zu erhöhen, für Körper.",
                     "Él comió piña y ñandú; la canción está aquí según él, también allí ahora mismo, dijo María."):
            self.assertEqual(I.garble_ratio(fine), 0.0, fine)

    def test_defined_as_in_many_languages(self):
        def term(s):
            for pat in COPULA_PATTERNS:
                m = pat.match(s)
                if m:
                    return m.group("t")
        self.assertEqual(term("La calorie a été définie à l'origine comme la quantité de chaleur."), "calorie")
        self.assertEqual(term("Die Kalorie wurde ursprünglich als die Wärmemenge definiert, die Wasser erwärmt."),
                         "Kalorie")
        self.assertEqual(term("Калория первоначально была определена как количество теплоты."), "Калория")
        self.assertEqual(term("La caloría se definió originalmente como la cantidad de calor."), "caloría")
        self.assertEqual(term("The calorie was originally defined as the amount of energy needed."), "calorie")
        self.assertIsNone(term("Die Regierung wurde im Jahr 1990 gewählt, als die Einheit kam."))


class TesseractDataTests(unittest.TestCase):
    def test_codes_download_and_folders(self):
        self.assertEqual(O.tess_codes_for("fr"), ["fra", "eng"])
        self.assertEqual(O.tess_codes_for("zh-TW"), ["chi_tra", "eng"])
        self.assertEqual(O.tess_codes_for("en"), ["eng"])
        tmp = Path(tempfile.mkdtemp(prefix="examscribe-tessdata-"))
        try:
            class Resp:
                def __init__(self, n):
                    self.data = b"x" * n

                def read(self, k=-1):
                    out, self.data = (self.data, b"") if k < 0 else (self.data[:k], self.data[k:])
                    return out

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False
            with mock.patch.object(O, "USER_TESSDATA", tmp), \
                    mock.patch("urllib.request.urlopen", side_effect=lambda url, timeout=0: Resp(200_000)):
                self.assertEqual(O.fetch_tessdata("fr", say=lambda *_: None), ["fra", "eng"])
            self.assertTrue((tmp / "fra.traineddata").exists())
            with mock.patch.object(O, "USER_TESSDATA", tmp / "other"), \
                    mock.patch("urllib.request.urlopen", side_effect=lambda url, timeout=0: Resp(10)):
                with self.assertRaises(O.ESError):          # a truncated download is refused and removed
                    O.fetch_tessdata("fr", say=lambda *_: None)
                self.assertFalse(any((tmp / "other").glob("*.part")))
            # the book's language is found in the user folder even when a system Tesseract lacks it
            system = tmp / "system"
            system.mkdir()
            (system / "eng.traineddata").write_bytes(b"x" * 200_000)
            with mock.patch.object(O, "USER_TESSDATA", tmp), \
                    mock.patch.object(O.pymupdf, "get_tessdata", return_value=str(system)):
                row = next(r for r in O.engine_report("fr") if r["name"] == "tesseract")
                self.assertTrue(row["ok"])
                self.assertEqual((row["lang"], row["tessdata"]), ("fra+eng", str(tmp)))
                row = next(r for r in O.engine_report("ru") if r["name"] == "tesseract")
                self.assertFalse(row["ok"])
                self.assertIn("ocr-setup", row["detail"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class WeakWriterTests(unittest.TestCase):
    """What a small model did in a real run: rewrote drafts with shell commands (destroying Chinese text), deleted
    blocks to get past the skip limit, and wrote English notes for a student who asked for Chinese."""

    def setUp(self):
        self.ws = helpers.new_workspace()

    def tearDown(self):
        helpers.cleanup(self.ws)

    def test_damaged_draft_is_recognised_and_restored(self):
        from examscribe_lib.pipeline import check, compute_next, draft_damage, restore_draft
        task = compute_next(self.ws)
        self.assertEqual(task.kind, "write-section")
        original = task.edit.read_text(encoding="utf-8")
        self.assertIsNone(draft_damage(original))
        task.edit.write_text("# ???? ??\n::: concept T-energy\nterm: ????\n:::\n", encoding="utf-8")
        res = check(self.ws)
        self.assertFalse(res.ok)
        self.assertIn("looks damaged", res.text)
        self.assertIn("restore-draft", res.text)
        msg = restore_draft(self.ws)
        self.assertIn("Restored", msg)
        self.assertEqual(task.edit.read_text(encoding="utf-8"), original)
        self.assertTrue(task.edit.with_name(task.edit.name + ".bak").exists())
        for bad in ("text � more", "no blocks at all here", "ÄÜÁ¿ÊÇ×ö¹¦»òÌá¹©ÈÈÁ¿µÄÄÜÁ¦¡£" * 3 + "\n::: concept T-x\n:::"):
            self.assertIsNotNone(draft_damage(bad), bad[:20])

    def test_deleted_blocks_become_reported_skips(self):
        from examscribe_lib.pipeline import check, compute_next
        from examscribe_lib.tiers import tier_params
        task = compute_next(self.ws)
        helpers.install_draft(self.ws, task.chapter, task.edit.name)
        text = task.edit.read_text(encoding="utf-8")
        blocks = text.split("\n::: ")
        victim = next(b for b in blocks[1:] if b.startswith("concept "))
        bid = victim.split()[1]
        task.edit.write_text(text.replace("\n::: " + victim, ""), encoding="utf-8")
        for _ in range(tier_params(self.ws.tier)["max_attempts"]):
            self.assertFalse(check(self.ws).ok)
        res = check(self.ws, accept_flags=True)
        self.assertTrue(res.ok, res.text[:800])
        restored = task.edit.read_text(encoding="utf-8")
        self.assertIn(f"::: concept {bid}\nskip: deleted by the writer", restored)
        flags = self.ws.state["chapters"][task.chapter]["flags"]
        self.assertTrue(any(bid in f for f in flags.get(task.extra["part"], [])), flags)

    def test_changed_readonly_worksheet_lines_are_put_back(self):
        from examscribe_lib.pipeline import check, compute_next
        for _ in range(40):
            task = compute_next(self.ws)
            if task.kind == "verify-claims":
                break
            if task.kind in ("write-section", "write-chapter"):
                helpers.install_draft(self.ws, task.chapter, task.edit.name)
            res = check(self.ws)
            self.assertTrue(res.ok or task.kind == "notify", res.text[:500])
        self.assertEqual(task.kind, "verify-claims")
        helpers.oracle_fill(self.ws)
        lines = task.edit.read_text(encoding="utf-8").split("\n")
        i = next(k for k, l in enumerate(lines) if l.startswith("context: "))
        lines[i] = lines[i].replace('"', "“", 1) if '"' in lines[i] else lines[i] + " (edited)"   # a retyped quote
        j = next(k for k, l in enumerate(lines) if l.startswith("claim: ") and k > i)
        del lines[j]                                                                            # a lost line
        task.edit.write_text("\n".join(lines), encoding="utf-8")
        res = check(self.ws)
        self.assertIn("put back 2 read-only line(s)", res.text)
        self.assertTrue(res.ok, res.text[:800])

    def test_notes_language(self):
        from examscribe_lib.config import set_key
        from examscribe_lib.esm import parse
        from examscribe_lib.lint import lint_notes
        from examscribe_lib.pipeline import compute_next, lint_ctx
        task = compute_next(self.ws)
        self.assertIn("in English (en)", " ".join(task.rules))
        helpers.install_draft(self.ws, task.chapter, task.edit.name)
        part = task.extra["part"]
        expected = self.ws.state["chapters"][task.chapter]["expected"][part]
        doc = parse(task.edit.read_text(encoding="utf-8"), task.edit)
        self.assertTrue(lint_notes(doc, lint_ctx(self.ws, task.chapter, "section", expected)).ok)
        set_key(self.ws, "output.language", "zh")
        self.ws.reload()
        self.assertIn("Chinese (zh)", " ".join(compute_next(self.ws).rules))
        res = lint_notes(doc, lint_ctx(self.ws, task.chapter, "section", expected))
        codes = {i.code for i in res.errors}
        self.assertIn("notes-language", codes)
        self.assertTrue(all(i.code in ("notes-language", "term-original") for i in res.errors),
                        [(i.code, i.message) for i in res.errors][:5])


class PageBreakTests(unittest.TestCase):
    def test_sentence_across_a_page_with_footnotes(self):
        from examscribe_lib.citations import QuoteIndex
        from examscribe_lib.config import init_workspace
        tmp = Path(tempfile.mkdtemp(prefix="examscribe-footnote-"))
        try:
            doc = pymupdf.open()
            body = "Plain text of the book that fills the page with ordinary sentences about energy. " * 2
            p1 = doc.new_page(width=400, height=600)
            y = 60
            for _ in range(10):
                p1.insert_text((40, y), body[:70], fontsize=10)
                y += 14
            p1.insert_text((40, y), "The five types of energy are kinetic, potential,", fontsize=10)
            p1.insert_text((40, 520), "1 See Smith, Energy Basics (Boston: Lake Press, 2005), p. 12.", fontsize=7)
            p1.insert_text((40, 532), "2 Ibid., p. 14.", fontsize=7)
            p2 = doc.new_page(width=400, height=600)
            p2.insert_text((40, 60), "thermal, chemical and nuclear energy. Each type can change into another one.", fontsize=10)
            y = 74
            for _ in range(10):
                p2.insert_text((40, y), body[:70], fontsize=10)
                y += 14
            doc.save(str(tmp / "b.pdf"))
            ws = init_workspace(tmp / "ws", tmp / "b.pdf", "strict", None, "en")
            I.ingest(ws)
            ws.reload()
            notes = [q["text"] for q in ws.pages[0]["paras"] if q.get("footnote")]
            self.assertEqual(len(notes), 2, ws.pages[0]["paras"][-3:])
            qi = QuoteIndex(ws)
            r = qi.check("1", "kinetic, potential, thermal, chemical and nuclear energy")
            self.assertEqual(r.status, "exact")
            self.assertIn("[p.2] thermal, chemical", r.context)
            self.assertNotIn("Lake Press", r.context)
            r = qi.check("1", "The five types of energy are kinetic")      # on one page: the rest comes from p.2
            self.assertIn("[p.2] thermal, chemical and nuclear energy", r.context)
            self.assertNotIn("Lake Press", r.context)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ocr_running_head_variants(self):
        pages = []
        for i in range(8):
            pe = I.PageExtract(i, 400, 740)
            head = ["生态学基础", f"{i + 3} 生态学基础", f"生态学基础{i + 3}", "生态学基础"][i % 4]
            pe.lines = [line(head, 11.5, 40, 30, 120)] + \
                       [line(f"正文第{i}页第{k}行的内容，这里是很长的一句话。", 11.5, 70 + 20 * k, 40, 360) for k in range(20)]
            pages.append(pe)
        marked = I._furniture_keys(pages)
        self.assertTrue(all((i, 0) in marked for i in range(8)), sorted(marked))

    def test_overlapping_contexts_are_given_once(self):
        from examscribe_lib.verify import _add_context
        para = "湿地生态系统是一个开放的系统。它的主要功能包括涵养水源、调节气候、净化水质，并为许多迁徙的鸟类和鱼类提供栖息地与食物。"
        parts = []
        _add_context(parts, "[p.8] " + para[:50])
        _add_context(parts, "[p.8] " + para[5:])
        _add_context(parts, "[p.9] 农业生产离不开土壤和水源的持续供给。持续的干旱会给农业带来严重损失。")
        self.assertEqual(len(parts), 2)
        self.assertIn("提供栖息地与食物", parts[0])


class PageLanguageTests(unittest.TestCase):
    def tearDown(self):
        from examscribe_lib import ui
        ui.set_language("en")

    def test_table_is_complete_and_placeholders_match(self):
        import re as _re
        from examscribe_lib import ui
        for en, row in ui.TEXT.items():
            self.assertEqual(len(row), len(ui.LANGS), en)
            want = sorted(_re.findall(r"\{(\w+)\}", en))
            for lang, s in zip(ui.LANGS, row):
                self.assertEqual(sorted(_re.findall(r"\{(\w+)\}", s)), want, f"{lang}: {en}")
        for k in ui.JS_KEYS:
            self.assertIn(k, ui.TEXT)

    def test_pages_in_the_notes_language(self):
        from examscribe_lib import ui
        from examscribe_lib.esm import parse
        from examscribe_lib.render import question_html
        q = parse("::: question Q-1\ntype: tf\nbloom: remember\nask: 能量是做功的能力。\nanswer: true\n"
                  "why: 课本这样说。 [p.1: \"能量是做功或提供热量的能力\"]\n:::\n").blocks[0]
        ui.set_language("zh")
        html = question_html(q)
        self.assertIn(">对<", html)
        self.assertIn("答案：<strong>", html)                 # no space after a full-width colon
        self.assertEqual(ui.T("What is {term}?", term="能量"), "什么是能量？")
        self.assertEqual(ui.reason("2 past-paper question(s)"), "2 道历年真题")
        ui.set_language("xx")                                  # unknown language: English
        self.assertEqual(ui.T("Key term"), "Key term")
        self.assertIn(">True<", question_html(q))

    def test_flags_cards_and_exports_in_the_notes_language(self):
        from examscribe_lib import ui
        ocr = "p.1, p.2 was read by OCR: check the numbers against the printed page"
        defines = 'The book defines "传播学" as: "传播学是一门社会科学"'
        self.assertEqual(ui.flag_reason(ocr), ocr)             # English pages: stored text unchanged
        self.assertEqual(ui.claim_text(defines), defines)
        self.assertEqual(ui.answer_text("tf", "false"), "False")
        ui.set_language("zh")
        self.assertEqual(ui.flag_reason(ocr), "p.1, 2 由 OCR 识别：请对照纸质页面核对数字")
        self.assertEqual(ui.flag_reason("partial"), "只有部分有依据")
        self.assertEqual(ui.flag_reason("课本说的是另一回事"), "课本说的是另一回事")   # a checker's own words stay
        self.assertEqual(ui.claim_text(defines), "课本对“传播学”的定义：“传播学是一门社会科学”")
        self.assertEqual(ui.answer_text("tf", "false"), "错")
        self.assertEqual(ui.answer_text("short", "false"), "false")
        ui.set_language("de")
        self.assertEqual(ui.flag_reason("text extraction on p.7 may be unreliable"),
                         "Text auf S. 7 ist möglicherweise unzuverlässig erkannt")


class CoversTests(unittest.TestCase):
    def test_parts_without_terms_cover_none(self):
        from examscribe_lib.esm import parse
        from examscribe_lib.lint import LintContext, lint_notes
        from examscribe_lib.skeleton import _question_block
        from examscribe_lib.tiers import tier_params
        tier = tier_params("strict")
        self.assertIn("covers: NONE", _question_block("Q-1.3.p3-01", "tf", "remember", "Possible covers: NONE", tier))
        self.assertIn("<<FILL", _question_block("Q-1.3.p2-01", "tf", "remember", "Possible covers: T-x", tier))
        q = ("::: question Q-1.3.p3-01\ntype: tf\nbloom: remember\nask: A statement.\nanswer: true\n"
             "why: Because. [p.1: \"exact words here now\"]\ncovers: NONE\n:::\n")
        ws = mock.Mock()
        quotes = mock.Mock(check=lambda *a, **k: mock.Mock(status="exact"))     # every quote "found"
        ctx = lambda exp: LintContext(ws=ws, tier=tier, expected=exp, min_questions=0, qindex=quotes)
        codes = lambda exp: {i.code for i in lint_notes(parse(q), ctx(exp)).issues}
        self.assertNotIn("covers", codes({"Q-1.3.p3-01": "question"}))
        self.assertIn("covers", codes({"Q-1.3.p3-01": "question", "T-信息产业": "concept"}))


class PictureBookTests(unittest.TestCase):
    def test_folder_of_page_photos_becomes_a_scanned_book(self):
        import subprocess
        import sys
        from examscribe_lib.images import prepare_book
        tmp = Path(tempfile.mkdtemp(prefix="examscribe-pics-"))
        try:
            pics = tmp / "Chemistry chapter 3"
            pics.mkdir()
            for name, w in (("page1.png", 100), ("page10.jpg", 300), ("page2.png", 200)):
                pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, w), False)
                pix.clear_with(200)
                pix.save(str(pics / name))
            (pics / "notes.txt").write_text("not a page", encoding="utf-8")
            doc = pymupdf.open(prepare_book(pics, tmp / "out.pdf"))
            widths = [round(p.rect.width) for p in doc]
            self.assertEqual(len(widths), 3)
            self.assertEqual(widths, sorted(widths))           # page1, page2, page10: natural order
            cli = helpers.SKILL / "scripts" / "examscribe.py"
            r = subprocess.run([sys.executable, str(cli), "init", str(tmp / "ws"), "--book", str(pics),
                                "--language", "en"], capture_output=True, text=True, encoding="utf-8",
                               env=dict(os.environ, PYTHONUTF8="1"))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("Made one PDF from the page pictures", r.stdout)
            cfg = json.loads((tmp / "ws" / "examscribe.json").read_text(encoding="utf-8"))
            self.assertEqual(cfg["title"], "Chemistry chapter 3")
            self.assertEqual(cfg["book"]["file"], "source/book.pdf")
            djvu = tmp / "book.djvu"
            djvu.write_bytes(b"AT&TFORM")
            with self.assertRaises(I.ESError) as err:
                prepare_book(djvu, tmp / "x.pdf")
            self.assertIn("ddjvu", err.exception.hint)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class OcrSpeedTests(unittest.TestCase):
    def test_estimates_use_measured_speed(self):
        tmp = Path(tempfile.mkdtemp(prefix="examscribe-speed-"))
        try:
            machine = tmp / "ocr-speed.json"
            eng = O.Engine("rapidocr", "ch+en", 1, 200)
            with mock.patch.object(O, "MACHINE_SPEED", machine), mock.patch.object(O.os, "cpu_count", return_value=2):
                self.assertAlmostEqual(eng.estimate(10), O.STARTUP["rapidocr"] + 10 * O.SPEED["rapidocr"] * 4)
                machine.write_text(json.dumps({"rapidocr": {"sec_per_page_worker": 20.0}}), encoding="utf-8")
                self.assertAlmostEqual(eng.estimate(10), O.STARTUP["rapidocr"] + 200)
                machine.write_text("{broken", encoding="utf-8")            # a damaged file is ignored
                self.assertGreater(eng.estimate(10), 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_windows_language_list_is_cached(self):
        tmp = Path(tempfile.mkdtemp(prefix="examscribe-winlang-"))
        try:
            cache = tmp / "langs.json"
            cache.write_text(json.dumps({"time": time.time(), "tags": ["en-US", "zh-Hans-CN"]}), encoding="utf-8")
            with mock.patch.object(O, "WIN_LANGS_CACHE", cache), mock.patch.object(O, "_WIN_LANGS", None), \
                    mock.patch.object(O.subprocess, "run", side_effect=AssertionError("PowerShell was started")):
                self.assertEqual(O.windows_languages(), ["en-US", "zh-Hans-CN"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_rapidocr_found_without_import(self):
        with mock.patch("importlib.util.find_spec", return_value=None):
            self.assertFalse(O._rapidocr_installed())


class ScanWorkspaceTests(unittest.TestCase):
    def test_page_renders_only_in_scope_and_scan_intake_wording(self):
        from examscribe_lib.config import init_workspace, set_key
        from examscribe_lib.media import ensure_chapter_media
        from examscribe_lib.pipeline import _intake_task
        tmp = Path(tempfile.mkdtemp(prefix="examscribe-scanmedia-"))
        try:
            src = pymupdf.open()
            for i in range(12):
                p = src.new_page(width=300, height=400)
                p.insert_text((40, 60), f"Scanned page {i + 1}", fontsize=14)
            out = pymupdf.open()
            for p in src:
                q = out.new_page(width=300, height=400)
                q.insert_image(q.rect, pixmap=p.get_pixmap(dpi=40, colorspace=pymupdf.csGRAY))
            out.save(str(tmp / "scan.pdf"))
            ws = init_workspace(tmp / "ws", tmp / "scan.pdf", "strict", None, "en")
            I.ingest(ws)
            ws.reload()
            self.assertEqual(ws.outline["label_method"], "pdf-index")
            self.assertIn("PDF viewer page numbers", _intake_task(ws).body)
            set_key(ws, "scope.pages", "3-4")
            ws.reload()
            ensure_chapter_media(ws, {"id": "ch01", "start": {"page": 0, "y": 0}, "end": {"page": 11, "y": 1e9}})
            made = sorted(f.name for f in ws.page_images_dir.glob("*.png"))
            self.assertEqual(made, ["p0003.png", "p0004.png"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
