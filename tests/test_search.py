"""Тесты поиска по складу."""
from pathlib import Path

from app.core import search


def _seed(sample_config):
    work = Path(sample_config["destinations"]["work_root"]) / "Акт" / "2024-04"
    work.mkdir(parents=True)
    (work / "Акт_Ромашка_2024.pdf").write_text("x", encoding="utf-8")
    video = Path(sample_config["destinations"]["files_root"]) / "Видео" / "2024"
    video.mkdir(parents=True)
    (video / "otpusk.mp4").write_text("x", encoding="utf-8")


def test_search_by_name(sample_config):
    _seed(sample_config)
    results = search.search(sample_config, "Ромашка")
    assert [p.name for p in results] == ["Акт_Ромашка_2024.pdf"]


def test_search_by_category(sample_config):
    _seed(sample_config)
    results = search.search(sample_config, "", category="Видео")
    assert [p.name for p in results] == ["otpusk.mp4"]


def test_search_empty_when_no_match(sample_config):
    _seed(sample_config)
    assert search.search(sample_config, "несуществующее") == []


def test_roots_skip_missing_dirs(sample_config):
    # Папки ещё не созданы — корней нет, ошибок тоже
    assert search.roots_from_config(sample_config) == []
