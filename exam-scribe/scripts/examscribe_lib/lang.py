"""Words that mark the structure of a textbook, in many languages.

Extraction and the inventory find captions, worked examples, learning objectives, chapter labels and the
end-of-chapter parts (summary, key terms, exercises, ...) by these words. English, German, French, Spanish,
Italian, Portuguese, Dutch, Russian, Polish, Turkish, Vietnamese, Indonesian, Chinese, Japanese, Korean,
Arabic and Hindi are covered; add words here to support more.
"""
from __future__ import annotations

import re


def _alt(words: list[str]) -> str:
    return "|".join(re.escape(w).replace(r"\ ", r"\s+") for w in sorted(set(words), key=len, reverse=True))


FIGURE = ["Figure", "Fig.", "Figs.", "Chart", "Diagram", "Abbildung", "Abb.", "Bild", "Figura", "Figuur", "Afbeelding",
          "Rysunek", "Rys.", "Рисунок", "Рис.", "Şekil", "Hình", "Gambar", "图表", "圖表", "図表", "图", "圖", "図",
          "그림", "شكل", "الشكل", "चित्र"]
TABLE = ["Table", "Tabelle", "Tab.", "Tableau", "Tabla", "Tabella", "Tabela", "Tabel", "Таблица", "Табл.", "Tablo",
         "Bảng", "表", "표", "جدول", "الجدول", "तालिका", "सारणी"]
EXAMPLE = ["Example", "Worked example", "Worked Example", "Sample problem", "Sample Problem", "Beispiel",
           "Rechenbeispiel", "Musterbeispiel", "Exemple", "Ejemplo", "Esempio", "Exemplo", "Voorbeeld", "Пример",
           "Przykład", "Örnek", "Ví dụ", "Contoh", "例题", "例題", "例", "예제", "보기", "مثال", "उदाहरण"]
OBJECTIVES = ["learning objectives", "learning objective", "learning outcomes", "learning outcome", "objectives",
              "objective", "goals", "by the end of this section", "after studying this section",
              "after reading this section", "after studying this chapter", "after reading this chapter",
              "Lernziele", "Ziele", "Objectifs d'apprentissage", "Objectifs", "Objetivos de aprendizaje", "Objetivos",
              "Obiettivi di apprendimento", "Obiettivi", "Objetivos de aprendizagem", "Leerdoelen", "Цели обучения",
              "Цели", "Cele", "Hedefler", "Mục tiêu", "Tujuan pembelajaran", "Tujuan", "学习目标", "學習目標", "学習目標",
              "本节目标", "학습 목표", "학습목표", "أهداف التعلم", "الأهداف", "अधिगम उद्देश्य", "उद्देश्य"]
SUMMARY = ["summary", "chapter summary", "section summary", "key concepts and summary", "key concepts",
           "key points", "Zusammenfassung", "Das Wichtigste in Kürze", "Résumé", "L'essentiel", "Resumen",
           "Riepilogo", "Sommario", "Sintesi", "Resumo", "Samenvatting", "Резюме", "Итоги", "Выводы",
           "Краткие итоги", "Podsumowanie", "Özet", "Tóm tắt", "Ringkasan", "本章小结", "本章小結", "本章总结",
           "本章要点", "小结", "小結", "总结", "總結", "要点", "まとめ", "要約", "本章のまとめ", "요약", "정리", "ملخص", "الملخص",
           "خلاصة", "सारांश"]
KEY_TERMS = ["key terms", "glossary", "vocabulary", "key vocabulary", "Schlüsselbegriffe", "Wichtige Begriffe",
             "Fachbegriffe", "Glossar", "Termes clés", "Mots clés", "Glossaire", "Vocabulaire", "Términos clave",
             "Glosario", "Vocabulario", "Termini chiave", "Glossario", "Termos-chave", "Termos chave", "Glossário",
             "Kernbegrippen", "Begrippen", "Ключевые термины", "Основные понятия", "Глоссарий", "Словарь",
             "Kluczowe pojęcia", "Słowniczek", "Anahtar terimler", "Sözlük", "Thuật ngữ", "Istilah penting",
             "关键术语", "關鍵術語", "关键词", "重要术语", "名词解释", "重要用語", "キーワード", "用語", "핵심 용어", "주요 용어",
             "المصطلحات الرئيسية", "المصطلحات", "मुख्य शब्द", "प्रमुख शब्द", "शब्दावली"]
