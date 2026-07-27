"""Классификация документа с помощью локальной модели.

Формирует промпт, отправляет текст документа в Ollama и приводит ответ к
предсказуемой структуре, с которой дальше работает organizer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .ai_client import OllamaClient, OllamaError

SYSTEM_PROMPT = (
    "Ты — ассистент по разбору файлов. Анализируешь текст документа и "
    "классифицируешь его. Отвечаешь строго в формате JSON на русском языке, "
    "без пояснений и лишнего текста."
)

# Шаблон промпта. {filename} и {text} подставляются перед отправкой.
PROMPT_TEMPLATE = """Проанализируй документ и верни JSON со следующими полями:

- "scope": "work" если это рабочий/деловой документ (бухгалтерия, договоры,
  счета, акты, рабочие таблицы), или "personal" если это личный файл
  (заметки, обучение, статьи, полезные ссылки, хобби).
- "doc_type": выбери ТОЧНО ОДНО значение из списка (не придумывай своё).
  Для рабочих: "Акт", "Счёт", "Счёт-фактура", "УПД", "Договор", "Накладная",
  "Отчёт", "Проектная документация", "Таблица", "Письмо", "Прочее".
  Для личных: "Заметка", "Статья", "Инструкция", "Прочее".
- "topic": краткая тема для личных файлов (например "Нейросети",
  "Программирование", "Обучение", "Финансы"). Для рабочих — "".
- "company": название основной компании из документа (без ООО/ИП/кавычек)
  или "" если не определено.
- "counterparty": название второй компании-контрагента или "".
- "date": дата документа в формате ГГГГ-ММ-ДД или "" если не найдена.
- "short_title": очень короткое (2-4 слова) название сути документа.

Имя файла: {filename}

Текст документа:
\"\"\"
{text}
\"\"\"

Верни только JSON."""


@dataclass
class Classification:
    scope: str = "personal"          # "work" | "personal"
    doc_type: str = "Прочее"
    topic: str = ""
    company: str = ""
    counterparty: str = ""
    date: str = ""
    short_title: str = ""
    raw: dict = field(default_factory=dict)
    error: str = ""                  # заполняется, если классификация не удалась


def classify(client: OllamaClient, filename: str, text: str) -> Classification:
    """Классифицирует документ. При ошибке возвращает объект с полем error."""
    prompt = PROMPT_TEMPLATE.format(filename=filename, text=text or "(текст не извлечён)")

    try:
        data = client.generate_json(prompt, system=SYSTEM_PROMPT)
    except OllamaError as exc:
        return Classification(error=str(exc))

    scope = str(data.get("scope", "personal")).lower().strip()
    if scope not in ("work", "personal"):
        scope = "personal"

    return Classification(
        scope=scope,
        doc_type=_normalize_doc_type(_clean(data.get("doc_type"))),
        topic=_clean(data.get("topic")),
        company=normalize_company(_clean(data.get("company"))),
        counterparty=normalize_company(_clean(data.get("counterparty"))),
        date=_clean(data.get("date")),
        short_title=_clean(data.get("short_title")),
        raw=data,
    )


def _clean(value) -> str:
    """Приводит значение к строке и убирает мусорные пустышки."""
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in ("", "none", "null", "не определено", "неизвестно", "n/a"):
        return ""
    return text


# --- Нормализация названий (чтобы одна компания = одна папка) ---

# Кавычки всех видов, которые встречаются в названиях
_QUOTES = "«»„“”‟\"'`‘’"
# Правовые формы и типовые приставки, которые убираем для единообразия
_LEGAL_RE = re.compile(
    r"^(ООО|ОАО|ЗАО|АО|ПАО|НАО|ПАО|ИП|ГК|ТОО|ЧП|НПП|НПО|ПК|КФХ)\b[\s.\-]*",
    re.IGNORECASE,
)

# Канонические типы документов (для приведения регистра/вариантов)
_DOC_TYPE_CANON = {
    "акт": "Акт",
    "счёт": "Счёт", "счет": "Счёт",
    "счёт-фактура": "Счёт-фактура", "счет-фактура": "Счёт-фактура",
    "упд": "УПД",
    "договор": "Договор",
    "накладная": "Накладная",
    "отчёт": "Отчёт", "отчет": "Отчёт",
    "проектная документация": "Проектная документация",
    "проектная": "Проектная документация",
    "таблица": "Таблица",
    "письмо": "Письмо",
    "заметка": "Заметка",
    "статья": "Статья",
    "инструкция": "Инструкция",
    "прочее": "Прочее",
}


def normalize_company(name: str) -> str:
    """Приводит название компании к единому виду.

    Убирает кавычки и правовые формы (ООО, ИП, НПП…), чтобы «ООО "Ромашка"»
    и «Ромашка» попадали в одну папку.
    """
    if not name:
        return ""
    for q in _QUOTES:
        name = name.replace(q, "")
    name = re.sub(r"\s+", " ", name).strip()
    # Правовые формы могут идти подряд: «ООО НПП Полихим»
    prev = None
    while name != prev:
        prev = name
        name = _LEGAL_RE.sub("", name).strip()
    return name.strip(" _.-") or prev.strip(" _.-")


def _normalize_doc_type(value: str) -> str:
    """Снимает разнобой в регистре/вариантах типа документа."""
    if not value:
        return "Прочее"
    key = re.sub(r"\s+", " ", value).strip().lower()
    return _DOC_TYPE_CANON.get(key, value.strip().capitalize())
