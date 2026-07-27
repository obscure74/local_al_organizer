"""Общие фикстуры для тестов."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def sample_config(tmp_path: Path) -> dict:
    """Минимальная конфигурация со всеми папками во временной директории."""
    sklad = tmp_path / "Sklad"
    return {
        "source_folder": str(tmp_path / "Downloads"),
        "process_all_files": True,
        "max_text_chars": 4000,
        "destinations": {
            "work_root": str(sklad / "Work"),
            "personal_root": str(sklad / "Personal"),
            "files_root": str(sklad),
        },
        "photo": {"dest_root": str(sklad / "Photo")},
    }


@pytest.fixture
def make_file(tmp_path: Path):
    """Фабрика: создаёт файл в Downloads с заданным содержимым и возвращает путь."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir(exist_ok=True)

    def _make(name: str, content: str = "data") -> Path:
        path = downloads / name
        path.write_text(content, encoding="utf-8")
        return path

    return _make
