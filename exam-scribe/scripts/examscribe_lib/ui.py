"""The words of the study pages in the student's language (the notes language).

Notes are written in the student's language; the pages around them (buttons, labels, instructions, the study plan)
use this table. Languages: Chinese, Japanese, Korean, German, French, Spanish, Russian; anything else falls back to
English. To add a language, add a column to every row (or leave rows out: they stay English).

    from .ui import T, use_language
    use_language(ws)                 # once per page build
    T("Key term")                    # -> "关键术语" for Chinese notes
    T("What is {term}?", term=x)     # placeholders stay as they are in every language
"""
from __future__ import annotations

import json
import re

LANGS = ("zh", "ja", "ko", "de", "fr", "es", "ru")
_LANG = ["en"]

# English: (zh, ja, ko, de, fr, es, ru)
TEXT: dict[str, tuple[str, ...]] = {
    # page frame and trust marks
    "Course overview": ("课程概览", "コース概要", "과정 개요", "Kursübersicht", "Vue d'ensemble du cours",
                        "Resumen del curso", "Обзор курса"),
    "⌂ Course": ("⌂ 课程", "⌂ コース", "⌂ 과정", "⌂ Kurs", "⌂ Cours", "⌂ Curso", "⌂ Курс"),
    "Study mode": ("学习模式", "学習モード", "학습 모드", "Lernmodus", "Mode d'étude", "Modo de estudio", "Режим занятий"),
    "Read": ("阅读", "読む", "읽기", "Lesen", "Lire", "Leer", "Чтение"),
    "Recall": ("回忆", "思い出す", "회상", "Abrufen", "Rappel", "Recordar", "Вспомнить"),
    "Light/dark": ("浅色/深色", "ライト/ダーク", "라이트/다크", "Hell/Dunkel", "Clair/sombre", "Claro/oscuro",
                   "Светлая/тёмная"),
    "verified against the book": ("已对照课本核实", "本と照合済み", "책과 대조해 확인됨", "mit dem Buch abgeglichen",
                                  "vérifié dans le livre", "verificado con el libro", "сверено с книгой"),
    "check this": ("请核对", "要確認", "확인 필요", "bitte prüfen", "à vérifier", "por comprobar", "проверьте"),
    "not verified yet": ("尚未核实", "未確認", "아직 확인 안 됨", "noch nicht geprüft", "pas encore vérifié",
                         "aún no verificado", "ещё не проверено"),
    "AI-added, not from the book": ("AI 补充，非课本内容", "AIによる追加（本の内容ではない）", "AI가 추가함, 책 내용 아님",
                                    "von der KI ergänzt, nicht aus dem Buch", "ajouté par l'IA, pas dans le livre",
                                    "añadido por la IA, no está en el libro", "добавлено ИИ, не из книги"),
    "check this (hover for why)": ("请核对（悬停查看原因）", "要確認（マウスを重ねると理由を表示）", "확인 필요(마우스를 올리면 이유 표시)",
                                   "bitte prüfen (Grund beim Darüberfahren)", "à vérifier (survolez pour voir pourquoi)",
                                   "por comprobar (pasa el ratón para ver por qué)",
                                   "проверьте (наведите курсор, чтобы узнать почему)"),
    "AI-added memory aid, not from the book": ("AI 补充的记忆提示，非课本内容", "AIによる覚え方（本の内容ではない）",
                                               "AI가 추가한 암기 도움말, 책 내용 아님", "Merkhilfe der KI, nicht aus dem Buch",
                                               "aide-mémoire ajoutée par l'IA, pas dans le livre",
                                               "truco para recordar añadido por la IA, no está en el libro",
                                               "подсказка для запоминания от ИИ, не из книги"),
    "book page (hover for the quote)": ("课本页码（悬停查看原文）", "本のページ（マウスを重ねると引用を表示）",
                                        "책 페이지(마우스를 올리면 인용문 표시)", "Buchseite (Zitat beim Darüberfahren)",
                                        "page du livre (survolez pour la citation)",
                                        "página del libro (pasa el ratón para ver la cita)",
                                        "страница книги (наведите курсор, чтобы увидеть цитату)"),
    "priority {n} of 3": ("优先级 {n}/3", "優先度 {n}/3", "우선순위 {n}/3", "Priorität {n} von 3", "priorité {n} sur 3",
                          "prioridad {n} de 3", "приоритет {n} из 3"),
    # field labels
    "Not in the book (writer marked it UNSURE: {reason})": (
        "课本中没有（编写时标为不确定：{reason}）", "本に記載なし（作成時に「不確か」と記録：{reason}）",
        "책에 없음(작성자가 '불확실'로 표시: {reason})", "Steht nicht im Buch (als UNSICHER markiert: {reason})",
        "Absent du livre (marqué INCERTAIN : {reason})", "No está en el libro (marcado como NO SEGURO: {reason})",
        "Нет в книге (помечено как НЕ УВЕРЕН: {reason})"),
    "Common mistake": ("常见错误", "よくある間違い", "흔한 실수", "Häufiger Fehler", "Erreur fréquente", "Error frecuente",
                       "Частая ошибка"),
    "Translation": ("翻译", "訳", "번역", "Übersetzung", "Traduction", "Traducción", "Перевод"),
    "In plain words": ("通俗解释", "わかりやすく言うと", "쉽게 말하면", "Einfach gesagt", "En termes simples",
                       "En palabras sencillas", "Простыми словами"),
    "Why it matters": ("为什么重要", "なぜ重要か", "왜 중요한가", "Warum es wichtig ist", "Pourquoi c'est important",
                       "Por qué importa", "Почему это важно"),
    "Example": ("例子", "例", "예", "Beispiel", "Exemple", "Ejemplo", "Пример"),
    "Symbols": ("符号含义", "記号", "기호", "Symbole", "Symboles", "Símbolos", "Обозначения"),
    "Holds when": ("适用条件", "成り立つ条件", "성립 조건", "Gilt, wenn", "Valable si", "Se cumple cuando",
                   "Справедливо, когда"),
    "Source": ("出处", "出典", "출처", "Quelle", "Source", "Fuente", "Источник"),
    "Problem": ("题目", "問題", "문제", "Aufgabe", "Problème", "Problema", "Задача"),
    "Answer": ("答案", "答え", "답", "Antwort", "Réponse", "Respuesta", "Ответ"),
    "What it shows": ("图示内容", "何を示すか", "무엇을 보여 주나", "Was es zeigt", "Ce que cela montre", "Qué muestra",
                      "Что показано"),
    "Look for": ("注意看", "注目点", "살펴볼 점", "Achte auf", "À repérer", "Fíjate en", "Обратите внимание"),
    "Why": ("原因", "理由", "이유", "Warum", "Pourquoi", "Por qué", "Почему"),
    "Output": ("输出", "出力", "출력", "Ausgabe", "Sortie", "Salida", "Вывод"),
    "Step": ("步骤", "手順", "단계", "Schritt", "Étape", "Paso", "Шаг"),
    "Event": ("事件", "出来事", "사건", "Ereignis", "Événement", "Acontecimiento", "Событие"),
    "Cause → effect": ("原因 → 结果", "原因 → 結果", "원인 → 결과", "Ursache → Wirkung", "Cause → effet",
                       "Causa → efecto", "Причина → следствие"),
    "Rule": ("规则", "規則", "규칙", "Regel", "Règle", "Regla", "Правило"),
    "Element": ("要件", "要件", "요건", "Merkmal", "Élément", "Elemento", "Элемент"),
    "Exception": ("例外", "例外", "예외", "Ausnahme", "Exception", "Excepción", "Исключение"),
    "Case": ("案例", "事例", "사례", "Fall", "Cas", "Caso", "Случай"),
    "Thesis": ("论点", "主張", "논지", "These", "Thèse", "Tesis", "Тезис"),
    "Point": ("论据", "論拠", "논거", "Argument", "Argument", "Argumento", "Довод"),
    "Counterpoint": ("反方观点", "反論", "반론", "Gegenargument", "Contre-argument", "Contraargumento", "Контраргумент"),
    "This chapter answers": ("本章回答", "この章が答える問い", "이 장이 답하는 질문", "Dieses Kapitel beantwortet",
                             "Ce chapitre répond à", "Este capítulo responde", "Глава отвечает на вопросы"),
    "Where it fits": ("在课程中的位置", "全体の中での位置", "전체에서의 위치", "Einordnung", "Place dans le cours",
                      "Dónde encaja", "Место в курсе"),
    "Memory aid": ("记忆提示", "覚え方", "암기 도움말", "Merkhilfe", "Aide-mémoire", "Truco para recordar",
                   "Подсказка для запоминания"),
    "Analogy": ("类比", "たとえ", "비유", "Vergleich", "Analogie", "Analogía", "Аналогия"),
    "Exam tip": ("考试提示", "試験のコツ", "시험 팁", "Prüfungstipp", "Conseil pour l'examen", "Consejo para el examen",
                 "Совет к экзамену"),
    "Extra example": ("补充例子", "追加の例", "추가 예", "Zusatzbeispiel", "Exemple supplémentaire", "Ejemplo adicional",
                      "Дополнительный пример"),
    # cards
    "What is {term}?": ("什么是{term}？", "{term}とは？", "{term}(이)란?", "Was ist {term}?", "Qu'est-ce que {term} ?",
                        "¿Qué es {term}?", "Что такое {term}?"),
    "Key term": ("关键术语", "キーワード", "핵심 용어", "Schlüsselbegriff", "Terme clé", "Término clave", "Ключевой термин"),
    "Recall:": ("回忆：", "思い出す：", "회상:", "Abrufen:", "Rappel :", "Recuerda:", "Вспомните:"),
    "Say the answer out loud, then click the blurred text to check.": (
        "先说出答案，再点击模糊的文字核对。", "答えを声に出してから、ぼかした部分をクリックして確認しましょう。",
        "답을 소리 내어 말한 뒤 흐린 글자를 눌러 확인하세요.",
        "Sag die Antwort laut und klick dann auf den unscharfen Text, um zu prüfen.",
        "Dites la réponse à voix haute, puis cliquez sur le texte flou pour vérifier.",
        "Di la respuesta en voz alta y luego haz clic en el texto borroso para comprobarla.",
        "Произнесите ответ вслух, затем нажмите на размытый текст, чтобы проверить."),
    "The writer could not find the book’s definition (UNSURE).": (
        "编写时未找到课本中的定义（不确定）。", "本の定義が見つかりませんでした（不確か）。", "책의 정의를 찾지 못했습니다(불확실).",
        "Die Definition aus dem Buch wurde nicht gefunden (UNSICHER).",
        "La définition du livre n'a pas été trouvée (INCERTAIN).", "No se encontró la definición del libro (NO SEGURO).",
        "Определение из книги не найдено (НЕ УВЕРЕН)."),
    "uses different notation": ("使用了不同的符号", "別の表記を使っています", "다른 표기를 씁니다",
                                "verwendet eine andere Schreibweise", "utilise une autre notation", "usa otra notación",
                                "использует другие обозначения"),
    "says something different": ("说法不同", "異なる内容です", "다르게 말합니다", "sagt etwas anderes", "dit autre chose",
                                 "dice algo distinto", "говорит иначе"),
    "Your instructor’s material ({material}) {what}:": (
        "老师的材料（{material}）{what}：", "先生の資料（{material}）は{what}：", "강사 자료({material})는 {what}:",
        "Das Material deiner Lehrkraft ({material}) {what}:", "Le support de votre enseignant ({material}) {what} :",
        "El material de tu profesor ({material}) {what}:", "Материал вашего преподавателя ({material}) {what}:"),
    "For the exam, follow your instructor.": (
        "考试时以老师的说法为准。", "試験では先生の説明に従ってください。", "시험에서는 강사의 설명을 따르세요.",
        "Halte dich in der Prüfung an deine Lehrkraft.", "Pour l'examen, suivez votre enseignant.",
        "En el examen, sigue a tu profesor.", "На экзамене следуйте преподавателю."),
    "Formula": ("公式", "公式", "공식", "Formel", "Formule", "Fórmula", "Формула"),
    "formula as printed in the book": ("课本中印刷的公式", "本に印刷された式", "책에 인쇄된 공식", "Formel, wie sie im Buch steht",
                                       "formule telle qu'imprimée dans le livre", "fórmula tal como aparece en el libro",
                                       "формула, как в книге"),
    "Recall: write the formula and say when it holds.": (
        "回忆：写出公式，并说出它的适用条件。", "思い出す：式を書き、成り立つ条件を言いましょう。", "회상: 공식을 쓰고 성립 조건을 말해 보세요.",
        "Abrufen: Schreib die Formel auf und sag, wann sie gilt.",
        "Rappel : écrivez la formule et dites quand elle s'applique.",
        "Recuerda: escribe la fórmula y di cuándo se cumple.", "Вспомните: запишите формулу и скажите, когда она верна."),
    "Click the blurred text to check.": ("点击模糊的文字核对。", "ぼかした部分をクリックして確認しましょう。", "흐린 글자를 눌러 확인하세요.",
                                         "Klick auf den unscharfen Text, um zu prüfen.",
                                         "Cliquez sur le texte flou pour vérifier.",
                                         "Haz clic en el texto borroso para comprobarlo.",
                                         "Нажмите на размытый текст, чтобы проверить."),
    "As printed": ("课本原样", "本の表記", "책에 실린 그대로", "Wie gedruckt", "Tel qu'imprimé", "Tal como está impreso",
                   "Как в книге"),
    "Forms (checked by script)": ("变形式（脚本已验算）", "変形（スクリプトで検算済み）", "변형식(스크립트로 검산함)",
                                  "Umformungen (vom Skript geprüft)", "Formes (vérifiées par le script)",
                                  "Formas (comprobadas por el script)", "Формы (проверены скриптом)"),
    "Calculation": ("计算", "計算", "계산", "Rechnung", "Calcul", "Cálculo", "Вычисление"),
    "Result (recomputed by the script ✓)": ("结果（脚本已重新计算 ✓）", "結果（スクリプトで再計算 ✓）", "결과(스크립트로 다시 계산 ✓)",
                                            "Ergebnis (vom Skript nachgerechnet ✓)", "Résultat (recalculé par le script ✓)",
                                            "Resultado (recalculado por el script ✓)", "Результат (пересчитан скриптом ✓)"),
    "Worked example": ("例题", "例題", "예제", "Musterbeispiel", "Exemple résolu", "Ejemplo resuelto", "Разобранный пример"),
    "Your turn": ("轮到你了", "やってみよう", "직접 해 보기", "Jetzt du", "À vous", "Tu turno", "Ваша очередь"),
    "Finish it yourself": ("自己完成剩下的步骤", "残りを自分で解こう", "나머지를 스스로 풀어 보세요", "Rechne den Rest selbst",
                           "Terminez vous-même", "Termínalo tú", "Закончите сами"),
    "Same problem: the first steps are given. Work out the rest on paper, then check.": (
        "同一道题：已给出前几步。请在纸上完成其余步骤，然后核对。",
        "同じ問題です。最初の手順は示してあります。残りを紙に書いて解き、確認しましょう。",
        "같은 문제입니다. 처음 몇 단계는 주어져 있습니다. 나머지를 종이에 풀고 확인하세요.",
        "Dieselbe Aufgabe: Die ersten Schritte sind vorgegeben. Rechne den Rest auf Papier und prüfe dann.",
        "Même problème : les premières étapes sont données. Faites le reste sur papier, puis vérifiez.",
        "El mismo problema: los primeros pasos están dados. Resuelve el resto en papel y luego comprueba.",
        "Та же задача: первые шаги даны. Решите остальное на бумаге, затем проверьте."),
    "Show the remaining steps": ("显示其余步骤", "残りの手順を表示", "나머지 단계 보기", "Restliche Schritte zeigen",
                                 "Afficher les étapes restantes", "Mostrar los pasos restantes", "Показать остальные шаги"),
    "Table": ("表", "表", "표", "Tabelle", "Tableau", "Tabla", "Таблица"),
    "Figure": ("图", "図", "그림", "Abbildung", "Figure", "Figura", "Рисунок"),
    "Trace the code": ("跟踪代码", "コードを追う", "코드 따라가기", "Code nachverfolgen", "Suivre le code", "Sigue el código",
                       "Проследите код"),
    "Don’t mix these up": ("不要混淆", "混同しないで", "헷갈리지 마세요", "Nicht verwechseln", "À ne pas confondre",
                           "No los confundas", "Не путайте"),
    "Concept map": ("概念图", "概念マップ", "개념 지도", "Begriffslandkarte", "Carte conceptuelle", "Mapa conceptual",
                    "Карта понятий"),
    "How the ideas connect": ("各概念之间的联系", "考えどうしのつながり", "개념들의 연결", "Wie die Ideen zusammenhängen",
                              "Comment les idées se relient", "Cómo se conectan las ideas", "Как связаны идеи"),
    "(AI-drawn; every arrow is a cited claim)": (
        "（AI 绘制；每个箭头都有课本出处）", "（AIが作図。どの矢印も本の引用付き）", "(AI가 그림, 모든 화살표에 인용 근거 있음)",
        "(von der KI gezeichnet; jeder Pfeil ist eine belegte Aussage)",
        "(dessiné par l'IA ; chaque flèche est une affirmation citée)",
        "(dibujado por la IA; cada flecha es una afirmación citada)",
        "(нарисовано ИИ; каждая стрелка — утверждение со ссылкой)"),
    # questions
    "True": ("对", "正しい", "참", "Wahr", "Vrai", "Verdadero", "Верно"),
    "False": ("错", "誤り", "거짓", "Falsch", "Faux", "Falso", "Неверно"),
    "Your answer": ("你的答案", "あなたの答え", "내 답", "Deine Antwort", "Votre réponse", "Tu respuesta", "Ваш ответ"),
    "Check": ("核对", "確認", "확인", "Prüfen", "Vérifier", "Comprobar", "Проверить"),
    "Missing words": ("缺少的词", "空欄の語", "빈칸의 말", "Fehlende Wörter", "Mots manquants", "Palabras que faltan",
                      "Пропущенные слова"),
    "Show model answer": ("显示参考答案", "模範解答を表示", "모범 답안 보기", "Musterantwort zeigen",
                          "Afficher la réponse modèle", "Mostrar la respuesta modelo", "Показать образец ответа"),
    "I got it": ("我答对了", "できた", "맞혔어요", "Gewusst", "J'ai trouvé", "Lo sabía", "Знал(а)"),
    "I missed it": ("我答错了", "できなかった", "틀렸어요", "Nicht gewusst", "Je me suis trompé", "No lo sabía", "Не знал(а)"),
    "{letter} is wrong:": ("{letter} 错在：", "{letter} が誤りの理由：", "{letter}가 틀린 이유:", "{letter} ist falsch:",
                           "{letter} est faux :", "{letter} es incorrecta:", "{letter} неверно:"),
    "Answer:": ("答案：", "答え：", "답:", "Antwort:", "Réponse :", "Respuesta:", "Ответ:"),
    # chapter page
    "Chapter {n} · book pages {a}–{b} · needs: {needs} · used by: {used}": (
        "第{n}章 · 课本第{a}–{b}页 · 前置：{needs} · 后续：{used}",
        "第{n}章 · 本の{a}–{b}ページ · 前提：{needs} · 後で使う章：{used}",
        "제{n}장 · 책 {a}–{b}쪽 · 선행: {needs} · 후속: {used}",
        "Kapitel {n} · Buchseiten {a}–{b} · setzt voraus: {needs} · gebraucht in: {used}",
        "Chapitre {n} · pages {a}–{b} du livre · prérequis : {needs} · utilisé dans : {used}",
        "Capítulo {n} · páginas {a}–{b} del libro · requiere: {needs} · se usa en: {used}",
        "Глава {n} · страницы книги {a}–{b} · опирается на: {needs} · нужна для: {used}"),
    "nothing earlier": ("无", "なし", "없음", "nichts Früheres", "rien d'antérieur", "nada anterior", "ничего"),
    "no later chapter": ("无", "なし", "없음", "kein späteres Kapitel", "aucun chapitre suivant", "ningún capítulo posterior",
                         "ни одной следующей главы"),
    "{ok} claims verified · {warn} to check · {pending} not yet verified": (
        "已核实 {ok} 条 · 待核对 {warn} 条 · 未核实 {pending} 条", "確認済み {ok} 件 · 要確認 {warn} 件 · 未確認 {pending} 件",
        "확인됨 {ok}개 · 확인 필요 {warn}개 · 미확인 {pending}개",
        "{ok} Aussagen geprüft · {warn} zu prüfen · {pending} noch nicht geprüft",
        "{ok} affirmations vérifiées · {warn} à vérifier · {pending} pas encore vérifiées",
        "{ok} afirmaciones verificadas · {warn} por comprobar · {pending} aún sin verificar",
        "проверено утверждений: {ok} · проверить: {warn} · ещё не проверено: {pending}"),
    "Pretest": ("课前小测", "事前テスト", "사전 테스트", "Vortest", "Prétest", "Prueba previa", "Предварительный тест"),
    "Connections": ("知识联系", "つながり", "연결", "Zusammenhänge", "Liens", "Conexiones", "Связи"),
    "Must know": ("必须掌握", "必修事項", "꼭 알아야 할 것", "Muss man wissen", "À savoir absolument", "Imprescindible",
                  "Обязательно знать"),
    "Self-test": ("自测", "セルフテスト", "자가 테스트", "Selbsttest", "Autotest", "Autoevaluación", "Самопроверка"),
    "Review sheet": ("复习表", "復習シート", "복습지", "Wiederholungsbogen", "Fiche de révision", "Hoja de repaso",
                     "Лист повторения"),
    "Big picture": ("全局概览", "全体像", "큰 그림", "Überblick", "Vue d'ensemble", "Panorama general", "Общая картина"),
    "Try these before reading. Guessing wrong is fine: it makes the answer stick when you meet it below. You will see "
    "them again in the self-test.": (
        "先试着做这几道题再阅读。猜错也没关系：这样在下文遇到答案时会记得更牢。自测中还会再出现。",
        "読む前に解いてみましょう。間違えても大丈夫です。後で答えに出会ったときに記憶に残りやすくなります。セルフテストでもう一度出題されます。",
        "읽기 전에 풀어 보세요. 틀려도 괜찮습니다. 아래에서 답을 만났을 때 더 오래 기억됩니다. 자가 테스트에서 다시 나옵니다.",
        "Versuch dich daran, bevor du liest. Falsch raten ist in Ordnung: So bleibt die Antwort besser hängen, wenn du "
        "sie unten triffst. Im Selbsttest kommen sie wieder.",
        "Essayez-les avant de lire. Se tromper n'est pas grave : la réponse se retient mieux quand vous la rencontrez "
        "plus bas. Vous les reverrez dans l'autotest.",
        "Inténtalas antes de leer. Equivocarse está bien: la respuesta se recuerda mejor cuando la encuentras más abajo. "
        "Volverán a aparecer en la autoevaluación.",
        "Попробуйте ответить до чтения. Ошибаться не страшно: так ответ лучше запомнится, когда вы встретите его ниже. "
        "Эти вопросы будут и в самопроверке."),
    "Priority because: {reasons}": ("优先原因：{reasons}", "優先する理由：{reasons}", "우선순위 이유: {reasons}",
                                    "Priorität, weil: {reasons}", "Prioritaire car : {reasons}",
                                    "Prioridad porque: {reasons}", "Приоритет, потому что: {reasons}"),
    "After this section you should be able to:": (
        "学完本节后，你应该能够：", "この節を終えたら、次のことができるはずです：", "이 절을 마치면 다음을 할 수 있어야 합니다:",
        "Nach diesem Abschnitt solltest du Folgendes können:", "Après cette section, vous devriez savoir :",
        "Después de esta sección deberías poder:", "После этого раздела вы должны уметь:"),
    "Process": ("过程", "プロセス", "과정", "Ablauf", "Processus", "Proceso", "Процесс"),
    "Timeline": ("时间线", "年表", "연표", "Zeitleiste", "Chronologie", "Cronología", "Хронология"),
    "Cause and effect": ("因果关系", "因果関係", "인과 관계", "Ursache und Wirkung", "Cause et effet", "Causa y efecto",
                         "Причина и следствие"),
    "Problem-solving": ("解题思路", "解き方", "문제 풀이", "Lösungsstrategie", "Résolution de problèmes",
                        "Resolución de problemas", "Решение задач"),
    "When you see … do …": ("看到……就……", "……を見たら……する", "…를 보면 …를 하세요", "Wenn du … siehst, mach …",
                            "Quand vous voyez …, faites …", "Cuando veas …, haz …", "Видите … — делайте …"),
    "Essay outline": ("论述题提纲", "論述の構成", "논술 개요", "Gliederung für Aufsätze", "Plan de dissertation",
                      "Esquema de ensayo", "План эссе"),
    "Checked against the book’s own chapter summary.": (
        "已对照课本的本章小结核对。", "本の章末まとめと照合済み。", "책의 장 요약과 대조함.",
        "Mit der Kapitelzusammenfassung des Buchs abgeglichen.", "Vérifié avec le résumé du chapitre dans le livre.",
        "Comprobado con el resumen del capítulo del libro.", "Сверено с итогами главы в книге."),
    "From recall to analysis. Answers were confirmed by an independent solver unless marked otherwise.": (
        "从记忆到分析。除非另有标注，答案均经过独立解答核实。", "記憶から分析まで。特に示さない限り、答えは独立した解答で確認済みです。",
        "기억에서 분석까지. 따로 표시하지 않은 답은 독립적으로 다시 풀어 확인했습니다.",
        "Vom Erinnern zum Analysieren. Die Antworten wurden unabhängig nachgelöst, sofern nicht anders markiert.",
        "Du rappel à l'analyse. Les réponses ont été confirmées par une résolution indépendante, sauf indication "
        "contraire.",
        "Del recuerdo al análisis. Las respuestas se confirmaron con una resolución independiente salvo que se indique "
        "lo contrario.",
        "От запоминания к анализу. Ответы подтверждены независимым решением, если не указано иное."),
    "Export my results": ("导出我的成绩", "結果をエクスポート", "내 결과 내보내기", "Meine Ergebnisse exportieren",
                          "Exporter mes résultats", "Exportar mis resultados", "Экспортировать результаты"),
    "Remember": ("记忆", "記憶", "기억", "Erinnern", "Se souvenir", "Recordar", "Запоминание"),
    "Understand": ("理解", "理解", "이해", "Verstehen", "Comprendre", "Comprender", "Понимание"),
    "Apply": ("应用", "応用", "적용", "Anwenden", "Appliquer", "Aplicar", "Применение"),
    "Analyze": ("分析", "分析", "분석", "Analysieren", "Analyser", "Analizar", "Анализ"),
    "Evaluate": ("评价", "評価", "평가", "Bewerten", "Évaluer", "Evaluar", "Оценка"),
    "Other": ("其他", "その他", "기타", "Sonstiges", "Autres", "Otras", "Прочее"),
    "Book pages cited in these notes: {pages}": (
        "本笔记引用的课本页码：{pages}", "このノートで引用した本のページ：{pages}", "이 노트에서 인용한 책 페이지: {pages}",
        "In diesen Notizen zitierte Buchseiten: {pages}", "Pages du livre citées dans ces notes : {pages}",
        "Páginas del libro citadas en estas notas: {pages}", "Страницы книги, процитированные в заметках: {pages}"),
    "{title} — notes": ("{title} — 笔记", "{title} — ノート", "{title} — 노트", "{title} — Notizen", "{title} — notes",
                        "{title} — apuntes", "{title} — заметки"),
    # review sheet
    "True or false: {s}": ("判断对错：{s}", "正しいか誤りか：{s}", "참 또는 거짓: {s}", "Wahr oder falsch: {s}",
                           "Vrai ou faux : {s}", "¿Verdadero o falso?: {s}", "Верно или нет: {s}"),
    "False.": ("错。", "誤り。", "거짓.", "Falsch.", "Faux.", "Falso.", "Неверно."),
    "Formula: {name}": ("公式：{name}", "公式：{name}", "공식: {name}", "Formel: {name}", "Formule : {name}",
                        "Fórmula: {name}", "Формула: {name}"),
    "Review sheet — {title}": ("复习表 — {title}", "復習シート — {title}", "복습지 — {title}", "Wiederholungsbogen — {title}",
                               "Fiche de révision — {title}", "Hoja de repaso — {title}", "Лист повторения — {title}"),
    "Cover the right column, answer from memory, then check. Recall mode blurs the answers for you.": (
        "盖住右栏，凭记忆作答，然后核对。回忆模式会自动模糊答案。",
        "右の列を隠し、記憶から答えてから確認しましょう。思い出すモードでは答えがぼかされます。",
        "오른쪽 열을 가리고 기억으로 답한 뒤 확인하세요. 회상 모드에서는 답이 흐리게 표시됩니다.",
        "Deck die rechte Spalte ab, antworte aus dem Gedächtnis und prüfe dann. Im Abrufmodus werden die Antworten "
        "unscharf.",
        "Cachez la colonne de droite, répondez de mémoire, puis vérifiez. Le mode rappel floute les réponses pour vous.",
        "Tapa la columna derecha, responde de memoria y luego comprueba. El modo recordar difumina las respuestas.",
        "Закройте правую колонку, ответьте по памяти, затем проверьте. В режиме «Вспомнить» ответы размыты."),
    "Hide all answers again": ("重新隐藏全部答案", "すべての答えを再び隠す", "모든 답 다시 가리기", "Alle Antworten wieder verbergen",
                               "Masquer à nouveau toutes les réponses", "Volver a ocultar todas las respuestas",
                               "Снова скрыть все ответы"),
    "Cue": ("提示", "手がかり", "단서", "Stichwort", "Indice", "Pista", "Подсказка"),
    "Review — {title}": ("复习 — {title}", "復習 — {title}", "복습 — {title}", "Wiederholung — {title}", "Révision — {title}",
                         "Repaso — {title}", "Повторение — {title}"),
    "Review · {title}": ("复习 · {title}", "復習 · {title}", "복습 · {title}", "Wiederholung · {title}", "Révision · {title}",
                         "Repaso · {title}", "Повторение · {title}"),
    # quizzes and practice pages
    "Start the timer ({m} min)": ("开始计时（{m} 分钟）", "タイマー開始（{m}分）", "타이머 시작({m}분)", "Timer starten ({m} Min.)",
                                  "Lancer le chrono ({m} min)", "Iniciar el temporizador ({m} min)",
                                  "Запустить таймер ({m} мин)"),
    "Finish and show answers": ("交卷并显示答案", "終了して答えを表示", "마치고 답 보기", "Beenden und Antworten zeigen",
                                "Terminer et afficher les réponses", "Terminar y mostrar las respuestas",
                                "Завершить и показать ответы"),
    "Mixed practice {k}": ("综合练习 {k}", "ミックス演習 {k}", "혼합 연습 {k}", "Gemischte Übung {k}",
                           "Entraînement mixte {k}", "Práctica mixta {k}", "Смешанная практика {k}"),
    "For {date}. Questions from {chapters}, mixed on purpose: deciding which idea applies is part of the practice.": (
        "用于 {date}。题目来自 {chapters}，有意混排：判断该用哪个知识点也是练习的一部分。",
        "{date}用。{chapters}からの問題を意図的に混ぜています。どの考え方を使うかを判断することも練習のうちです。",
        "{date}용. {chapters}에서 낸 문제를 일부러 섞었습니다. 어떤 개념을 쓸지 판단하는 것도 연습입니다.",
        "Für {date}. Fragen aus {chapters}, absichtlich gemischt: Zu erkennen, welche Idee passt, gehört zur Übung.",
        "Pour le {date}. Questions de {chapters}, mélangées exprès : savoir quelle idée s'applique fait partie de "
        "l'entraînement.",
        "Para el {date}. Preguntas de {chapters}, mezcladas a propósito: decidir qué idea aplica es parte de la práctica.",
        "На {date}. Вопросы из {chapters} намеренно перемешаны: понять, какая идея здесь нужна, — часть тренировки."),
    "Mock exam": ("模拟考试", "模擬試験", "모의고사", "Probeklausur", "Examen blanc", "Simulacro de examen",
                  "Пробный экзамен"),
    "{n} questions, {m} minutes, answers shown only when you finish. Work under exam conditions: no notes.": (
        "共 {n} 题，{m} 分钟，交卷后才显示答案。请按考试条件作答：不看笔记。",
        "全{n}問、{m}分。答えは終了後にだけ表示されます。試験と同じ条件で、ノートを見ずに解きましょう。",
        "{n}문제, {m}분. 답은 마친 뒤에만 보입니다. 시험과 같은 조건으로 노트 없이 푸세요.",
        "{n} Fragen, {m} Minuten, Antworten erst am Ende. Unter Prüfungsbedingungen arbeiten: keine Notizen.",
        "{n} questions, {m} minutes, réponses affichées seulement à la fin. Travaillez en conditions d'examen : sans "
        "notes.",
        "{n} preguntas, {m} minutos; las respuestas se muestran solo al terminar. Trabaja en condiciones de examen: sin "
        "apuntes.",
        "Вопросов: {n}, минут: {m}, ответы — только в конце. Работайте как на экзамене: без записей."),
    "Cheat sheet": ("速查表", "チートシート", "요점 정리표", "Spickzettel", "Antisèche", "Chuleta", "Шпаргалка"),
    "Only verified formulas, must-know facts and comparisons. Read it the day before the exam; the most important "
    "items come first in each chapter.": (
        "只包含已核实的公式、必须掌握的要点和对比。请在考前一天阅读；每章最重要的内容排在最前。",
        "確認済みの公式・必修事項・比較だけを載せています。試験の前日に読みましょう。各章で最も重要な項目が先頭です。",
        "확인된 공식, 꼭 알아야 할 사실, 비교만 담았습니다. 시험 전날 읽으세요. 장마다 가장 중요한 항목이 먼저 나옵니다.",
        "Nur geprüfte Formeln, Muss-man-wissen-Fakten und Vergleiche. Lies es am Tag vor der Prüfung; das Wichtigste "
        "steht in jedem Kapitel zuerst.",
        "Uniquement des formules, faits essentiels et comparaisons vérifiés. Lisez-la la veille de l'examen ; les "
        "éléments les plus importants viennent en premier dans chaque chapitre.",
        "Solo fórmulas, datos imprescindibles y comparaciones verificados. Léela el día antes del examen; lo más "
        "importante va primero en cada capítulo.",
        "Только проверенные формулы, обязательные факты и сравнения. Прочитайте накануне экзамена; самое важное в "
        "каждой главе идёт первым."),
    "Your exam allows one sheet of notes: print this, then rewrite it by hand in your own words.": (
        "你的考试允许带一页笔记：先打印这一页，再用自己的话手写一遍。",
        "試験にはメモ1枚の持ち込みが認められています。これを印刷し、自分の言葉で手書きし直しましょう。",
        "시험에 메모 한 장을 가져갈 수 있습니다. 이것을 인쇄한 뒤 자기 말로 손글씨로 다시 쓰세요.",
        "Deine Prüfung erlaubt einen Notizzettel: Druck dies aus und schreib es dann mit eigenen Worten von Hand neu.",
        "Votre examen autorise une feuille de notes : imprimez ceci, puis réécrivez-le à la main avec vos mots.",
        "Tu examen permite una hoja de apuntes: imprime esto y luego reescríbelo a mano con tus palabras.",
        "На экзамене разрешён один лист записей: распечатайте это и перепишите от руки своими словами."),
    "Traps": ("易错点", "落とし穴", "함정", "Fallen", "Pièges", "Trampas", "Ловушки"),
    "Typical mistakes from the notes, plus questions you keep missing. Read the wrong version, then say the right one "
    "out loud.": (
        "笔记中的典型错误，以及你反复做错的题。先读错误的说法，再大声说出正确的说法。",
        "ノートにあるよくある間違いと、何度も間違える問題です。誤った説明を読んでから、正しい説明を声に出しましょう。",
        "노트의 흔한 실수와 자주 틀리는 문제입니다. 틀린 설명을 읽고 맞는 설명을 소리 내어 말하세요.",
        "Typische Fehler aus den Notizen und Fragen, die du immer wieder falsch beantwortest. Lies die falsche Version "
        "und sag dann die richtige laut.",
        "Erreurs typiques tirées des notes et questions que vous ratez souvent. Lisez la version fausse, puis dites la "
        "bonne à voix haute.",
        "Errores típicos de los apuntes y preguntas que sigues fallando. Lee la versión incorrecta y luego di en voz "
        "alta la correcta.",
        "Типичные ошибки из заметок и вопросы, на которых вы ошибаетесь. Прочитайте неверный вариант, затем вслух "
        "скажите верный."),
    "No traps recorded yet.": ("暂无易错点。", "まだ落とし穴はありません。", "아직 기록된 함정이 없습니다.", "Noch keine Fallen erfasst.",
                               "Aucun piège enregistré pour l'instant.", "Aún no hay trampas registradas.",
                               "Ловушек пока нет."),
    "You missed this {n} times ({qid})": ("你已经答错 {n} 次（{qid}）", "{n}回間違えました（{qid}）", "{n}번 틀렸습니다({qid})",
                                          "{n}-mal falsch beantwortet ({qid})", "Vous l'avez raté {n} fois ({qid})",
                                          "La fallaste {n} veces ({qid})", "Ошибок: {n} ({qid})"),
    "Lookup index": ("查找索引", "索引", "찾아보기", "Nachschlageregister", "Index de recherche", "Índice de consulta",
                     "Указатель"),
    "For open-book exams: find any term fast, in the book and in your notes.": (
        "用于开卷考试：在课本和笔记中快速找到任何术语。", "持ち込み可の試験用：用語を本とノートの中ですばやく探せます。",
        "오픈북 시험용: 어떤 용어든 책과 노트에서 빠르게 찾으세요.",
        "Für Open-Book-Prüfungen: jeden Begriff schnell im Buch und in den Notizen finden.",
        "Pour les examens à livre ouvert : trouvez vite n'importe quel terme, dans le livre et dans vos notes.",
        "Para exámenes a libro abierto: encuentra rápido cualquier término, en el libro y en tus apuntes.",
        "Для экзаменов с открытой книгой: быстро найдите любой термин в книге и в заметках."),
    "Term": ("术语", "用語", "용어", "Begriff", "Terme", "Término", "Термин"),
    "Type": ("类型", "種類", "종류", "Art", "Type", "Tipo", "Тип"),
    "Book": ("课本", "本", "책", "Buch", "Livre", "Libro", "Книга"),
    "Notes": ("笔记", "ノート", "노트", "Notizen", "Notes", "Apuntes", "Заметки"),
    "formula": ("公式", "公式", "공식", "Formel", "formule", "fórmula", "формула"),
    "term": ("术语", "用語", "용어", "Begriff", "terme", "término", "термин"),
    "{c} notes": ("{c} 笔记", "{c} ノート", "{c} 노트", "{c} Notizen", "notes {c}", "apuntes {c}", "заметки {c}"),
    # course index
    "not built yet": ("尚未生成", "未作成", "아직 생성되지 않음", "noch nicht erstellt", "pas encore généré", "aún no generado",
                      "ещё не собрано"),
    "not written yet": ("尚未编写", "未執筆", "아직 작성되지 않음", "noch nicht geschrieben", "pas encore rédigé",
                        "aún no escrito", "ещё не написано"),
    "coming soon": ("即将推出", "準備中", "준비 중", "folgt bald", "bientôt", "próximamente", "скоро"),
    "Due today": ("今日复习", "今日の復習", "오늘 복습", "Heute fällig", "À revoir aujourd'hui", "Para hoy", "На сегодня"),
    "Verification report": ("核实报告", "検証レポート", "검증 보고서", "Prüfbericht", "Rapport de vérification",
                            "Informe de verificación", "Отчёт о проверке"),
    "Mixed practice:": ("综合练习：", "ミックス演習：", "혼합 연습:", "Gemischte Übung:", "Entraînement mixte :",
                        "Práctica mixta:", "Смешанная практика:"),
    "Anki deck": ("Anki 卡组", "Ankiデッキ", "Anki 덱", "Anki-Stapel", "Paquet Anki", "Mazo de Anki", "Колода Anki"),
    "Flashcards (TSV)": ("记忆卡（TSV）", "単語カード（TSV）", "플래시카드(TSV)", "Karteikarten (TSV)", "Cartes mémoire (TSV)",
                         "Tarjetas (TSV)", "Карточки (TSV)"),
    "Calendar (.ics)": ("日历（.ics）", "カレンダー（.ics）", "캘린더(.ics)", "Kalender (.ics)", "Calendrier (.ics)",
                        "Calendario (.ics)", "Календарь (.ics)"),
    "Exam: {date} · formats: {formats} · {policy}": (
        "考试：{date} · 题型：{formats} · {policy}", "試験：{date} · 形式：{formats} · {policy}",
        "시험: {date} · 유형: {formats} · {policy}", "Prüfung: {date} · Formate: {formats} · {policy}",
        "Examen : {date} · formats : {formats} · {policy}", "Examen: {date} · formatos: {formats} · {policy}",
        "Экзамен: {date} · форматы: {formats} · {policy}"),
    "date not set": ("未设定日期", "日付未設定", "날짜 미정", "Datum nicht festgelegt", "date non fixée", "fecha sin fijar",
                     "дата не задана"),
    "closed book": ("闭卷", "持ち込み不可", "오픈북 아님", "ohne Unterlagen", "sans documents", "a libro cerrado",
                    "без материалов"),
    "open book": ("开卷", "持ち込み可", "오픈북", "mit Unterlagen", "avec documents", "a libro abierto",
                  "с открытой книгой"),
    "one cheat sheet allowed": ("允许带一页笔记", "メモ1枚持ち込み可", "메모 한 장 허용", "ein Spickzettel erlaubt",
                                "une feuille de notes autorisée", "se permite una hoja de apuntes",
                                "разрешён один лист записей"),
    "multiple choice": ("选择题", "選択問題", "객관식", "Multiple Choice", "QCM", "opción múltiple",
                        "тест с выбором ответа"),
    "short answer": ("简答题", "短答問題", "단답형", "Kurzantwort", "réponse courte", "respuesta corta", "краткий ответ"),
    "essay": ("论述题", "論述問題", "논술형", "Aufsatz", "dissertation", "ensayo", "эссе"),
    "problems": ("计算题", "計算問題", "계산 문제", "Rechenaufgaben", "problèmes", "problemas", "задачи"),
    "How to use this": ("使用方法", "使い方", "사용 방법", "So benutzt du das", "Mode d'emploi", "Cómo usarlo",
                        "Как этим пользоваться"),
    "Follow the plan below: each day says what to do and for how long.": (
        "按照下面的计划学习：每天都写明了要做什么、做多久。", "下の計画に沿って進めましょう。毎日、何をどれくらいするかが書いてあります。",
        "아래 계획을 따르세요. 날마다 무엇을 얼마나 할지 적혀 있습니다.",
        "Folge dem Plan unten: Jeder Tag sagt, was zu tun ist und wie lange.",
        "Suivez le plan ci-dessous : chaque jour indique quoi faire et combien de temps.",
        "Sigue el plan de abajo: cada día dice qué hacer y durante cuánto tiempo.",
        "Следуйте плану ниже: на каждый день указано, что делать и сколько."),
    "New chapter: take the pretest, read the notes, then do the self-test in {recall} mode.": (
        "新的一章：先做课前小测，再读笔记，然后在{recall}模式下做自测。",
        "新しい章：事前テストを受け、ノートを読み、{recall}モードでセルフテストをしましょう。",
        "새 장: 사전 테스트를 풀고 노트를 읽은 뒤 {recall} 모드로 자가 테스트를 하세요.",
        "Neues Kapitel: Mach den Vortest, lies die Notizen und dann den Selbsttest im Modus {recall}.",
        "Nouveau chapitre : faites le prétest, lisez les notes, puis l'autotest en mode {recall}.",
        "Capítulo nuevo: haz la prueba previa, lee los apuntes y luego la autoevaluación en modo {recall}.",
        "Новая глава: пройдите предварительный тест, прочитайте заметки, затем самопроверку в режиме «{recall}»."),
    "Review days: flashcards first, then the review sheet with answers hidden.": (
        "复习日：先用记忆卡，再用隐藏答案的复习表。", "復習日：まず単語カード、次に答えを隠した復習シート。",
        "복습하는 날: 먼저 플래시카드, 그다음 답을 가린 복습지.",
        "Wiederholungstage: erst die Karteikarten, dann der Wiederholungsbogen mit verdeckten Antworten.",
        "Jours de révision : d'abord les cartes mémoire, puis la fiche de révision réponses cachées.",
        "Días de repaso: primero las tarjetas, luego la hoja de repaso con las respuestas ocultas.",
        "Дни повторения: сначала карточки, затем лист повторения со скрытыми ответами."),
    "Export your results from any quiz page and log them (mistakes import), so missed questions come back.": (
        "在任一测验页面导出成绩并记录（mistakes import），这样答错的题会再次出现。",
        "どのクイズページからでも結果をエクスポートして記録すると（mistakes import）、間違えた問題がまた出題されます。",
        "어느 퀴즈 페이지에서든 결과를 내보내 기록하면(mistakes import) 틀린 문제가 다시 나옵니다.",
        "Exportiere deine Ergebnisse auf einer Quizseite und trag sie ein (mistakes import), damit falsch beantwortete "
        "Fragen wiederkommen.",
        "Exportez vos résultats depuis une page de quiz et enregistrez-les (mistakes import) pour que les questions "
        "ratées reviennent.",
        "Exporta tus resultados desde cualquier página de preguntas y regístralos (mistakes import) para que vuelvan "
        "las preguntas falladas.",
        "Экспортируйте результаты на любой странице теста и внесите их (mistakes import), чтобы вопросы с ошибками "
        "вернулись."),
    "Items marked ⚠ are not fully verified: check them in the book before relying on them.": (
        "标有 ⚠ 的内容尚未完全核实：使用前请对照课本检查。", "⚠ の付いた項目は完全には確認されていません。頼る前に本で確かめましょう。",
        "⚠ 표시 항목은 완전히 확인되지 않았습니다. 믿기 전에 책에서 확인하세요.",
        "Mit ⚠ markierte Punkte sind nicht vollständig geprüft: Prüf sie im Buch, bevor du dich darauf verlässt.",
        "Les éléments marqués ⚠ ne sont pas entièrement vérifiés : vérifiez-les dans le livre avant de vous y fier.",
        "Lo marcado con ⚠ no está totalmente verificado: compruébalo en el libro antes de fiarte.",
        "Пункты с ⚠ проверены не полностью: сверьте их с книгой, прежде чем полагаться на них."),
    "Plan": ("计划", "計画", "계획", "Plan", "Plan", "Plan", "План"),
    "Date": ("日期", "日付", "날짜", "Datum", "Date", "Fecha", "Дата"),
    "Task": ("任务", "内容", "할 일", "Aufgabe", "Tâche", "Tarea", "Задача"),
    "Min": ("分钟", "分", "분", "Min.", "Min", "Min", "Мин"),
    "How": ("方法", "やり方", "방법", "Wie", "Comment", "Cómo", "Как"),
    "Run build to create the plan.": ("运行 build 生成计划。", "build を実行すると計画が作られます。", "build를 실행하면 계획이 만들어집니다.",
                                      "Führe build aus, um den Plan zu erstellen.", "Lancez build pour créer le plan.",
                                      "Ejecuta build para crear el plan.", "Запустите build, чтобы составить план."),
    "Chapters": ("章节", "章", "장", "Kapitel", "Chapitres", "Capítulos", "Главы"),
    "Exam prep": ("备考", "試験対策", "시험 대비", "Prüfungsvorbereitung", "Préparation à l'examen", "Preparación del examen",
                  "Подготовка к экзамену"),
    "{ok} claims verified, {warn} marked for a human check; {qok} of {qn} answer keys confirmed.": (
        "已核实 {ok} 条，{warn} 条需人工核对；{qn} 个答案中已确认 {qok} 个。",
        "確認済み {ok} 件、人による確認が必要 {warn} 件。解答 {qn} 件中 {qok} 件確認済み。",
        "확인됨 {ok}개, 사람이 확인할 것 {warn}개; 답안 {qn}개 중 {qok}개 확인됨.",
        "{ok} Aussagen geprüft, {warn} zur Prüfung durch einen Menschen markiert; {qok} von {qn} Lösungen bestätigt.",
        "{ok} affirmations vérifiées, {warn} à vérifier par une personne ; {qok} réponses sur {qn} confirmées.",
        "{ok} afirmaciones verificadas, {warn} marcadas para revisión humana; {qok} de {qn} respuestas confirmadas.",
        "проверено утверждений: {ok}, на проверку человеку: {warn}; подтверждено ответов: {qok} из {qn}."),
    # study plan (also the calendar file)
    "Exam": ("考试", "試験", "시험", "Prüfung", "Examen", "Examen", "Экзамен"),
    "Learn {cid}: {title}": ("学习 {cid}：{title}", "{cid} を学ぶ：{title}", "{cid} 공부: {title}", "{cid} lernen: {title}",
                             "Apprendre {cid} : {title}", "Estudiar {cid}: {title}", "Изучить {cid}: {title}"),
    "Pretest first, then the notes in read mode, then the self-test.": (
        "先做课前小测，再在阅读模式下读笔记，最后做自测。", "まず事前テスト、次に読むモードでノート、最後にセルフテスト。",
        "먼저 사전 테스트, 다음에 읽기 모드로 노트, 마지막으로 자가 테스트.",
        "Erst den Vortest, dann die Notizen im Lesemodus, dann den Selbsttest.",
        "D'abord le prétest, puis les notes en mode lecture, puis l'autotest.",
        "Primero la prueba previa, luego los apuntes en modo lectura y después la autoevaluación.",
        "Сначала предварительный тест, затем заметки в режиме чтения, потом самопроверка."),
    "Review {cid} (+{gap}d)": ("复习 {cid}（+{gap}天）", "{cid} を復習（+{gap}日）", "{cid} 복습(+{gap}일)",
                               "{cid} wiederholen (+{gap} T.)", "Réviser {cid} (+{gap} j)", "Repasar {cid} (+{gap} d)",
                               "Повторить {cid} (+{gap} дн.)"),
    "Flashcards, then the review sheet in recall mode. Redo missed questions.": (
        "先用记忆卡，再在回忆模式下用复习表。重做答错的题。", "単語カード、次に思い出すモードで復習シート。間違えた問題をやり直す。",
        "플래시카드, 그다음 회상 모드로 복습지. 틀린 문제를 다시 풀기.",
        "Karteikarten, dann der Wiederholungsbogen im Abrufmodus. Falsch beantwortete Fragen wiederholen.",
        "Cartes mémoire, puis la fiche de révision en mode rappel. Refaites les questions ratées.",
        "Tarjetas y luego la hoja de repaso en modo recordar. Repite las preguntas falladas.",
        "Карточки, затем лист повторения в режиме «Вспомнить». Перерешайте вопросы с ошибками."),
    "Mixed practice set {week}": ("综合练习 {week}", "ミックス演習 {week}", "혼합 연습 {week}", "Gemischte Übung {week}",
                                  "Entraînement mixte {week}", "Práctica mixta {week}", "Смешанная практика {week}"),
    "Interleaved questions from every chapter so far. Log mistakes.": (
        "混合已学各章的题目。记录错题。", "これまでの全章から混ぜた問題。間違いを記録する。",
        "지금까지 모든 장의 문제를 섞었습니다. 틀린 것을 기록하세요.",
        "Gemischte Fragen aus allen bisherigen Kapiteln. Fehler eintragen.",
        "Questions mélangées de tous les chapitres vus. Notez vos erreurs.",
        "Preguntas mezcladas de todos los capítulos hasta ahora. Anota los errores.",
        "Вперемешку вопросы из всех пройденных глав. Записывайте ошибки."),
    "Timed mock exam": ("计时模拟考试", "時間を計る模擬試験", "시간제 모의고사", "Probeklausur mit Zeitlimit",
                        "Examen blanc chronométré", "Simulacro cronometrado", "Пробный экзамен на время"),
    "Exam conditions. Afterwards, redo every missed question.": (
        "按考试条件进行。结束后重做所有错题。", "本番と同じ条件で。終わったら間違えた問題をすべてやり直す。",
        "시험과 같은 조건으로. 끝난 뒤 틀린 문제를 모두 다시 푸세요.",
        "Prüfungsbedingungen. Danach jede falsch beantwortete Frage wiederholen.",
        "Conditions d'examen. Ensuite, refaites chaque question ratée.",
        "Condiciones de examen. Después, repite cada pregunta fallada.",
        "Как на экзамене. Потом перерешайте все вопросы с ошибками."),
    "Cheat sheet + traps": ("速查表 + 易错点", "チートシート + 落とし穴", "요점 정리표 + 함정", "Spickzettel + Fallen",
                            "Antisèche + pièges", "Chuleta + trampas", "Шпаргалка + ловушки"),
    "Read the cheat sheet and the traps list; light flashcards only.": (
        "阅读速查表和易错点；只做少量记忆卡。", "チートシートと落とし穴を読む。単語カードは軽めに。",
        "요점 정리표와 함정 목록을 읽으세요. 플래시카드는 가볍게만.",
        "Spickzettel und Fallenliste lesen; nur wenige Karteikarten.",
        "Lisez l'antisèche et la liste des pièges ; peu de cartes mémoire.",
        "Lee la chuleta y la lista de trampas; solo unas pocas tarjetas.",
        "Прочитайте шпаргалку и список ловушек; карточки — немного."),
    "Mock exam + cheat sheet": ("模拟考试 + 速查表", "模擬試験 + チートシート", "모의고사 + 요점 정리표", "Probeklausur + Spickzettel",
                                "Examen blanc + antisèche", "Simulacro + chuleta", "Пробный экзамен + шпаргалка"),
    "Short on time: one mock exam, then the cheat sheet.": (
        "时间紧：做一次模拟考试，然后看速查表。", "時間がない場合：模擬試験を1回、次にチートシート。",
        "시간이 부족하면: 모의고사 한 번, 그다음 요점 정리표.", "Wenig Zeit: eine Probeklausur, dann der Spickzettel.",
        "Peu de temps : un examen blanc, puis l'antisèche.", "Poco tiempo: un simulacro y luego la chuleta.",
        "Мало времени: один пробный экзамен, затем шпаргалка."),
    "Exam day": ("考试日", "試験日", "시험 날", "Prüfungstag", "Jour de l'examen", "Día del examen", "День экзамена"),
    "Skim the cheat sheet in the morning. Sleep matters more than cramming.": (
        "早上浏览一下速查表。睡眠比临时抱佛脚更重要。", "朝にチートシートをざっと見る。詰め込みより睡眠が大切です。",
        "아침에 요점 정리표를 훑어보세요. 벼락치기보다 잠이 더 중요합니다.",
        "Morgens den Spickzettel überfliegen. Schlaf ist wichtiger als Pauken.",
        "Survolez l'antisèche le matin. Le sommeil compte plus que le bachotage.",
        "Repasa la chuleta por la mañana. Dormir importa más que memorizar a última hora.",
        "Утром просмотрите шпаргалку. Сон важнее зубрёжки."),
    # priority reasons (stored in English, shown translated)
    "{n} past-paper question(s)": ("{n} 道历年真题", "過去問 {n} 問", "기출 문제 {n}개", "{n} Frage(n) aus Altklausuren",
                                   "{n} question(s) d'annales", "{n} pregunta(s) de exámenes anteriores",
                                   "вопросов из прошлых экзаменов: {n}"),
    "listed in the syllabus": ("列入教学大纲", "シラバスに記載", "강의 계획서에 있음", "im Lehrplan genannt", "au programme",
                               "en el temario", "есть в программе"),
    "{n} learning objective(s)": ("{n} 个学习目标", "学習目標 {n} 件", "학습 목표 {n}개", "{n} Lernziel(e)",
                                  "{n} objectif(s) d'apprentissage", "{n} objetivo(s) de aprendizaje",
                                  "учебных целей: {n}"),
    "{n} end-of-chapter exercise(s)": ("{n} 道章末习题", "章末問題 {n} 問", "장 끝 연습 문제 {n}개",
                                       "{n} Übungsaufgabe(n) am Kapitelende", "{n} exercice(s) de fin de chapitre",
                                       "{n} ejercicio(s) de final de capítulo", "упражнений в конце главы: {n}"),
    "ideas reused in summaries or later chapters": (
        "在小结或后续章节中再次用到", "まとめや後の章で再び使われる", "요약이나 뒤 장에서 다시 쓰임",
        "in Zusammenfassungen oder späteren Kapiteln wieder aufgegriffen",
        "idées reprises dans les résumés ou les chapitres suivants",
        "ideas que reaparecen en resúmenes o capítulos posteriores", "идеи повторяются в итогах или следующих главах"),
    "boxed key content": ("课本中框出的重点", "本で枠囲みされた重要事項", "책에서 상자로 강조한 핵심 내용", "im Buch hervorgehobener Kasten",
                          "contenu clé encadré", "contenido clave destacado en recuadro", "ключевой материал в рамке"),
    "book signals only": ("仅依据课本中的标记", "本の手がかりのみ", "책의 표시만 근거", "nur Hinweise aus dem Buch",
                          "seulement les indices du livre", "solo las señales del libro", "только признаки из книги"),
    # flashcards, Obsidian notes, study-plan file
    ": ": ("：", "：", ": ", ": ", " : ", ": ", ": "),
    "Book p.{pages}": ("课本 p.{pages}", "本 p.{pages}", "책 p.{pages}", "Buch S. {pages}", "Livre p. {pages}",
                       "Libro p. {pages}", "Книга, с. {pages}"),
    "When does this hold?": ("这个公式在什么条件下成立？", "この式はどんなときに成り立つ？", "이 식은 언제 성립하나요?", "Wann gilt das?",
                             "Quand est-ce valable ?", "¿Cuándo se cumple?", "Когда это верно?"),
    "{a} vs {b}: {aspect}?": ("{a} 与 {b}：{aspect}？", "{a} と {b}：{aspect}は？", "{a} 대 {b}: {aspect}?",
                              "{a} vs. {b}: {aspect}?", "{a} ou {b} : {aspect} ?", "{a} frente a {b}: ¿{aspect}?",
                              "{a} и {b}: {aspect}?"),
    "{name}: what comes after “{step}”?": ("{name}：“{step}”之后是哪一步？", "{name}：「{step}」の次は？",
                                           "{name}: “{step}” 다음은?", "{name}: Was kommt nach „{step}“?",
                                           "{name} : qu'est-ce qui suit « {step} » ?",
                                           "{name}: ¿qué viene después de «{step}»?", "{name}: что идёт после «{step}»?"),
    "(true or false?)": ("（对还是错？）", "（正しい？誤り？）", "(참 또는 거짓?)", "(wahr oder falsch?)", "(vrai ou faux ?)",
                         "(¿verdadero o falso?)", "(верно или нет?)"),
    "AI-added": ("AI 补充", "AIによる追加", "AI 추가", "von der KI ergänzt", "ajouté par l'IA", "añadido por la IA",
                 "добавлено ИИ"),
    "Generated by ExamScribe from the book. {ok} verified, {warn} check, {pending} not yet verified, {ai} AI-added.": (
        "由 ExamScribe 根据课本生成。{ok} 已核实，{warn} 请核对，{pending} 尚未核实，{ai} AI 补充。",
        "ExamScribe が本から作成。{ok} 確認済み、{warn} 要確認、{pending} 未確認、{ai} AIによる追加。",
        "ExamScribe가 책에서 만듦. {ok} 확인됨, {warn} 확인 필요, {pending} 아직 확인 안 됨, {ai} AI 추가.",
        "Von ExamScribe aus dem Buch erstellt. {ok} geprüft, {warn} bitte prüfen, {pending} noch nicht geprüft, "
        "{ai} von der KI ergänzt.",
        "Généré par ExamScribe à partir du livre. {ok} vérifié, {warn} à vérifier, {pending} pas encore vérifié, "
        "{ai} ajouté par l'IA.",
        "Generado por ExamScribe a partir del libro. {ok} verificado, {warn} por comprobar, {pending} aún no "
        "verificado, {ai} añadido por la IA.",
        "Создано ExamScribe по книге. {ok} проверено, {warn} проверьте, {pending} ещё не проверено, {ai} добавлено ИИ."),
    "Study plan — {title}": ("学习计划 — {title}", "学習計画 — {title}", "학습 계획 — {title}", "Lernplan — {title}",
                             "Plan de révision — {title}", "Plan de estudio — {title}", "План занятий — {title}"),
    "Study: {title}": ("学习：{title}", "学習：{title}", "학습: {title}", "Lernen: {title}", "Révisions : {title}",
                       "Estudio: {title}", "Учёба: {title}"),
    "Minutes": ("分钟", "分", "분", "Minuten", "Minutes", "Minutos", "Минуты"),
    "{m} min": ("{m} 分钟", "{m}分", "{m}분", "{m} Min.", "{m} min", "{m} min", "{m} мин"),
    # verification report page
    "Answer keys: {ok} confirmed by an independent solver, {warn} disputed, {pending} pending.": (
        "答案：{ok} 个经独立解答确认，{warn} 个有争议，{pending} 个待定。",
        "解答：{ok} 件は独立した解答で確認済み、{warn} 件は食い違い、{pending} 件は未確認。",
        "답안: {ok}개는 독립적인 풀이로 확인됨, {warn}개는 이견 있음, {pending}개는 대기 중.",
        "Lösungen: {ok} von einem unabhängigen Löser bestätigt, {warn} strittig, {pending} offen.",
        "Corrigés : {ok} confirmés par une résolution indépendante, {warn} contestés, {pending} en attente.",
        "Respuestas: {ok} confirmadas por una resolución independiente, {warn} en disputa, {pending} pendientes.",
        "Ответы: подтверждено независимым решением — {ok}, спорных — {warn}, ожидают — {pending}."),
    "Attention tests: the checker caught {caught} of {planted} planted false claims; {rejected} batch(es) had to be "
    "redone.": (
        "注意力测试：核对者识别出了 {planted} 条故意植入的错误说法中的 {caught} 条；有 {rejected} 批需要重做。",
        "注意力テスト：チェック役は仕込まれた誤った主張 {planted} 件中 {caught} 件を見抜きました。やり直しは {rejected} 回分です。",
        "주의력 테스트: 검토자가 일부러 넣은 거짓 주장 {planted}개 중 {caught}개를 찾아냈습니다. 다시 한 묶음: {rejected}개.",
        "Aufmerksamkeitstests: Der Prüfer hat {caught} von {planted} absichtlich eingefügten falschen Aussagen erkannt; "
        "wiederholte Durchgänge: {rejected}.",
        "Tests d'attention : le vérificateur a repéré {caught} des {planted} fausses affirmations glissées exprès ; "
        "lots refaits : {rejected}.",
        "Pruebas de atención: el revisor detectó {caught} de {planted} afirmaciones falsas puestas a propósito; "
        "lotes repetidos: {rejected}.",
        "Проверка внимательности: проверяющий нашёл {caught} из {planted} специально подложенных ложных утверждений; "
        "переделано пакетов: {rejected}."),
    "How to read this: every claim in the notes quotes the book; a script confirmed each quote is on the cited page "
    "and recomputed every calculation; then an independent checker compared each claim with the book text. Anything "
    "below needs a human look before you rely on it.": (
        "如何阅读：笔记中的每条说法都引用了课本；脚本确认了每条引文确实在所注页码上，并重新计算了每个算式；随后由独立的核对者把每条说法与课本原文"
        "逐一比对。下面列出的内容在使用前需要人工查看。",
        "読み方：ノートの各主張は本を引用しています。スクリプトが各引用が示されたページにあることを確かめ、計算をすべてやり直しました。その後、"
        "独立したチェック役が各主張を本文と照合しました。以下の項目は、頼る前に人の目で確認してください。",
        "읽는 법: 노트의 모든 주장은 책을 인용합니다. 스크립트가 각 인용문이 표시된 쪽에 있는지 확인하고 모든 계산을 다시 했으며, 이어서 독립된 "
        "검토자가 각 주장을 책 본문과 비교했습니다. 아래 항목은 믿기 전에 사람이 확인해야 합니다.",
        "So liest du das: Jede Aussage in den Notizen zitiert das Buch; ein Skript hat geprüft, dass jedes Zitat auf der "
        "angegebenen Seite steht, und jede Rechnung nachgerechnet; dann hat ein unabhängiger Prüfer jede Aussage mit "
        "dem Buchtext verglichen. Alles unten sollte ein Mensch ansehen, bevor du dich darauf verlässt.",
        "Comment lire ceci : chaque affirmation des notes cite le livre ; un script a vérifié que chaque citation se "
        "trouve à la page indiquée et a refait chaque calcul ; puis un vérificateur indépendant a comparé chaque "
        "affirmation au texte du livre. Tout ce qui suit doit être relu par une personne avant de vous y fier.",
        "Cómo leer esto: cada afirmación de los apuntes cita el libro; un script confirmó que cada cita está en la "
        "página indicada y rehízo cada cálculo; después, un revisor independiente comparó cada afirmación con el texto "
        "del libro. Todo lo de abajo necesita una revisión humana antes de fiarte.",
        "Как это читать: каждое утверждение в заметках цитирует книгу; скрипт подтвердил, что каждая цитата есть на "
        "указанной странице, и пересчитал все вычисления; затем независимый проверяющий сравнил каждое утверждение с "
        "текстом книги. Всё, что ниже, должен посмотреть человек, прежде чем на это полагаться."),
    "Not started yet.": ("尚未开始。", "まだ始まっていません。", "아직 시작하지 않음.", "Noch nicht begonnen.", "Pas encore commencé.",
                         "Aún no empezado.", "Ещё не начато."),
    "Coverage of the book’s key items: {covered} covered, {skipped} skipped (reasons below), {missing} missing{list}.": (
        "课本关键内容覆盖：已覆盖 {covered} 项，跳过 {skipped} 项（原因见下），缺少 {missing} 项{list}。",
        "本の重要項目：カバー {covered} 件、スキップ {skipped} 件（理由は下記）、不足 {missing} 件{list}。",
        "책 핵심 항목: 반영 {covered}개, 건너뜀 {skipped}개(이유는 아래), 누락 {missing}개{list}.",
        "Wichtige Punkte des Buchs: {covered} abgedeckt, {skipped} übersprungen (Gründe unten), {missing} fehlen{list}.",
        "Éléments clés du livre : {covered} couverts, {skipped} ignorés (raisons ci-dessous), {missing} manquants{list}.",
        "Elementos clave del libro: {covered} cubiertos, {skipped} omitidos (motivos abajo), {missing} faltan{list}.",
        "Ключевые элементы книги: охвачено {covered}, пропущено {skipped} (причины ниже), отсутствует {missing}{list}."),
    "Learning objectives without a question: {list}.": (
        "没有对应题目的学习目标：{list}。", "問題のない学習目標：{list}。", "문제가 없는 학습 목표: {list}.",
        "Lernziele ohne Frage: {list}.", "Objectifs d'apprentissage sans question : {list}.",
        "Objetivos de aprendizaje sin pregunta: {list}.", "Учебные цели без вопроса: {list}."),
    "none": ("无", "なし", "없음", "keine", "aucun", "ninguno", "нет"),
    "Claims to check": ("需要核对的说法", "確認が必要な主張", "확인할 주장", "Zu prüfende Aussagen", "Affirmations à vérifier",
                        "Afirmaciones por comprobar", "Утверждения для проверки"),
    "Where": ("位置", "場所", "위치", "Wo", "Où", "Dónde", "Где"),
    "Claim": ("说法", "主張", "주장", "Aussage", "Affirmation", "Afirmación", "Утверждение"),
    "Why flagged": ("标记原因", "指摘の理由", "표시한 이유", "Warum markiert", "Pourquoi signalé", "Por qué se marcó",
                    "Почему отмечено"),
    "Formulas to check against the printed book": (
        "需要对照纸质课本核对的公式", "印刷された本と照合が必要な式", "인쇄된 책과 대조할 공식",
        "Formeln, die mit dem gedruckten Buch abzugleichen sind", "Formules à comparer au livre imprimé",
        "Fórmulas que hay que comprobar con el libro impreso", "Формулы, которые нужно сверить с печатной книгой"),
    "Questions with disputed answer keys (left out of practice sets)": (
        "答案有争议的题目（未放入练习）", "解答に食い違いがある問題（演習から除外）", "답안에 이견이 있는 문제(연습 세트에서 제외)",
        "Fragen mit strittiger Lösung (nicht in den Übungen)", "Questions au corrigé contesté (exclues des entraînements)",
        "Preguntas con respuesta en disputa (fuera de las prácticas)", "Вопросы со спорным ответом (не входят в практику)"),
    "Marked UNSURE by the writer": ("编写时标为“不确定”的内容", "作成時に「不確か」とされた項目", "작성자가 '불확실'로 표시한 항목",
                                    "Beim Schreiben als UNSICHER markiert", "Marqué INCERTAIN lors de la rédaction",
                                    "Marcado como NO SEGURO al redactar", "Помечено при написании как НЕ УВЕРЕН"),
    "Skipped items": ("跳过的内容", "スキップした項目", "건너뛴 항목", "Übersprungene Punkte", "Éléments ignorés",
                      "Elementos omitidos", "Пропущенные элементы"),
    "Pages where text extraction may be unreliable": (
        "文字提取可能不可靠的页面", "文字の読み取りが不確かなページ", "글자 추출이 불확실할 수 있는 쪽",
        "Seiten, deren Text unzuverlässig erkannt sein kann", "Pages dont le texte extrait peut être peu fiable",
        "Páginas cuya extracción de texto puede no ser fiable", "Страницы, где текст мог быть извлечён ненадёжно"),
    "Quotes from these pages are marked for checking (on OCR pages: quotes with numbers). Pictures of these pages are "
    "in {folder} (or run: {command}).": (
        "这些页面上的引文会被标记以便核对（OCR 页面上：含数字的引文）。这些页面的图片在 {folder} 中（或运行：{command}）。",
        "これらのページからの引用は確認対象として示されます（OCRページでは数字を含む引用）。ページの画像は {folder} にあります（または {command} を実行）。",
        "이 쪽들의 인용문은 확인 대상으로 표시됩니다(OCR 쪽에서는 숫자가 있는 인용문). 쪽 이미지는 {folder}에 있습니다(또는 {command} 실행).",
        "Zitate von diesen Seiten werden zur Prüfung markiert (auf OCR-Seiten: Zitate mit Zahlen). Bilder dieser Seiten "
        "liegen in {folder} (oder: {command}).",
        "Les citations de ces pages sont signalées pour vérification (sur les pages OCR : les citations avec des "
        "nombres). Les images de ces pages sont dans {folder} (ou lancez : {command}).",
        "Las citas de estas páginas se marcan para comprobarlas (en páginas OCR: las citas con números). Las imágenes "
        "de estas páginas están en {folder} (o ejecuta: {command}).",
        "Цитаты с этих страниц отмечены для проверки (на страницах OCR — цитаты с числами). Изображения страниц лежат в "
        "{folder} (или выполните: {command})."),
    "… and {n} more": ("……还有 {n} 页", "…ほか {n} ページ", "… 외 {n}쪽", "… und {n} weitere", "… et {n} de plus",
                       "… y {n} más", "… и ещё {n}"),
    "Instructor material vs. book": ("老师材料与课本的差异", "先生の資料と本の違い", "강사 자료와 책의 차이",
                                     "Material der Lehrkraft vs. Buch", "Support de l'enseignant et livre",
                                     "Material del profesor frente al libro", "Материалы преподавателя и книга"),
    "Records changed by hand": ("被手动改动的记录", "手作業で変更された記録", "직접 수정된 기록", "Von Hand geänderte Aufzeichnungen",
                                "Enregistrements modifiés à la main", "Registros modificados a mano",
                                "Записи, изменённые вручную"),
    "Files that only the scripts write were changed outside them {n} time(s). ExamScribe put its own version back each "
    "time; still, read the flagged items with extra care.": (
        "只应由脚本写入的文件在脚本之外被改动了 {n} 次。ExamScribe 每次都恢复了自己的版本；但阅读被标记的条目时仍请格外仔细。",
        "スクリプトだけが書くファイルが、スクリプト以外で {n} 回変更されました。ExamScribe はそのたびに自分の版に戻しましたが、印の付いた項目は特に注意して読んでください。",
        "스크립트만 쓰는 파일이 스크립트 밖에서 {n}번 수정되었습니다. ExamScribe가 매번 자기 버전으로 되돌렸지만, 표시된 항목은 특히 주의해서 읽으세요.",
        "Dateien, die nur die Skripte schreiben, wurden {n}-mal außerhalb von ihnen geändert. ExamScribe hat jedes Mal "
        "die eigene Fassung zurückgelegt; lies die markierten Punkte trotzdem besonders sorgfältig.",
        "Des fichiers que seuls les scripts écrivent ont été modifiés en dehors d'eux {n} fois. ExamScribe a remis sa "
        "propre version à chaque fois ; lisez tout de même les éléments signalés avec une attention particulière.",
        "Archivos que solo escriben los scripts se modificaron fuera de ellos {n} vez/veces. ExamScribe repuso su "
        "propia versión cada vez; aun así, lee con especial cuidado los elementos marcados.",
        "Файлы, которые пишут только скрипты, были изменены вне их {n} раз(а). ExamScribe каждый раз возвращал свою "
        "версию; всё же читайте отмеченные пункты особенно внимательно."),
    # verification flags (stored in English, shown translated)
    "quote matches the book only approximately": (
        "引文与课本只是大致相符", "引用が本と大まかにしか一致しない", "인용문이 책과 대략적으로만 일치함",
        "Zitat stimmt nur ungefähr mit dem Buch überein", "la citation ne correspond qu'approximativement au livre",
        "la cita solo coincide aproximadamente con el libro", "цитата совпадает с книгой лишь приблизительно"),
    "p.{pages} was read by OCR: check the numbers against the printed page": (
        "p.{pages} 由 OCR 识别：请对照纸质页面核对数字", "p.{pages} はOCRで読み取り：数字を印刷されたページと照合してください",
        "p.{pages}는 OCR로 읽음: 숫자를 인쇄된 쪽과 대조하세요", "S. {pages} wurde per OCR gelesen: Zahlen mit der gedruckten "
        "Seite vergleichen", "p. {pages} lue par OCR : vérifiez les nombres sur la page imprimée",
        "p. {pages} se leyó con OCR: comprueba los números en la página impresa",
        "с. {pages} распознана OCR: сверьте числа с печатной страницей"),
    "text extraction on p.{pages} may be unreliable": (
        "p.{pages} 的文字提取可能不可靠", "p.{pages} の文字の読み取りは不確かな可能性があります", "p.{pages}의 글자 추출은 불확실할 수 있음",
        "Text auf S. {pages} ist möglicherweise unzuverlässig erkannt", "le texte extrait p. {pages} peut être peu fiable",
        "el texto extraído en p. {pages} puede no ser fiable", "текст на с. {pages} мог быть извлечён ненадёжно"),
    "partial": ("只有部分有依据", "一部しか裏づけがない", "일부만 뒷받침됨", "nur teilweise belegt", "seulement en partie étayé",
                "solo en parte respaldado", "подтверждено лишь частично"),
    "not supported": ("课本中找不到依据", "本に根拠がない", "책에 근거 없음", "nicht belegt", "non étayé", "sin respaldo",
                      "не подтверждено"),
    "contradicted": ("与课本相矛盾", "本と矛盾する", "책과 모순됨", "widerspricht dem Buch", "contredit par le livre",
                     "contradice el libro", "противоречит книге"),
    "could not be confirmed against the printed formula": (
        "无法与课本印刷的公式核对一致", "印刷された式との一致を確認できませんでした", "인쇄된 공식과 일치하는지 확인할 수 없음",
        "konnte nicht mit der gedruckten Formel bestätigt werden", "n'a pas pu être confirmée avec la formule imprimée",
        "no se pudo confirmar con la fórmula impresa", "не удалось сверить с печатной формулой"),
    'The book defines "{term}" as: "{quote}"': (
        "课本对“{term}”的定义：“{quote}”", "本による「{term}」の定義：「{quote}」", "책의 “{term}” 정의: “{quote}”",
        "Das Buch definiert „{term}“ als: „{quote}“", "Le livre définit « {term} » ainsi : « {quote} »",
        "El libro define «{term}» como: «{quote}»", "Книга определяет «{term}» так: «{quote}»"),
    # browser script
    "Correct.": ("正确。", "正解。", "정답.", "Richtig.", "Correct.", "Correcto.", "Верно."),
    "Not quite.": ("不太对。", "惜しい。", "조금 다릅니다.", "Nicht ganz.", "Pas tout à fait.", "No del todo.", "Не совсем."),
    "{good} / {done} correct ({total} questions)": (
        "答对 {good} / {done}（共 {total} 题）", "{good} / {done} 正解（全 {total} 問）", "{good} / {done} 정답(총 {total}문제)",
        "{good} / {done} richtig ({total} Fragen)", "{good} / {done} correctes ({total} questions)",
        "{good} / {done} correctas ({total} preguntas)", "верно {good} / {done} (всего вопросов: {total})"),
}

