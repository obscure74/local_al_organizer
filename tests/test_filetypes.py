"""Тесты определения категории файла по расширению."""
from pathlib import Path

import pytest

from app.core import filetypes


@pytest.mark.parametrize("name,expected", [
    ("film.mp4", "Видео"),
    ("table.xlsx", "Таблицы"),
    ("archive.zip", "Архивы"),
    ("song.mp3", "Аудио"),
    ("book.epub", "Книги"),
    ("setup.exe", "Программы"),
    ("script.py", "Код"),
    ("photo.jpg", "Изображения"),
    ("report.pdf", "Документы"),
    ("mystery.xyz", "Прочее"),
])
def test_category_for(name, expected):
    assert filetypes.category_for(Path(name)) == expected


def test_category_is_case_insensitive():
    assert filetypes.category_for(Path("MOVIE.MP4")) == "Видео"


@pytest.mark.parametrize("name,is_doc", [
    ("report.pdf", True),
    ("notes.txt", True),
    ("letter.docx", True),
    ("film.mp4", False),
    ("table.xlsx", False),
])
def test_is_ai_document(name, is_doc):
    assert filetypes.is_ai_document(Path(name)) is is_doc
