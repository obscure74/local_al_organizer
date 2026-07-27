"""Оркестрация сканирования: чтение → классификация/категоризация → план.

Документы (PDF, Word, txt…) отдаются ИИ на анализ содержимого. Остальные типы
(видео, таблицы, аудио, архивы…) раскладываются по категории и году без ИИ —
это быстро и не грузит модель.

Не двигает файлы. Возвращает список планов (MovePlan) для предпросмотра.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from . import filetypes, organizer, readers
from .ai_client import OllamaClient
from .classifier import Classification, classify

# progress_callback(индекс, всего, имя_файла)
ProgressCb = Callable[[int, int, str], None]


def list_files(config: dict) -> list[Path]:
    """Файлы в исходной папке (без вложенных папок).

    Если process_all_files=False — только известные типы (см. filetypes).
    """
    source = Path(config["source_folder"])
    if not source.is_dir():
        return []
    files = [p for p in source.iterdir() if p.is_file()]
    if not config.get("process_all_files", True):
        known = filetypes.all_known_extensions()
        files = [p for p in files if p.suffix.lower() in known]
    return sorted(files)


def scan(
    config: dict,
    client: OllamaClient,
    progress: ProgressCb | None = None,
    stop_flag: Callable[[], bool] | None = None,
) -> list[organizer.MovePlan]:
    """Классифицирует/категоризует каждый файл, возвращает планы перемещения.

    progress   — колбэк для обновления прогресса в интерфейсе.
    stop_flag  — функция, возвращающая True, если пользователь прервал скан.
    """
    files = list_files(config)
    total = len(files)
    plans: list[organizer.MovePlan] = []
    max_chars = config.get("max_text_chars", 4000)

    for i, path in enumerate(files, start=1):
        if stop_flag and stop_flag():
            break
        if progress:
            progress(i, total, path.name)

        if filetypes.is_ai_document(path):
            # Документ — читаем текст и отдаём ИИ
            text = readers.extract_text(path, max_chars=max_chars)
            cls = classify(client, path.name, text)
        else:
            # Остальные типы — по категории и году, без ИИ
            cls = Classification(
                scope="typed",
                doc_type=filetypes.category_for(path),
                short_title=path.stem,
            )
        plans.append(organizer.plan(path, cls, config))

    return plans
