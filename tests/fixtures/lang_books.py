"""Small text-PDF textbooks in several languages (same chemistry content), for testing extraction,
outline, inventory and quote checks outside English.

    python lang_books.py <out-folder> [lang ...]      # default: every language below

Each book: a title page, two chapters with two numbered sections each (bold key terms in defining sentences,
filler paragraphs, a figure with caption, a numbered equation, a worked example), and end-of-chapter key terms,
summary and exercises; bookmarks (TOC) and printed page numbers in the footer. Also writes <book>.truth.json.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pymupdf

LANGS = {
    "zh": dict(
        title="基础化学", chapter="第{n}章", rtl=False,
        chapters=["能量及其单位", "热化学"],
        sections=[["什么是能量", "能量的单位"], ["热与温度", "比热容"]],
        defs=[[("能量", "能量是做功或提供热量的能力。"), ("动能", "动能是物体由于运动而具有的能量。")],
              [("焦耳", "焦耳是国际单位制中的能量单位。"), ("卡路里", "卡路里最初被定义为使一克水升高一摄氏度所需的热量。")],
              [("温度", "温度是物质中粒子平均动能的量度。"), ("热", "热是在不同温度的物体之间传递的热能。")],
              [("热容", "热容是使物体温度升高一摄氏度所需的热量。"),
               ("比热容", "比热容是使一克物质温度升高一摄氏度所需的热量。")]],
        filler=["化学变化和物理变化几乎总是伴随着能量的变化。", "能量可以从一种形式转化为另一种形式，但它既不会被创造也不会被消灭。",
                "在实验室中，我们通常用温度计测量温度的变化。", "物质的量越大，吸收或释放的热量就越多。",
                "这一原理在日常生活中有很多应用。", "下面的例题说明了如何使用这个公式。"],
        figure="图", example="例题", summary="本章小结", key_terms="关键术语", exercises="习题",
        example_text=["计算质量为 2.00 千克、速度为 3.00 米每秒的物体的动能。", "解：代入公式可得动能为 9.00 焦耳。"],
        exercise_items=["什么是能量？", "一卡路里等于多少焦耳？"],
        caption="能量在不同形式之间转化的示意图。"),
    "ja": dict(
        title="基礎化学", chapter="第{n}章", rtl=False,
        chapters=["エネルギーとその単位", "熱化学"],
        sections=[["エネルギーとは何か", "エネルギーの単位"], ["熱と温度", "比熱容量"]],
        defs=[[("エネルギー", "エネルギーとは、仕事をしたり熱を供給したりする能力である。"),
               ("運動エネルギー", "運動エネルギーとは、物体が運動していることによって持つエネルギーである。")],
              [("ジュール", "ジュールは国際単位系におけるエネルギーの単位である。"),
               ("カロリー", "カロリーはもともと水一グラムの温度を一度上げるのに必要な熱量として定義された。")],
              [("温度", "温度とは、物質を構成する粒子の平均運動エネルギーの尺度である。"),
               ("熱", "熱とは、温度の異なる物体の間を移動する熱エネルギーである。")],
              [("熱容量", "熱容量とは、物体の温度を一度上げるのに必要な熱量である。"),
               ("比熱容量", "比熱容量とは、物質一グラムの温度を一度上げるのに必要な熱量である。")]],
        filler=["化学変化や物理変化には、ほとんどの場合エネルギーの出入りが伴う。", "エネルギーはある形から別の形に変換できるが、生成も消滅もしない。",
                "実験室では、温度の変化を温度計で測定することが多い。", "物質の量が多いほど、吸収または放出される熱量も多くなる。",
                "この原理は日常生活の多くの場面で利用されている。", "次の例題では、この式の使い方を示す。"],
        figure="図", example="例題", summary="まとめ", key_terms="重要用語", exercises="演習問題",
        example_text=["質量 2.00 kg、速さ 3.00 m/s で運動する物体の運動エネルギーを求めよ。", "解：式に代入すると、運動エネルギーは 9.00 J となる。"],
        exercise_items=["エネルギーとは何か。", "1 カロリーは何ジュールか。"],
        caption="エネルギーの形態の変換を示す模式図。"),
    "ko": dict(
        title="기초 화학", chapter="제{n}장", rtl=False,
        chapters=["에너지와 그 단위", "열화학"],
        sections=[["에너지란 무엇인가", "에너지의 단위"], ["열과 온도", "비열"]],
        defs=[[("에너지", "에너지는 일을 하거나 열을 공급하는 능력이다."), ("운동 에너지", "운동 에너지는 물체가 운동하기 때문에 가지는 에너지이다.")],
              [("줄", "줄은 국제단위계에서 에너지의 단위이다."),
               ("칼로리", "칼로리는 원래 물 1그램의 온도를 1도 올리는 데 필요한 열의 양으로 정의되었다.")],
              [("온도", "온도는 물질을 이루는 입자들의 평균 운동 에너지의 척도이다."), ("열", "열은 온도가 다른 물체 사이에서 이동하는 열에너지이다.")],
              [("열용량", "열용량은 물체의 온도를 1도 올리는 데 필요한 열의 양이다."),
               ("비열", "비열은 물질 1그램의 온도를 1도 올리는 데 필요한 열의 양이다.")]],
        filler=["화학 변화와 물리 변화에는 거의 항상 에너지 변화가 따른다.", "에너지는 한 형태에서 다른 형태로 바뀔 수 있지만 생성되거나 소멸되지 않는다.",
                "실험실에서는 보통 온도계로 온도 변화를 측정한다.", "물질의 양이 많을수록 흡수하거나 방출하는 열의 양도 많다.",
                "이 원리는 일상생활에서 널리 이용된다.", "다음 예제는 이 식을 사용하는 방법을 보여 준다."],
        figure="그림", example="예제", summary="요약", key_terms="핵심 용어", exercises="연습 문제",
        example_text=["질량이 2.00 kg이고 속력이 3.00 m/s인 물체의 운동 에너지를 구하시오.", "풀이: 식에 대입하면 운동 에너지는 9.00 J이다."],
        exercise_items=["에너지란 무엇인가?", "1칼로리는 몇 줄인가?"],
        caption="에너지 형태의 변환을 보여 주는 모식도."),
    "ru": dict(
        title="Основы химии", chapter="Глава {n}", rtl=False,
        chapters=["Энергия и её единицы", "Термохимия"],
        sections=[["Что такое энергия", "Единицы энергии"], ["Теплота и температура", "Удельная теплоёмкость"]],
        defs=[[("Энергия", "Энергия — это способность совершать работу или передавать теплоту."),
               ("Кинетическая энергия", "Кинетическая энергия — это энергия, которой обладает тело вследствие своего движения.")],
              [("Джоуль", "Джоуль — это единица энергии в Международной системе единиц."),
               ("Калория", "Калория первоначально была определена как количество теплоты, необходимое для нагревания одного грамма воды на один градус.")],
              [("Температура", "Температура — это мера средней кинетической энергии частиц вещества."),
               ("Теплота", "Теплота — это тепловая энергия, передаваемая между телами с разной температурой.")],
              [("Теплоёмкость", "Теплоёмкость — это количество теплоты, необходимое для нагревания тела на один градус."),
               ("Удельная теплоёмкость", "Удельная теплоёмкость — это количество теплоты, необходимое для нагревания одного грамма вещества на один градус.")]],
        filler=["Химические и физические изменения почти всегда сопровождаются изменением энергии.",
                "Энергия может переходить из одной формы в другую, но она не создаётся и не исчезает.",
                "В лаборатории изменение температуры обычно измеряют термометром.",
                "Чем больше количество вещества, тем больше теплоты оно поглощает или выделяет.",
                "Этот принцип широко используется в повседневной жизни.", "Следующий пример показывает, как пользоваться этой формулой."],
        figure="Рис.", example="Пример", summary="Резюме", key_terms="Ключевые термины", exercises="Упражнения",
        example_text=["Вычислите кинетическую энергию тела массой 2,00 кг, движущегося со скоростью 3,00 м/с.",
                      "Решение: подставив значения в формулу, получаем 9,00 Дж."],
        exercise_items=["Что такое энергия?", "Сколько джоулей в одной калории?"],
        caption="Схема превращения энергии из одной формы в другую."),
    "de": dict(
        title="Grundlagen der Chemie", chapter="Kapitel {n}", rtl=False,
        chapters=["Energie und ihre Einheiten", "Thermochemie"],
        sections=[["Was ist Energie?", "Einheiten der Energie"], ["Wärme und Temperatur", "Spezifische Wärmekapazität"]],
        defs=[[("Energie", "Energie ist die Fähigkeit, Arbeit zu verrichten oder Wärme zu liefern."),
               ("kinetische Energie", "Die kinetische Energie ist die Energie, die ein Körper aufgrund seiner Bewegung besitzt.")],
              [("Joule", "Das Joule ist die SI-Einheit der Energie."),
               ("Kalorie", "Die Kalorie wurde ursprünglich als die Wärmemenge definiert, die ein Gramm Wasser um ein Grad erwärmt.")],
              [("Temperatur", "Die Temperatur ist ein Maß für die mittlere kinetische Energie der Teilchen eines Stoffes."),
               ("Wärme", "Wärme ist die thermische Energie, die zwischen Körpern unterschiedlicher Temperatur übertragen wird.")],
              [("Wärmekapazität", "Die Wärmekapazität ist die Wärmemenge, die nötig ist, um die Temperatur eines Körpers um ein Grad zu erhöhen."),
               ("spezifische Wärmekapazität", "Die spezifische Wärmekapazität ist die Wärmemenge, die nötig ist, um ein Gramm eines Stoffes um ein Grad zu erwärmen.")]],
        filler=["Chemische und physikalische Veränderungen sind fast immer mit Energieänderungen verbunden.",
                "Energie kann von einer Form in eine andere umgewandelt werden, sie wird aber weder erzeugt noch vernichtet.",
                "Im Labor misst man Temperaturänderungen meist mit einem Thermometer.",
                "Je größer die Stoffmenge ist, desto mehr Wärme nimmt sie auf oder gibt sie ab.",
                "Dieses Prinzip wird im Alltag vielfach genutzt, z. B. beim Kochen.", "Das folgende Beispiel zeigt, wie man diese Formel verwendet."],
        figure="Abb.", example="Beispiel", summary="Zusammenfassung", key_terms="Schlüsselbegriffe", exercises="Aufgaben",
        example_text=["Berechnen Sie die kinetische Energie eines Körpers mit der Masse 2,00 kg, der sich mit 3,00 m/s bewegt.",
                      "Lösung: Einsetzen in die Formel ergibt 9,00 J."],
        exercise_items=["Was ist Energie?", "Wie viele Joule entsprechen einer Kalorie?"],
        caption="Schema der Umwandlung von Energieformen."),
    "fr": dict(
        title="Chimie générale", chapter="Chapitre {n}", rtl=False,
        chapters=["L'énergie et ses unités", "Thermochimie"],
        sections=[["Qu'est-ce que l'énergie ?", "Les unités d'énergie"], ["Chaleur et température", "Capacité thermique massique"]],
        defs=[[("énergie", "L'énergie est la capacité à fournir un travail ou de la chaleur."),
               ("énergie cinétique", "L'énergie cinétique est l'énergie que possède un corps du fait de son mouvement.")],
              [("joule", "Le joule est l'unité d'énergie du Système international."),
               ("calorie", "La calorie a été définie à l'origine comme la quantité de chaleur nécessaire pour élever d'un degré la température d'un gramme d'eau.")],
              [("température", "La température est une mesure de l'énergie cinétique moyenne des particules d'une substance."),
               ("chaleur", "La chaleur est l'énergie thermique transférée entre des corps de températures différentes.")],
              [("capacité thermique", "La capacité thermique est la quantité de chaleur nécessaire pour élever d'un degré la température d'un corps."),
               ("capacité thermique massique", "La capacité thermique massique est la quantité de chaleur nécessaire pour élever d'un degré la température d'un gramme de substance.")]],
        filler=["Les transformations chimiques et physiques s'accompagnent presque toujours d'une variation d'énergie.",
                "L'énergie peut passer d'une forme à une autre, mais elle n'est ni créée ni détruite.",
                "Au laboratoire, on mesure généralement les variations de température avec un thermomètre.",
                "Plus la quantité de matière est grande, plus la chaleur absorbée ou libérée est importante.",
                "Ce principe est utilisé dans de nombreuses situations de la vie courante.", "L'exemple suivant montre comment utiliser cette formule."],
        figure="Figure", example="Exemple", summary="Résumé", key_terms="Termes clés", exercises="Exercices",
        example_text=["Calculez l'énergie cinétique d'un corps de masse 2,00 kg se déplaçant à 3,00 m/s.",
                      "Solution : en remplaçant dans la formule, on obtient 9,00 J."],
        exercise_items=["Qu'est-ce que l'énergie ?", "Combien de joules vaut une calorie ?"],
        caption="Schéma de la conversion entre formes d'énergie."),
    "es": dict(
        title="Química general", chapter="Capítulo {n}", rtl=False,
        chapters=["La energía y sus unidades", "Termoquímica"],
        sections=[["¿Qué es la energía?", "Unidades de energía"], ["Calor y temperatura", "Capacidad calorífica específica"]],
        defs=[[("energía", "La energía es la capacidad de realizar trabajo o de suministrar calor."),
               ("energía cinética", "La energía cinética es la energía que posee un cuerpo debido a su movimiento.")],
              [("julio", "El julio es la unidad de energía del Sistema Internacional."),
               ("caloría", "La caloría se definió originalmente como la cantidad de calor necesaria para elevar un grado la temperatura de un gramo de agua.")],
              [("temperatura", "La temperatura es una medida de la energía cinética media de las partículas de una sustancia."),
               ("calor", "El calor es la energía térmica que se transfiere entre cuerpos a distinta temperatura.")],
              [("capacidad calorífica", "La capacidad calorífica es la cantidad de calor necesaria para elevar un grado la temperatura de un cuerpo."),
               ("capacidad calorífica específica", "La capacidad calorífica específica es la cantidad de calor necesaria para elevar un grado la temperatura de un gramo de sustancia.")]],
        filler=["Los cambios químicos y físicos casi siempre van acompañados de cambios de energía.",
                "La energía puede transformarse de una forma a otra, pero no se crea ni se destruye.",
                "En el laboratorio, los cambios de temperatura suelen medirse con un termómetro.",
                "Cuanto mayor es la cantidad de sustancia, mayor es el calor que absorbe o libera.",
                "Este principio se aplica en muchas situaciones de la vida diaria.", "El siguiente ejemplo muestra cómo usar esta fórmula."],
        figure="Figura", example="Ejemplo", summary="Resumen", key_terms="Términos clave", exercises="Ejercicios",
        example_text=["Calcule la energía cinética de un cuerpo de 2,00 kg que se mueve a 3,00 m/s.",
                      "Solución: al sustituir en la fórmula se obtiene 9,00 J."],
        exercise_items=["¿Qué es la energía?", "¿Cuántos julios equivalen a una caloría?"],
        caption="Esquema de la conversión entre formas de energía."),
    "ar": dict(
        title="أساسيات الكيمياء", chapter="الفصل {n}", rtl=True,
        chapters=["الطاقة ووحداتها", "الكيمياء الحرارية"],
        sections=[["ما هي الطاقة", "وحدات الطاقة"], ["الحرارة ودرجة الحرارة", "السعة الحرارية النوعية"]],
        defs=[[("الطاقة", "الطاقة هي القدرة على بذل شغل أو توفير حرارة."), ("الطاقة الحركية", "الطاقة الحركية هي الطاقة التي يمتلكها الجسم بسبب حركته.")],
              [("الجول", "الجول هو وحدة الطاقة في النظام الدولي للوحدات."),
               ("السعر الحراري", "عرف السعر الحراري في الأصل بأنه كمية الحرارة اللازمة لرفع درجة حرارة غرام واحد من الماء درجة واحدة.")],
              [("درجة الحرارة", "درجة الحرارة هي مقياس لمتوسط الطاقة الحركية لجسيمات المادة."),
               ("الحرارة", "الحرارة هي الطاقة الحرارية المنتقلة بين أجسام مختلفة في درجة حرارتها.")],
              [("السعة الحرارية", "السعة الحرارية هي كمية الحرارة اللازمة لرفع درجة حرارة الجسم درجة واحدة."),
               ("السعة الحرارية النوعية", "السعة الحرارية النوعية هي كمية الحرارة اللازمة لرفع درجة حرارة غرام واحد من المادة درجة واحدة.")]],
        filler=["تصاحب التغيرات الكيميائية والفيزيائية دائما تقريبا تغيرات في الطاقة.", "يمكن أن تتحول الطاقة من شكل إلى آخر لكنها لا تفنى ولا تستحدث.",
                "في المختبر نقيس عادة التغير في درجة الحرارة بمقياس الحرارة.", "كلما زادت كمية المادة زادت كمية الحرارة الممتصة أو المنطلقة.",
                "يستخدم هذا المبدأ في مواقف كثيرة من الحياة اليومية.", "يوضح المثال التالي كيفية استخدام هذه الصيغة."],
        figure="شكل", example="مثال", summary="ملخص", key_terms="المصطلحات الرئيسية", exercises="تمارين",
        example_text=["احسب الطاقة الحركية لجسم كتلته 2.00 kg يتحرك بسرعة 3.00 m/s.", "الحل: بالتعويض في الصيغة نحصل على 9.00 J."],
        exercise_items=["ما هي الطاقة؟", "كم جولا يساوي السعر الحراري الواحد؟"],
        caption="مخطط يوضح تحول الطاقة من شكل إلى آخر."),
    "hi": dict(
        title="रसायन विज्ञान के मूल सिद्धांत", chapter="अध्याय {n}", rtl=False,
        chapters=["ऊर्जा और उसकी इकाइयाँ", "ऊष्मा रसायन"],
        sections=[["ऊर्जा क्या है", "ऊर्जा की इकाइयाँ"], ["ऊष्मा और तापमान", "विशिष्ट ऊष्मा धारिता"]],
        defs=[[("ऊर्जा", "ऊर्जा कार्य करने या ऊष्मा प्रदान करने की क्षमता है।"), ("गतिज ऊर्जा", "गतिज ऊर्जा वह ऊर्जा है जो किसी वस्तु में उसकी गति के कारण होती है।")],
              [("जूल", "जूल अंतरराष्ट्रीय मात्रक प्रणाली में ऊर्जा का मात्रक है।"),
               ("कैलोरी", "कैलोरी को मूल रूप से एक ग्राम पानी का तापमान एक डिग्री बढ़ाने के लिए आवश्यक ऊष्मा के रूप में परिभाषित किया गया था।")],
              [("तापमान", "तापमान किसी पदार्थ के कणों की औसत गतिज ऊर्जा का माप है।"),
               ("ऊष्मा", "ऊष्मा वह तापीय ऊर्जा है जो अलग-अलग तापमान वाली वस्तुओं के बीच स्थानांतरित होती है।")],
              [("ऊष्मा धारिता", "ऊष्मा धारिता किसी वस्तु का तापमान एक डिग्री बढ़ाने के लिए आवश्यक ऊष्मा है।"),
               ("विशिष्ट ऊष्मा धारिता", "विशिष्ट ऊष्मा धारिता किसी पदार्थ के एक ग्राम का तापमान एक डिग्री बढ़ाने के लिए आवश्यक ऊष्मा है।")]],
        filler=["रासायनिक और भौतिक परिवर्तनों के साथ लगभग हमेशा ऊर्जा परिवर्तन होता है।",
                "ऊर्जा एक रूप से दूसरे रूप में बदल सकती है, परंतु न तो इसे बनाया जा सकता है और न ही नष्ट किया जा सकता है।",
                "प्रयोगशाला में तापमान में परिवर्तन प्रायः थर्मामीटर से मापा जाता है।",
                "पदार्थ की मात्रा जितनी अधिक होती है, अवशोषित या मुक्त ऊष्मा उतनी ही अधिक होती है।",
                "इस सिद्धांत का उपयोग दैनिक जीवन में कई स्थितियों में होता है।", "निम्नलिखित उदाहरण दिखाता है कि इस सूत्र का उपयोग कैसे करें।"],
        figure="चित्र", example="उदाहरण", summary="सारांश", key_terms="मुख्य शब्द", exercises="अभ्यास",
        example_text=["2.00 kg द्रव्यमान और 3.00 m/s चाल वाली वस्तु की गतिज ऊर्जा की गणना कीजिए।", "हल: सूत्र में मान रखने पर गतिज ऊर्जा 9.00 J प्राप्त होती है।"],
        exercise_items=["ऊर्जा क्या है?", "एक कैलोरी में कितने जूल होते हैं?"],
        caption="ऊर्जा के एक रूप से दूसरे रूप में परिवर्तन का आरेख।"),
}

CSS = """
body { font-size: 11pt; line-height: 1.45; }
h1 { font-size: 22pt; margin: 0 0 6pt 0; }
h2 { font-size: 14pt; margin: 14pt 0 6pt 0; }
h3 { font-size: 12pt; margin: 10pt 0 4pt 0; }
p { margin: 0 0 7pt 0; text-align: justify; }
p.label { font-size: 12pt; margin: 0; }
p.eq { text-align: center; margin: 8pt 0; }
p.caption { font-size: 9pt; }
div.box { border: 1pt solid #444; padding: 6pt; margin: 8pt 0; }
"""


def _bold_first(sentence: str, term: str) -> str:
    i = sentence.find(term)
    if i < 0:
        i = sentence.lower().find(term.lower())
    if i < 0:
        return sentence
    return sentence[:i] + "<b>" + sentence[i:i + len(term)] + "</b>" + sentence[i + len(term):]


def book_html(L: dict) -> tuple[str, dict]:
    parts = []
    truth = {"terms": {}, "sections": {}, "captions": [], "examples": [], "chapters": []}
    sep = "" if L is LANGS.get("zh") or L is LANGS.get("ja") else " "
    for ci, ch in enumerate(L["chapters"], start=1):
        cid = f"ch{ci:02d}"
        truth["chapters"].append(ch)
        truth["terms"][cid] = []
        parts.append(f'<p class="label" style="page-break-before: always">{L["chapter"].format(n=ci)}</p>'
                     f'<h1 id="c{ci}">{ch}</h1>')
        parts.append(f"<p>{L['filler'][0]}{sep}{L['filler'][1]}</p>")
        for si, sec in enumerate(L["sections"][ci - 1], start=1):
            sid = f"{ci}.{si}"
            truth["sections"][sid] = f"{sid} {sec}"
            parts.append(f'<h2 id="s{ci}{si}">{sid} {sec}</h2>')
            for term, sentence in L["defs"][(ci - 1) * 2 + si - 1]:
                truth["terms"][cid].append(term)
                parts.append(f"<p>{_bold_first(sentence, term)}{sep}{L['filler'][2]}{sep}{L['filler'][3]}</p>")
            parts.append(f"<p>{L['filler'][4]}{sep}{L['filler'][5]}</p>")
            if si == 1:
                cap = f"{L['figure']} {ci}.1 {L['caption']}"
                truth["captions"].append(cap)
                parts.append('<div style="height: 90pt; border: 1pt solid #333; margin: 6pt 40pt;"></div>'
                             f'<p class="caption"><b>{L["figure"]} {ci}.1</b> {L["caption"]}</p>')
            else:
                parts.append(f'<p class="eq">q = m × c × ΔT ({ci}.1)</p>')
                truth["examples"].append(f"{ci}.1")
                parts.append(f'<div class="box"><p><b>{L["example"]} {ci}.1</b></p>'
                             f'<p>{L["example_text"][0]}</p><p>{L["example_text"][1]}</p></div>')
        parts.append(f'<h2 id="k{ci}">{L["key_terms"]}</h2>')
        for term, sentence in [d for pair in L["defs"][(ci - 1) * 2:(ci - 1) * 2 + 2] for d in pair]:
            parts.append(f"<p><b>{term}</b> {sentence}</p>")
        parts.append(f'<h2 id="m{ci}">{L["summary"]}</h2>')
        parts.append(f"<p>{L['defs'][(ci - 1) * 2][0][1]}{sep}{L['defs'][(ci - 1) * 2 + 1][0][1]}</p>")
        parts.append(f'<h2 id="e{ci}">{L["exercises"]}</h2>')
        for n, q in enumerate(L["exercise_items"], start=1):
            parts.append(f"<p>{n}. {q}</p>")
    direction = ' dir="rtl"' if L["rtl"] else ""
    body = f'<body{direction}><h1 id="t0">{L["title"]}</h1>' + "".join(parts) + "</body>"
    return body, truth


def build(out: Path, lang: str) -> dict:
    L = LANGS[lang]
    html, truth = book_html(L)
    story = pymupdf.Story(html=html, user_css=CSS)
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    mediabox = pymupdf.paper_rect("a4")
    where = mediabox + (60, 60, -60, -70)
    toc_raw: list[tuple[int, str, str, int]] = []
    pno = 0

    def recorder(pos):
        if pos.open_close & 1 and pos.heading in (1, 2) and pos.id and pos.id != "t0":
            toc_raw.append((pos.heading, pos.text, pos.id, pos.page))

    more = True
    while more:
        device = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.element_positions(recorder, {"page": pno})
        story.draw(device)
        writer.end_page()
        pno += 1
    writer.close()
    doc = pymupdf.open("pdf", buf.getvalue())
    for page in doc:                                   # printed page numbers and a running header
        if page.number == 0:
            continue
        page.insert_text((mediabox.width / 2 - 6, mediabox.height - 30), str(page.number), fontsize=9)
    toc, seen = [], set()
    for level, text, ident, page_no in toc_raw:
        if ident in seen:
            continue
        seen.add(ident)
        title = text.strip()
        if level == 1:
            n = int(ident[1:])
            title = f"{L['chapter'].format(n=n)} {title}"
        toc.append([level, title, page_no + 1])
    doc.set_toc(toc)
    doc.set_metadata({"title": L["title"]})
    doc.save(str(out), garbage=3, deflate=True)
    doc.close()
    truth.update(lang=lang, pages=pno, toc=toc)
    Path(str(out) + ".truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
    return truth


if __name__ == "__main__":
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "lang-books")
    folder.mkdir(parents=True, exist_ok=True)
    for lang in (sys.argv[2:] or list(LANGS)):
        t = build(folder / f"book-{lang}.pdf", lang)
        print(f"{lang}: {t['pages']} pages, {len(t['toc'])} TOC entries")
