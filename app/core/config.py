"""Загрузка и сохранение настроек приложения.

Настройки хранятся в config.json рядом с приложением. При первом запуске
создаётся файл со значениями по умолчанию.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

# Корень проекта (папка, где лежит app/)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = BASE_DIR / "config.json"

# Настройки по умолчанию
DEFAULT_CONFIG: dict = {
    "ollama": {
        "host": "http://localhost:11434",
        "model": "qwen2.5:3b",
        # Таймаут одного запроса к модели, секунд
        "timeout": 120,
    },
    # Папка, которую сканируем (обычно "Загрузки")
    "source_folder": str(Path(os.path.expanduser("~")) / "Downloads"),
    # Куда раскладывать. {root} — корневая папка категории.
    "destinations": {
        # Рабочие документы: Рабочее/<Тип>/<ГГГГ-ММ>/<Компания>
        "work_root": str(Path(os.path.expanduser("~")) / "Organized" / "Рабочее"),
        # Личные файлы: Личное/<Тема>
        "personal_root": str(Path(os.path.expanduser("~")) / "Organized" / "Личное"),
        # Типовые файлы (видео, таблицы, архивы…): <files_root>/<Категория>/<Год>/
        "files_root": str(Path(os.path.expanduser("~")) / "Organized"),
    },
    # Тема оформления: "System" | "Light" | "Dark"
    "appearance": "System",
    # "move" — перемещать, "copy" — копировать (безопаснее для тестов)
    "action": "copy",
    # Обрабатывать все файлы в папке. False — только известные типы (см. filetypes).
    "process_all_files": True,
    # Максимум символов текста, отправляемых модели (экономим время/память)
    "max_text_chars": 4000,
    # --- Модуль 2: фотографии ---
    "photo": {
        # Откуда брать фото (можно указать внешний диск, напр. E:\DCIM)
        "source_folder": "",
        # Куда раскладывать: <dest_root>/<ГГГГ>/<ММ_Месяц>/
        "dest_root": str(Path(os.path.expanduser("~")) / "Organized" / "Фото"),
        # Искать во вложенных папках
        "recursive": True,
        # Складывать скриншоты в отдельную папку "Скриншоты"
        "separate_screenshots": True,
        # "move" или "copy"
        "action": "copy",
        "extensions": [
            ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif",
            ".webp", ".gif", ".heic",
        ],
    },
}


def load_config() -> dict:
    """Читает config.json. Если файла нет — создаёт со значениями по умолчанию.

    Недостающие ключи дополняются из DEFAULT_CONFIG (миграция при обновлениях).
    """
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return copy.deepcopy(DEFAULT_CONFIG)

    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        # Битый конфиг — не падаем, откатываемся к дефолту
        return copy.deepcopy(DEFAULT_CONFIG)

    return _merge_defaults(DEFAULT_CONFIG, data)


def save_config(config: dict) -> None:
    """Сохраняет настройки в config.json (UTF-8, читаемый вид)."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def _merge_defaults(defaults: dict, data: dict) -> dict:
    """Рекурсивно дополняет data недостающими ключами из defaults."""
    result = copy.deepcopy(defaults)
    for key, value in data.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_defaults(result[key], value)
        else:
            result[key] = value
    return result