JS_KEYS = ("Correct.", "Not quite.", "{good} / {done} correct ({total} questions)")
_REASONS = [(re.compile(r"^(\d+) past-paper question\(s\)$"), "{n} past-paper question(s)"),
            (re.compile(r"^(\d+) learning objective\(s\)$"), "{n} learning objective(s)"),
            (re.compile(r"^(\d+) end-of-chapter exercise\(s\)$"), "{n} end-of-chapter exercise(s)")]
_FLAGS = [(re.compile(r"^p\.(.+?) was read by OCR: check the numbers against the printed page$"),
           "p.{pages} was read by OCR: check the numbers against the printed page"),
          (re.compile(r"^text extraction on p\.(.+?) may be unreliable$"), "text extraction on p.{pages} may be unreliable")]
_DEFINES = re.compile(r'^The book defines "(.+?)" as: "(.*)"$', re.S)
FORMATS = {"mcq": "multiple choice", "short-answer": "short answer", "essay": "essay", "problems": "problems"}
POLICIES = {"closed": "closed book", "open": "open book", "cheat-sheet": "one cheat sheet allowed"}


def set_language(code: str | None) -> None:
    base = (code or "en").lower().split("-")[0]
    _LANG[0] = base if base in LANGS else "en"


def language_of(ws) -> str:
    return (ws.config.get("output") or {}).get("language") or (ws.config.get("book") or {}).get("language") or "en"