KEY_EQUATIONS = ["key equations", "important equations", "equations", "Wichtige Gleichungen", "Formeln",
                 "Formelsammlung", "Équations clés", "Formules", "Ecuaciones clave", "Fórmulas", "Equazioni",
                 "Formule", "Equações", "Основные формулы", "Формулы", "Wzory", "Formüller", "Công thức", "Rumus",
                 "重要公式", "主要公式", "公式", "重要な式", "주요 공식", "공식", "المعادلات الرئيسية", "المعادلات",
                 "मुख्य समीकरण", "सूत्र"]
EXERCISES = ["review questions", "exercises", "problems", "conceptual questions", "critical thinking",
             "additional problems", "challenge problems", "practice", "chapter review", "questions",
             "Aufgaben", "Übungen", "Übungsaufgaben", "Fragen", "Kontrollfragen", "Exercices", "Problèmes",
             "Questions", "Ejercicios", "Problemas", "Preguntas", "Esercizi", "Problemi", "Domande", "Exercícios",
             "Questões", "Opgaven", "Vragen", "Упражнения", "Задачи", "Вопросы", "Контрольные вопросы", "Zadania",
             "Ćwiczenia", "Pytania", "Alıştırmalar", "Sorular", "Problemler", "Bài tập", "Câu hỏi", "Latihan", "Soal",
             "习题", "習題", "练习", "練習", "思考题", "思考題", "复习题", "複習題", "演習問題", "練習問題", "問題", "연습 문제",
             "연습문제", "확인 문제", "تمارين", "التمارين", "أسئلة", "مسائل", "अभ्यास", "प्रश्नावली", "प्रश्न"]
BACK_MATTER = ["further reading", "references", "bibliography", "answers", "answer key", "self-test", "review",
               "check your understanding", "end-of-chapter", "Literatur", "Literaturverzeichnis", "Literaturhinweise",
               "Weiterführende Literatur", "Quellen", "Quellenverzeichnis", "Internetadressen", "Weblinks",
               "Unterrichtsmaterialien", "Lösungen", "Bibliographie",
               "Références", "Solutions", "Réponses", "Corrigés", "Bibliografía", "Referencias", "Soluciones",
               "Respuestas", "Clave de respuestas",
               "Bibliografia", "Soluzioni", "Referências", "Respostas", "Литература", "Ответы", "Odpowiedzi",
               "Kaynakça", "Cevaplar", "Tài liệu tham khảo", "Đáp án", "Daftar pustaka", "Jawaban", "参考文献",
               "参考答案", "答案", "解答", "참고 문헌", "정답", "المراجع", "الإجابات", "संदर्भ", "उत्तर"]
# front and back matter that is not a chapter
NOT_CHAPTER = ["preface", "foreword", "contents", "table of contents", "index", "answer key", "answers", "appendix",
               "glossary", "references", "bibliography", "acknowledg", "about", "copyright", "dedication", "notes",
               "further reading", "credits", "list of", "blank page", "Vorwort", "Inhaltsverzeichnis", "Inhalt",
               "Register", "Stichwortverzeichnis", "Sachverzeichnis", "Anhang", "Literatur", "Impressum",
               "Préface", "Avant-propos", "Table des matières", "Sommaire", "Annexe", "Prólogo", "Prefacio", "Índice",
               "Contenidos", "Contenido", "Tabla de contenido", "Apéndice", "Anexo", "Clave de respuestas",
               "Prefazione", "Indice", "Appendice", "Prefácio", "Sumário", "Apêndice",
               "Voorwoord", "Inhoud", "Bijlage", "Предисловие", "Содержание", "Оглавление", "Приложение",
               "Предметный указатель", "Przedmowa", "Spis treści", "Dodatek", "Önsöz", "İçindekiler", "Lời nói đầu",
               "Mục lục", "Phụ lục", "Kata pengantar", "Daftar isi", "Lampiran", "前言", "序言", "目录", "目錄", "索引",
               "附录", "附錄", "はじめに", "まえがき", "目次", "付録", "あとがき", "머리말", "서문", "차례", "목차", "찾아보기",
               "부록", "مقدمة", "المحتويات", "الفهرس", "ملحق", "प्रस्तावना", "विषय सूची", "अनुक्रमणिका", "परिशिष्ट"]
# not a chapter only when they are the whole title ("Lösungen" is the answer key, "Lösungen und Gemische" a chapter)
NOT_CHAPTER_EXACT = ["solutions", "Lösungen", "Réponses", "Corrigés", "Soluciones", "Respuestas", "Soluzioni",
                     "Risposte", "Soluções", "Respostas", "Решения", "Ответы", "editorial"]
