"""Определение категории файла по расширению.

Документы разбираются ИИ по содержимому (см. classifier), а остальные типы
(видео, таблицы, аудио, архивы…) раскладываются просто по категории и году —
для них ИИ не нужен, достаточно узнать тип.
"""
from __future__ import annotations

from pathlib import Path

# Категория -> набор расширений (в нижнем регистре, с точкой)
CATEGORIES: dict[str, set[str]] = {
    "Документы": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt", ".pages"},
    "Таблицы": {".xls", ".xlsx", ".xlsm", ".csv", ".ods", ".tsv"},
    "Презентации": {".ppt", ".pptx", ".odp", ".key"},
    "Изображения": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
                    ".webp", ".heic", ".svg", ".raw", ".cr2", ".nef"},
    "Видео": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg"},
    "Аудио": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus"},
    "Архивы": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "Программы": {".exe", ".msi", ".apk", ".dmg", ".appimage", ".deb"},
    "Код": {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".json",
            ".ipynb", ".java", ".cpp", ".c", ".h", ".go", ".rs", ".sql", ".sh", ".yml", ".yaml"},
    "Книги": {".epub", ".fb2", ".mobi", ".djvu", ".azw3"},
    "Торренты": {".torrent"},
}

# Расширения документов, которые анализирует ИИ (текстовое содержимое)
AI_DOCUMENT_EXTS: set[str] = {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf"}

# Быстрый обратный индекс: расширение -> категория
_EXT_TO_CATEGORY: dict[str, str] = {
    ext: cat for cat, exts in CATEGORIES.items() for ext in exts
}


def category_for(path: Path) -> str:
    """Категория файла по расширению. Неизвестное расширение -> 'Прочее'."""
    return _EXT_TO_CATEGORY.get(path.suffix.lower(), "Прочее")


def is_ai_document(path: Path) -> bool:
    """True, если файл нужно отдавать ИИ на анализ содержимого."""
    return path.suffix.lower() in AI_DOCUMENT_EXTS


def all_known_extensions() -> set[str]:
    return set(_EXT_TO_CATEGORY)