def use_language(ws) -> None:
    """Pages are worded in the notes language of this workspace."""
    set_language(language_of(ws))


def T(text: str, **kw) -> str:
    row = TEXT.get(text)
    s = row[LANGS.index(_LANG[0])] if row and _LANG[0] in LANGS else text
    return s.format(**kw) if kw else s


def reason(text: str) -> str:
    """A priority reason (stored in English) in the page language."""
    for pat, key in _REASONS:
        m = pat.match(text)
        if m:
            return T(key, n=m.group(1))
    return T(text)


def flag_reason(text: str) -> str:
    """A verification flag (stored in English) in the page language; a checker's own words stay as written."""
    if _LANG[0] == "en":
        return text
    for pat, key in _FLAGS:
        m = pat.match(text)
        if m:
            return T(key, pages=m.group(1).replace(", p.", ", "))
    return T(text)


def answer_text(qtype: str, answer: str) -> str:
    """A question's answer as the student sees it: true/false in the page language."""
    a = (answer or "").strip()
    if qtype.lower() == "tf" and a.lower() in ("true", "false"):
        return T("True") if a.lower() == "true" else T("False")
    return a


def claim_text(text: str) -> str:
    """A claim as the report shows it: the script-made definition claim in the page language."""
    m = _DEFINES.match(text)
    if not m or _LANG[0] == "en":
        return text
    return T('The book defines "{term}" as: "{quote}"', term=m.group(1), quote=m.group(2))


def js_strings() -> str:
    """The browser script's words, as JSON for a data attribute."""
    return json.dumps({k: T(k) for k in JS_KEYS}, ensure_ascii=False)
