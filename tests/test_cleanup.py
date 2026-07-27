"""Тесты утилиты чистки склада от дублей (tools/cleanup_sklad.py)."""
import sys
from pathlib import Path

# tools/ не является пакетом — добавляем его в путь для импорта
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import cleanup_sklad  # noqa: E402


def test_canonical_segment_company():
    assert cleanup_sklad.canonical_segment("ООО_«ПромЭкоСистемы»") == "ПромЭкоСистемы"
    assert cleanup_sklad.canonical_segment("ООО_ПромЭкоСистемы") == "ПромЭкоСистемы"


def test_canonical_segment_doc_type():
    assert cleanup_sklad.canonical_segment("Проектная") == "Проектная_документация"
    assert cleanup_sklad.canonical_segment("Проектная_документация") == "Проектная_документация"


def test_canonical_segment_keeps_year():
    assert cleanup_sklad.canonical_segment("2024-04") == "2024-04"


def test_build_plan_finds_duplicate_folders(tmp_path):
    root = tmp_path / "Sklad"
    a = root / "Work" / "Проектная" / "2024-04" / "ООО_ПромЭкоСистемы"
    b = root / "Work" / "Проектная_документация" / "2024-04" / "ООО_«ПромЭкоСистемы»"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    (a / "doc.pdf").write_text("SAME", encoding="utf-8")
    (b / "doc.pdf").write_text("SAME", encoding="utf-8")  # дубликат по содержимому

    moves, dups, merges = cleanup_sklad.build_plan(root)
    assert len(dups) == 1          # один из двух — дубликат
    assert len(merges) >= 1        # папки-двойники сливаются


def test_build_plan_same_folder_duplicate(tmp_path):
    root = tmp_path / "Sklad"
    folder = root / "Photo" / "2024" / "03_Март"
    folder.mkdir(parents=True)
    (folder / "p.jpg").write_text("IMG", encoding="utf-8")
    (folder / "p_1.jpg").write_text("IMG", encoding="utf-8")  # тот же контент

    _, dups, _ = cleanup_sklad.build_plan(root)
    assert len(dups) == 1