CHAPTER_WORDS = ["chapter", "unit", "lesson", "module", "part", "Kapitel", "Lektion", "Chapitre", "Leçon", "Capítulo",
                 "Lección", "Capitolo", "Lezione", "Hoofdstuk", "Глава", "Урок", "Rozdział", "Bölüm", "Ünite", "Chương",
                 "Bài", "Bab"]
# bold runs that are labels, not key terms
NOT_TERM_WORDS = ["Abschnitt", "Artikel", "Absatz", "Paragraph", "Art.", "Abs.", "Teil", "Impressum", "Editorial",
                  "Inhalt", "Inhaltsverzeichnis", "Vorwort", "Literaturhinweise", "Literatur", "Preface", "Foreword",
                  "Contents", "Acknowledgments", "Acknowledgements", "Bibliography", "Article", "Artículo",
                  "Lösung", "Beispiel", "Hinweis", "Merke", "Achtung", "Aufgabe", "Bemerkung", "Remarque",
                  "Attention", "Exemple", "Ejemplo", "Solución", "Nota", "Observación", "Esempio", "Soluzione",
                  "Osservazione", "Exemplo", "Solução", "Observação", "Пример", "Решение", "Примечание", "Внимание",
                  "Задача", "注意", "注", "解", "例", "解答", "提示", "答", "例題", "解説", "ヒント", "풀이", "예제", "참고", "주의",
                  "مثال", "الحل", "ملاحظة", "उदाहरण", "हल", "टिप्पणी"]

LANG_NAMES = {"en": "English", "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "de": "German", "fr": "French",
              "es": "Spanish", "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "ru": "Russian", "uk": "Ukrainian",
              "pl": "Polish", "tr": "Turkish", "vi": "Vietnamese", "id": "Indonesian", "ar": "Arabic", "fa": "Persian",
              "he": "Hebrew", "hi": "Hindi", "th": "Thai", "el": "Greek", "cs": "Czech", "sv": "Swedish"}


def lang_name(code: str | None) -> str:
    """'zh' -> 'Chinese (zh)'; unknown codes are returned as they are."""
    code = (code or "en").strip()
    name = LANG_NAMES.get(code.lower().split("-")[0])
    return f"{name} ({code})" if name else code


# title of the text between a chapter's start and its first section
INTRODUCTION = {"en": "Introduction", "de": "Einleitung", "fr": "Introduction", "es": "Introducción",
                "it": "Introduzione", "pt": "Introdução", "nl": "Inleiding", "ru": "Введение", "pl": "Wprowadzenie",
                "tr": "Giriş", "vi": "Giới thiệu", "id": "Pendahuluan", "zh": "引言", "ja": "はじめに", "ko": "개요",
                "ar": "مقدمة", "hi": "परिचय"}


def introduction(lang: str | None) -> str:
    return INTRODUCTION.get((lang or "en").lower().split("-")[0], "Introduction")


INTRO_WORDS = sorted(set(INTRODUCTION.values()) | {"Intro", "Overview", "Einführung", "Überblick", "Présentation",
                                                   "Presentación", "Apresentação", "导言", "导论", "绪论", "緒論",
                                                   "概述", "序論", "序章", "도입", "서론"}, key=len, reverse=True)
INTRO_RE = re.compile(r"^(?:" + "|".join(re.escape(w) for w in INTRO_WORDS) + r")(?![^\W\d_])", re.I)


def is_introduction(title: str) -> bool:
    return bool(INTRO_RE.match(title.strip()))


FIGURE_ALT = _alt(FIGURE)
TABLE_ALT = _alt(TABLE)
CHAPTER_WORD_ALT = _alt(CHAPTER_WORDS)


_SPACED_SCRIPT = re.compile(r"[A-Za-zÀ-ɏͰ-ԯ؀-ۿऀ-ॿ가-힯]")


def head_re(*groups: list[str]) -> re.Pattern:
    """Text that starts with one of the words (case-insensitive). Words of scripts written with spaces must end
    at a word boundary ("Summary" but not "Summaryx"); Chinese and Japanese words need not."""
    words = [w for g in groups for w in g]
    spaced = [w for w in words if _SPACED_SCRIPT.match(w[-1])]
    other = [w for w in words if not _SPACED_SCRIPT.match(w[-1])]
    parts = []
    if spaced:
        parts.append(r"(?:" + _alt(spaced) + r")(?![^\W\d_])")
    if other:
        parts.append(r"(?:" + _alt(other) + r")")
    return re.compile(r"^(?:" + "|".join(parts) + r")", re.I)


def is_table_word(word: str) -> bool:
    return any(word.casefold() == t.casefold() for t in TABLE)
