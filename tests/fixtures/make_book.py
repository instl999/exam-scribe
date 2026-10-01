"""Generate a small but realistic sample textbook PDF for ExamScribe tests.

The book imitates features of real textbooks that the pipeline must handle:
bookmarks (TOC), roman-numeral front matter, running headers and page numbers,
bold key terms, numbered equations with the number in a separate text run,
subscripts, a ligature, a hyphenated line break, boxed notes, vector and raster
figures with captions, a table, worked examples, end-of-chapter key terms,
key equations, summaries, review questions, an answer key, and one scanned
(image-only) page.

Usage:  python make_book.py [output.pdf]
Also writes <output>.truth.json with the ground truth used by the tests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pymupdf

W, H = 612, 792
LEFT, RIGHT, TOP, BOTTOM = 72, 540, 72, 724
CSS = (
    "* {font-family: sans-serif; font-size: 10.5pt; line-height: 1.32;}"
    "h1 {font-size: 22pt; margin: 0;} h2 {font-size: 14pt; margin: 0;}"
    "h3 {font-size: 11.5pt; margin: 0;} p {margin: 0;} ul {margin: 0;}"
    ".small {font-size: 9pt;}"
)


class Book:
    def __init__(self) -> None:
        self.doc = pymupdf.open()
        self.page = None
        self.y = TOP
        self.toc: list[list] = []
        self.truth: dict = {"sections": {}, "figures": [], "equations": [], "terms": {}, "examples": [],
                            "objectives": {}, "summary_paragraphs": {}, "boxed_terms": []}

    # ---- pages -------------------------------------------------------------
    def new_page(self, header: str | None = None, number: str | None = None) -> None:
        self.page = self.doc.new_page(width=W, height=H)
        self.y = TOP
        if header:
            self.page.insert_text((LEFT, 44), header, fontsize=8.5, fontname="helv", color=(0.35, 0.35, 0.35))
            self.page.draw_line((LEFT, 50), (RIGHT, 50), color=(0.7, 0.7, 0.7), width=0.5)
        if number:
            self.page.insert_text((W / 2 - 6, 760), number, fontsize=9, fontname="helv")

    @property
    def pno(self) -> int:
        return self.page.number

    # ---- content -----------------------------------------------------------
    def html(self, html: str, gap: float = 7, indent: float = 0, width: float | None = None) -> pymupdf.Rect:
        right = RIGHT - indent if width is None else LEFT + indent + width
        rect = pymupdf.Rect(LEFT + indent, self.y, right, BOTTOM)
        spare, scale = self.page.insert_htmlbox(rect, html, css=CSS, scale_low=1)
        if spare < 0:
            raise RuntimeError(f"content does not fit on page {self.pno + 1}: {html[:60]}")
        used = rect.height - spare
        placed = pymupdf.Rect(rect.x0, self.y, rect.x1, self.y + used)
        self.y += used + gap
        return placed

    def measure(self, html: str, width: float) -> float:
        tmp = pymupdf.open()
        pg = tmp.new_page(width=W, height=H)
        rect = pymupdf.Rect(0, 0, width, 700)
        spare, _ = pg.insert_htmlbox(rect, html, css=CSS, scale_low=1)
        return rect.height - spare

    def box(self, html: str, fill=(0.93, 0.95, 1.0), gap: float = 9) -> None:
        pad = 8
        inner_w = RIGHT - LEFT - 2 * pad
        h = self.measure(html, inner_w)
        rect = pymupdf.Rect(LEFT, self.y, RIGHT, self.y + h + 2 * pad)
        self.page.draw_rect(rect, color=(0.55, 0.6, 0.8), fill=fill, width=0.8)
        inner = pymupdf.Rect(LEFT + pad, self.y + pad, RIGHT - pad, BOTTOM)
        spare, _ = self.page.insert_htmlbox(inner, html, css=CSS, scale_low=1)
        if spare < 0:
            raise RuntimeError("box does not fit")
        self.y = rect.y1 + gap

    def heading(self, text: str, level: int, toc_title: str | None = None, section_id: str | None = None,
                toc_level: int | None = None) -> None:
        tag = {1: "h1", 2: "h2", 3: "h3"}[level]
        y0 = self.y
        self.html(f"<{tag}>{text}</{tag}>", gap=8)
        if toc_title:
            lvl = toc_level or (1 if level == 1 else 2)
            self.toc.append([lvl, toc_title, self.pno + 1,
                             {"kind": pymupdf.LINK_GOTO, "page": self.pno, "to": pymupdf.Point(LEFT, y0)}])
        if section_id:
            self.truth["sections"][section_id] = {"title": text, "page_index": self.pno}

    def equation(self, text: str, number: str | None) -> None:
        eq_html = (
            '<table style="width:100%"><tr>'
            f'<td style="width:86%;text-align:center">{text}</td>'
            f'<td style="text-align:right">{"(" + number + ")" if number else ""}</td>'
            "</tr></table>"
        )
        self.html(eq_html, gap=8)
        if number:
            self.truth["equations"].append({"number": number, "page_index": self.pno})

    def lines(self, lines: list[str], size: float = 10.5, leading: float = 13.9) -> None:
        """Place pre-broken lines (used to create a real hyphenated line break)."""
        y = self.y + size
        for ln in lines:
            self.page.insert_text((LEFT, y), ln, fontsize=size, fontname="helv")
            y += leading
        self.y = y - size + 8

    def vector_figure(self, number: str, caption: str, draw, height: float = 150) -> None:
        rect = pymupdf.Rect(LEFT + 90, self.y, RIGHT - 90, self.y + height)
        draw(self.page, rect)
        self.y = rect.y1 + 6
        self.html(f'<p class="small"><b>Figure {number}</b> {caption}</p>', gap=10)
        self.truth["figures"].append({"number": number, "page_index": self.pno, "kind": "vector"})

    def raster_figure(self, number: str, caption: str, draw, height: float = 150) -> None:
        tmp = pymupdf.open()
        pg = tmp.new_page(width=300, height=height)
        draw(pg, pymupdf.Rect(0, 0, 300, height))
        pix = pg.get_pixmap(dpi=110)
        rect = pymupdf.Rect(LEFT + 84, self.y, LEFT + 84 + 300, self.y + height)
        self.page.insert_image(rect, pixmap=pix)
        self.y = rect.y1 + 6
        self.html(f'<p class="small"><b>Figure {number}</b> {caption}</p>', gap=10)
        self.truth["figures"].append({"number": number, "page_index": self.pno, "kind": "raster"})

    def objectives(self, section_id: str, items: list[str]) -> None:
        lis = "".join(f"<li>{t}</li>" for t in items)
        self.box(f"<h3>Learning Objectives</h3><p>By the end of this section, you will be able to:</p><ul>{lis}</ul>",
                 fill=(0.95, 0.97, 0.93))
        self.truth["objectives"][section_id] = items

    def term(self, chapter: str, term: str) -> None:
        self.truth["terms"].setdefault(chapter, []).append(term)


# ---- drawings -----------------------------------------------------------------

def draw_hill(page, r):
    pts = [(r.x0, r.y1), (r.x0 + r.width * 0.15, r.y0 + 25), (r.x0 + r.width * 0.35, r.y0 + 20),
           (r.x0 + r.width * 0.7, r.y1 - 10), (r.x1, r.y1)]
    page.draw_polyline(pts, color=(0.2, 0.45, 0.2), width=2)
    page.draw_circle((r.x0 + r.width * 0.25, r.y0 + 10), 9, color=(0.6, 0.1, 0.1), fill=(0.9, 0.3, 0.3))
    page.draw_circle((r.x0 + r.width * 0.82, r.y1 - 14), 9, color=(0.6, 0.1, 0.1), fill=(0.9, 0.3, 0.3))
    page.insert_text((r.x0 + r.width * 0.25 - 12, r.y0 + 40), "PE max", fontsize=8, fontname="helv")
    page.insert_text((r.x0 + r.width * 0.82 - 14, r.y1 - 30), "KE max", fontsize=8, fontname="helv")


def draw_system(page, r):
    inner = pymupdf.Rect(r.x0 + r.width * 0.3, r.y0 + 30, r.x1 - r.width * 0.3, r.y1 - 30)
    page.draw_rect(r, color=(0.3, 0.3, 0.3), width=1)
    page.draw_rect(inner, color=(0.1, 0.2, 0.6), fill=(0.85, 0.9, 1.0), width=1.5)
    page.insert_text((inner.x0 + 12, inner.y0 + 45), "system", fontsize=9, fontname="helv")
    page.insert_text((r.x0 + 8, r.y0 + 16), "surroundings", fontsize=9, fontname="helv")
    page.draw_line((r.x0 + 20, r.y0 + r.height / 2), (inner.x0 - 4, r.y0 + r.height / 2), color=(0.8, 0.2, 0.1), width=2)
    page.draw_line((inner.x1 + 4, r.y0 + r.height / 2), (r.x1 - 20, r.y0 + r.height / 2), color=(0.1, 0.4, 0.8), width=2)


def draw_calorimeter(page, r):
    page.draw_rect(pymupdf.Rect(0, 0, r.width, r.height), color=None, fill=(1, 1, 1))
    cup = pymupdf.Rect(r.width * 0.3, 40, r.width * 0.7, r.height - 12)
    page.draw_rect(cup, color=(0.4, 0.4, 0.4), fill=(0.95, 0.95, 0.9), width=2)
    page.draw_rect(pymupdf.Rect(cup.x0 + 8, cup.y0 + 30, cup.x1 - 8, cup.y1 - 6), color=(0.2, 0.4, 0.8),
                   fill=(0.75, 0.85, 1.0), width=1)
    page.draw_line((r.width * 0.45, 8), (r.width * 0.45, r.height - 30), color=(0.5, 0.1, 0.1), width=2)
    page.draw_line((r.width * 0.58, 16), (r.width * 0.58, r.height - 26), color=(0.2, 0.2, 0.2), width=1.5)
    page.insert_text((r.width * 0.47, 20), "thermometer", fontsize=8, fontname="helv")
    page.insert_text((r.width * 0.60, 32), "stirrer", fontsize=8, fontname="helv")


# ---- the book ---------------------------------------------------------------------

def build(out: Path) -> dict:
    b = Book()
    body = 0

    def body_page(header: str | None) -> None:
        nonlocal body
        body += 1
        b.new_page(header, str(body))

    # Front matter (i-iii)
    b.new_page()
    b.y = 220
    b.html("<h1>Foundations of Chemistry</h1><h2>Energy and Change</h2>", gap=20)
    b.html("<p>Sample Edition for Testing ExamScribe</p><p class='small'>This short text was written for software "
           "testing. It follows the structure of an introductory chemistry textbook.</p>")
    b.new_page(number="ii")
    b.html("<h2>Contents</h2>")
    b.html("<p>Preface iii</p><p>1 Energy and Its Units 1</p><p>2 Thermochemistry 6</p><p>Answer Key 15</p>"
           "<p>Appendix A: SI Prefixes 16</p>")
    b.new_page(number="iii")
    b.heading("Preface", 2, toc_title="Preface", toc_level=1)
    b.html("<p>This sample book introduces energy, heat, and enthalpy. Each section begins with learning "
           "objectives, defines key terms in bold, and ends with review questions. Answers to the review "
           "questions appear in the Answer Key.</p>")

    # ----- Chapter 1 -----
    body_page(None)
    b.html('<p class="small">CHAPTER 1</p>', gap=2)
    b.heading("Energy and Its Units", 1, toc_title="1 Energy and Its Units")
    b.html("<p>Every chemical and physical change involves energy. This chapter introduces the main forms of "
           "energy and the units used to measure it.</p>")
    b.heading("1.1 What Is Energy?", 2, toc_title="1.1 What Is Energy?", section_id="1.1")
    b.objectives("1.1", ["Define energy and distinguish kinetic energy from potential energy",
                         "Calculate the kinetic energy of a moving object",
                         "Describe thermal energy as a form of kinetic energy"])
    b.html("<p>Chemical changes and physical changes are almost always accompanied by changes in energy. "
           "<b>Energy</b> is the capacity to supply heat or do work. Work is done when a force moves matter "
           "through a distance. Energy exists in many forms, but most of them can be grouped into two broad "
           "classes.</p>")
    b.term("ch01", "energy")
    b.html("<p><b>Kinetic energy</b> is the energy that an object possesses because of its motion. A rolling "
           "ball, a flowing river, and a vibrating molecule all have kinetic energy. The kinetic energy of an "
           "object depends on both its mass and its speed:</p>")
    b.term("ch01", "kinetic energy")
    b.equation("KE = ½mv²", "1.1")
    b.html("<p>where <i>m</i> is the mass of the object in kilograms and <i>v</i> is its speed in meters per "
           "second. Because the speed is squared, doubling the speed of an object multiplies its kinetic energy "
           "by four.</p>")

    body_page("Chapter 1 | Energy and Its Units")
    b.html("<p><b>Potential energy</b> is the energy that an object possesses because of its position, "
           "composition, or condition. A ball held above the ground has gravitational potential energy, and a "
           "battery stores chemical potential energy in the arrangement of its atoms.</p>")
    b.term("ch01", "potential energy")
    b.box("<p>Energy can be converted from one form to another, but it is never created or destroyed. This "
          "principle is called the <b>law of conservation of energy</b>.</p>")
    b.term("ch01", "law of conservation of energy")
    b.truth["boxed_terms"].append("law of conservation of energy")
    b.html("<p>The atoms and molecules in any sample of matter are in constant random motion. <b>Thermal "
           "energy</b> is the kinetic energy associated with the random motion of these particles. A cup of hot "
           "tea has more thermal energy than the same cup of tea after it has cooled, because its molecules move "
           "faster on average.</p>")
    b.term("ch01", "thermal energy")
    b.vector_figure("1.1", "A ball at the top of a hill has maximum potential energy. As it rolls down, "
                    "potential energy is converted to kinetic energy.", draw_hill)

    body_page("Chapter 1 | Energy and Its Units")
    b.box("<h3>Example 1.1 Calculating Kinetic Energy</h3>"
          "<p>A 0.500-kg ball rolls at a speed of 4.00 m/s. What is its kinetic energy?</p>"
          "<p><b>Solution</b> Substitute the mass and speed into Equation 1.1: KE = ½ × 0.500 kg "
          "× (4.00 m/s)² = 4.00 J.</p>", fill=(0.98, 0.96, 0.9))
    b.truth["examples"].append({"number": "1.1", "page_index": b.pno})
    b.heading("1.2 Units of Energy", 2, toc_title="1.2 Units of Energy", section_id="1.2")
    b.objectives("1.2", ["Identify the joule as the SI unit of energy", "Convert between joules and calories"])
    b.html("<p>The SI unit of energy is the <b>joule</b> (J). One joule is the kinetic energy of a 2-kg object "
           "moving at a speed of 1 meter per second. A joule is a small amount of energy, so chemists often "
           "report energies in kilojoules (kJ); 1 kJ = 1000 J.</p>")
    b.term("ch01", "joule")
    b.html("<p>An older unit, the <b>calorie</b> (cal), was originally defined as the amount of energy needed "
           "to raise the temperature of 1 gram of water by 1 degree Celsius. Today the calorie is defined in "
           "terms of the joule:</p>")
    b.term("ch01", "calorie")
    b.equation("1 cal = 4.184 J (exactly)", "1.2")

    body_page("Chapter 1 | Energy and Its Units")
    b.html("<p>The Calorie (with a capital C) that appears on food labels is actually a kilocalorie: "
           "1 Calorie = 1 kcal = 1000 cal.</p>")
    b.box("<h3>Example 1.2 Converting Calories to Joules</h3>"
          "<p>A snack releases 250 cal of energy when it is burned. How many joules is this?</p>"
          "<p><b>Solution</b> Multiply by the conversion factor from Equation 1.2: 250 cal × 4.184 J/cal "
          "= 1046 J, or about 1.05 kJ.</p>", fill=(0.98, 0.96, 0.9))
    b.truth["examples"].append({"number": "1.2", "page_index": b.pno})
    b.heading("Key Terms", 2, toc_title="Key Terms")
    for t, d in [("calorie (cal)", "unit of energy; 1 cal is defined as exactly 4.184 J"),
                 ("energy", "capacity to supply heat or do work"),
                 ("joule (J)", "SI unit of energy; 1 J = 1 kg·m²/s²"),
                 ("kinetic energy", "energy of an object due to its motion"),
                 ("law of conservation of energy", "energy is converted from one form to another but is never "
                  "created or destroyed"),
                 ("potential energy", "energy of an object due to its position, composition, or condition"),
                 ("thermal energy", "kinetic energy associated with the random motion of atoms and molecules")]:
        b.html(f"<p><b>{t}</b> {d}</p>", gap=4)

    body_page("Chapter 1 | Energy and Its Units")
    b.heading("Key Equations", 2, toc_title="Key Equations")
    b.html("<p>KE = ½mv²</p><p>1 cal = 4.184 J</p>")
    b.heading("Summary", 2, toc_title="Summary")
    b.html("<h3>1.1 What Is Energy?</h3><p>Energy is the capacity to supply heat or do work. Kinetic energy is "
           "energy of motion, and potential energy is energy of position, composition, or condition. Thermal "
           "energy is the kinetic energy of randomly moving particles.</p>")
    b.html("<h3>1.2 Units of Energy</h3><p>The joule is the SI unit of energy. One calorie equals exactly 4.184 "
           "joules.</p>")
    b.truth["summary_paragraphs"]["ch01"] = 2
    b.heading("Review Questions", 2, toc_title="Review Questions")
    b.html("<h3>1.1 What Is Energy?</h3>"
           "<p>1. Which of the following has the greatest kinetic energy? (a) a 1-kg ball at rest (b) a 1-kg ball "
           "moving at 2 m/s (c) a 1-kg ball moving at 1 m/s (d) a 2-kg ball at rest</p>"
           "<p>2. Calculate the kinetic energy of a 2.00-kg object moving at 3.00 m/s.</p>")
    b.html("<h3>1.2 Units of Energy</h3><p>3. Convert 500. cal to joules.</p>"
           "<p>4. How many calories are in 1.00 kJ?</p>")

    # ----- Chapter 2 -----
    body_page(None)
    b.html('<p class="small">CHAPTER 2</p>', gap=2)
    b.heading("Thermochemistry", 1, toc_title="2 Thermochemistry")
    b.html("<p>In Chapter 1 you learned that energy is the capacity to supply heat or do work, and that the joule "
           "is the SI unit of energy. This chapter applies those ideas to the heat that flows during chemical and "
           "physical changes, and to the thermal energy stored in matter.</p>")
    b.heading("2.1 Heat and Temperature", 2, toc_title="2.1 Heat and Temperature", section_id="2.1")
    b.objectives("2.1", ["Distinguish between heat and temperature", "Identify a system and its surroundings",
                         "Classify processes as endothermic or exothermic"])
    b.html("<p><b>Temperature</b> is a measure of the average kinetic energy of the particles in a sample of "
           "matter. <b>Heat</b> (<i>q</i>) is the transfer of thermal energy between two bodies at different "
           "temperatures. Heat always flows spontaneously from a hotter body to a colder body until both reach "
           "the same temperature.</p>")
    b.term("ch02", "temperature")
    b.term("ch02", "heat")
    b.html("<p>Temperature does not depend on the amount of matter present, whereas the amount of heat "
           "transferred does. A bathtub of warm water and a cup of water at the same temperature can transfer "
           "very different amounts of heat.</p>")

    body_page("Chapter 2 | Thermochemistry")
    b.html("<p>To study heat flow, chemists divide the universe into two parts. The <b>system</b> is the specific "
           "portion of matter being studied, such as the chemicals reacting in a flask. The <b>surroundings</b> "
           "are everything outside the system that can exchange energy with it.</p>")
    b.term("ch02", "system")
    b.term("ch02", "surroundings")
    b.html("<p>An <b>endothermic process</b> absorbs heat from the surroundings, so the surroundings become "
           "colder. Melting ice is endothermic. An <b>exothermic process</b> releases heat to the surroundings, so "
           "the surroundings become warmer. Burning wood is exothermic.</p>")
    b.term("ch02", "endothermic process")
    b.term("ch02", "exothermic process")
    b.lines(["When a hot metal block is placed in cool water, heat flows from the block into the water until the tempera-",
             "ture of the block equals the temperature of the water."])
    b.vector_figure("2.1", "In an endothermic process, heat flows into the system from the surroundings. In an "
                    "exothermic process, heat flows out of the system.", draw_system, height=130)

    body_page("Chapter 2 | Thermochemistry")
    b.heading("2.2 Specific Heat and Calorimetry", 2, toc_title="2.2 Specific Heat and Calorimetry", section_id="2.2")
    b.objectives("2.2", ["Define heat capacity and specific heat capacity",
                         "Calculate heat transferred using q = m × c × ΔT",
                         "Explain how a coffee-cup calorimeter measures heat"])
    b.html("<p>The <b>heat capacity</b> (<i>C</i>) of an object is the amount of heat needed to raise its "
           "temperature by 1 °C. Heat capacity depends on both the kind of substance and its amount.</p>")
    b.term("ch02", "heat capacity")
    b.html("<p>The <b>specific heat capacity</b> (<i>c</i>) of a substance is the amount of heat needed to raise "
           "the temperature of 1 gram of the substance by 1 °C. Speciﬁc heat is an intensive property: it "
           "depends only on the kind of substance, not on the amount.</p>")
    b.term("ch02", "specific heat capacity")
    b.html("<p>The heat absorbed or released by a sample that changes temperature without changing phase is "
           "given by</p>")
    b.equation("q = m × c × ΔT", "2.1")
    b.html("<p>where <i>q</i> is the heat in joules, <i>m</i> is the mass in grams, <i>c</i> is the specific heat "
           "in J/(g·°C), and Δ<i>T</i> is the change in temperature (final temperature minus initial "
           "temperature). When <i>q</i> is positive the sample absorbs heat; when <i>q</i> is negative the sample "
           "releases heat.</p>")

    body_page("Chapter 2 | Thermochemistry")
    b.html("<p class='small'><b>Table 2.1</b> Specific Heats of Common Substances at 25 °C</p>", gap=4)
    b.html("<table style='width:70%'><tr><td><b>Substance</b></td><td><b>c (J/(g·°C))</b></td></tr>"
           "<tr><td>water (liquid)</td><td>4.184</td></tr><tr><td>aluminum</td><td>0.897</td></tr>"
           "<tr><td>iron</td><td>0.449</td></tr><tr><td>copper</td><td>0.385</td></tr></table>", gap=10)
    b.box("<h3>Example 2.1 Heat Absorbed by Water</h3>"
          "<p>How much heat is absorbed when 250. g of water is heated from 20.0 °C to 35.0 °C?</p>"
          "<p><b>Solution</b> The temperature change is ΔT = 35.0 °C − 20.0 °C = 15.0 °C. "
          "Then q = m × c × ΔT = (250. g)(4.184 J/(g·°C))(15.0 °C) = 15,690 J = "
          "15.7 kJ. Because q is positive, the water absorbed heat.</p>", fill=(0.98, 0.96, 0.9))
    b.truth["examples"].append({"number": "2.1", "page_index": b.pno})
    b.html("<p>A <b>calorimeter</b> is a device used to measure the heat that flows during a chemical or physical "
           "process. In a simple coffee-cup calorimeter, a reaction takes place in water inside an insulated cup, "
           "and the temperature change of the water is used to calculate the heat released or absorbed by the "
           "reaction.</p>")
    b.term("ch02", "calorimeter")

    body_page("Chapter 2 | Thermochemistry")
    b.raster_figure("2.2", "A coffee-cup calorimeter. Nested foam cups limit heat exchange with the surroundings.",
                    draw_calorimeter, height=140)
    b.box("<p>Because the calorimeter is insulated, we assume that the heat released by the reaction equals the "
          "heat absorbed by the water: q<sub>reaction</sub> = −q<sub>water</sub>.</p>")
    b.heading("2.3 Enthalpy", 2, toc_title="2.3 Enthalpy", section_id="2.3")
    b.objectives("2.3", ["Define enthalpy and enthalpy change",
                         "Relate the sign of ΔH to endothermic and exothermic processes"])

    body_page("Chapter 2 | Thermochemistry")
    b.html("<p>Most chemical reactions in the laboratory take place in open containers at constant atmospheric "
           "pressure. <b>Enthalpy</b> (<i>H</i>) is a property of a system equal to its internal energy plus the "
           "product of its pressure and volume:</p>")
    b.term("ch02", "enthalpy")
    b.equation("H = U + PV", "2.2")
    b.html("<p>Chemists rarely measure enthalpy itself; instead they measure changes in enthalpy. The "
           "<b>enthalpy change</b> (Δ<i>H</i>) for a process carried out at constant pressure equals the heat "
           "absorbed or released by the system:</p>")
    b.term("ch02", "enthalpy change")
    b.equation("ΔH = q<sub>p</sub>", "2.3")
    b.html("<p>For an endothermic reaction, the system absorbs heat, so ΔH is positive. For an exothermic "
           "reaction, the system releases heat, so ΔH is negative. For example, the combustion of methane "
           "releases 890 kJ of heat per mole of methane burned, so ΔH = −890 kJ.</p>")
    b.html("<p>Unlike heat, which depends on the path taken, enthalpy is a state function: ΔH depends only on "
           "the initial and final states of the system.</p>")
    b.box("<h3>Example 2.2 Classifying a Reaction</h3>"
          "<p>The reaction N<sub>2</sub>(g) + O<sub>2</sub>(g) → 2 NO(g) has ΔH = +180.5 kJ. Is it "
          "endothermic or exothermic?</p><p><b>Solution</b> ΔH is positive, so the reaction absorbs heat "
          "and is endothermic.</p>", fill=(0.98, 0.96, 0.9))
    b.truth["examples"].append({"number": "2.2", "page_index": b.pno})

    body_page("Chapter 2 | Thermochemistry")
    b.heading("Key Terms", 2, toc_title="Key Terms")
    for t, d in [("calorimeter", "device used to measure the heat that flows during a chemical or physical process"),
                 ("endothermic process", "process that absorbs heat from the surroundings"),
                 ("enthalpy (H)", "property of a system equal to its internal energy plus the product of its "
                  "pressure and volume"),
                 ("enthalpy change (ΔH)", "heat absorbed or released by a system at constant pressure"),
                 ("exothermic process", "process that releases heat to the surroundings"),
                 ("heat (q)", "transfer of thermal energy between two bodies at different temperatures"),
                 ("heat capacity (C)", "amount of heat needed to raise the temperature of an object by 1 °C"),
                 ("specific heat capacity (c)", "amount of heat needed to raise the temperature of 1 gram of a "
                  "substance by 1 °C"),
                 ("surroundings", "everything outside the system that can exchange energy with it"),
                 ("system", "specific portion of matter being studied"),
                 ("temperature", "measure of the average kinetic energy of the particles in a sample")]:
        b.html(f"<p><b>{t}</b> {d}</p>", gap=4)

    body_page("Chapter 2 | Thermochemistry")
    b.heading("Key Equations", 2, toc_title="Key Equations")
    b.html("<p>q = m × c × ΔT</p><p>H = U + PV</p><p>ΔH = q<sub>p</sub></p>")
    b.heading("Summary", 2, toc_title="Summary")
    b.html("<h3>2.1 Heat and Temperature</h3><p>Heat is the transfer of thermal energy between bodies at different "
           "temperatures, and temperature measures the average kinetic energy of particles. Endothermic processes "
           "absorb heat; exothermic processes release heat.</p>")
    b.html("<h3>2.2 Specific Heat and Calorimetry</h3><p>The specific heat capacity of a substance is the heat "
           "needed to raise the temperature of 1 g by 1 °C. The heat for a temperature change is "
           "q = m × c × ΔT. Calorimeters measure heat flow.</p>")
    b.html("<h3>2.3 Enthalpy</h3><p>Enthalpy is H = U + PV. At constant pressure, the enthalpy change equals the "
           "heat absorbed or released. ΔH is positive for endothermic processes and negative for exothermic "
           "processes.</p>")
    b.truth["summary_paragraphs"]["ch02"] = 3

    body_page("Chapter 2 | Thermochemistry")
    b.heading("Review Questions", 2, toc_title="Review Questions")
    b.html("<h3>2.1 Heat and Temperature</h3>"
           "<p>5. Is the freezing of water endothermic or exothermic? Explain.</p>"
           "<p>6. Identify the system and the surroundings when a reaction occurs in a beaker of water.</p>")
    b.html("<h3>2.2 Specific Heat and Calorimetry</h3>"
           "<p>7. How much heat is needed to raise the temperature of 50.0 g of aluminum from 25.0 °C to "
           "75.0 °C?</p><p>8. A 100.0-g sample of copper absorbs 385 J of heat. By how much does its "
           "temperature rise?</p>")
    b.html("<h3>2.3 Enthalpy</h3><p>9. The combustion of methane has ΔH = −890 kJ. Is heat absorbed or "
           "released?</p>")

    body_page(None)
    b.heading("Answer Key", 2, toc_title="Answer Key", toc_level=1)
    b.html("<h3>Chapter 1</h3><p>1. (b)</p><p>2. 9.00 J</p><p>3. 2092 J (2.09 kJ)</p><p>4. 239 cal</p>")
    b.html("<h3>Chapter 2</h3><p>5. Exothermic; liquid water releases heat as it freezes.</p>"
           "<p>7. 2.24 × 10³ J (2.24 kJ)</p><p>8. 10.0 °C</p><p>9. Released (exothermic).</p>")

    # Scanned appendix page (image only, no text layer)
    body += 1
    tmp = pymupdf.open()
    tp = tmp.new_page(width=W, height=H)
    tp.insert_htmlbox(pymupdf.Rect(LEFT, TOP, RIGHT, BOTTOM),
                      "<h2>Appendix A: SI Prefixes</h2><p>kilo (k) = 10<sup>3</sup>; mega (M) = 10<sup>6</sup>; "
                      "milli (m) = 10<sup>-3</sup>; micro (µ) = 10<sup>-6</sup></p>", css=CSS)
    pix = tp.get_pixmap(dpi=90)
    pg = b.doc.new_page(width=W, height=H)
    pg.insert_image(pg.rect, pixmap=pix)
    b.toc.append([1, "Appendix A: SI Prefixes", pg.number + 1])

    # Page labels: i-iii then 1..
    b.doc.set_page_labels([{"startpage": 0, "prefix": "", "style": "r", "firstpagenum": 1},
                           {"startpage": 3, "prefix": "", "style": "D", "firstpagenum": 1}])
    b.doc.set_toc(b.toc)
    b.doc.set_metadata({"title": "Foundations of Chemistry: Energy and Change", "author": "ExamScribe test suite"})
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        b.doc.subset_fonts()          # each HTML box embeds its own font copy; subsetting keeps the file small
    except Exception:
        pass
    b.doc.save(str(out), garbage=4, deflate=True, clean=True)
    truth = b.truth
    truth["page_count"] = b.doc.page_count
    truth["chapters"] = {"ch01": {"title": "Energy and Its Units", "sections": ["1.1", "1.2"]},
                         "ch02": {"title": "Thermochemistry", "sections": ["2.1", "2.2", "2.3"]}}
    truth["scanned_page_index"] = b.doc.page_count - 1
    Path(str(out) + ".truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")
    return truth


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "out" / "sample-textbook.pdf"
    t = build(target)
    print(f"wrote {target} ({t['page_count']} pages)")
