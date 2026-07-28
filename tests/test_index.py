"""Тесты индекса метаданных."""
from pathlib import Path

import pytest

from app.core import index
from app.core.classifier import Classification


@pytest.fixture
def db(tmp_path):
    return index.MetadataIndex(path=tmp_path / "index.db")


def _record(path="C:/x/акт.pdf", **kwargs):
    return index.Record(path=path, **kwargs)


def test_add_and_count(db):
    db.add(_record(company="Ромашка"))
    assert db.count() == 1


def test_name_filled_from_path(db):
    record = _record(path="C:/склад/договор.pdf")
    assert record.name == "договор.pdf"


def test_add_is_idempotent(db):
    """Повторная запись того же пути обновляет строку, а не плодит дубли."""
    db.add(_record(company="Старое"))
    db.add(_record(company="Новое"))
    assert db.count() == 1
    assert db.search(company="Новое")[0].company == "Новое"


def test_search_by_company_ignores_case(db):
    """SQLite LOWER() не умеет кириллицу — проверяем свою функцию RULOWER."""
    db.add(_record(company="ПромЭкоСистемы"))
    assert len(db.search(company="промэкосистемы")) == 1
    assert len(db.search(company="ПРОМЭКОСИСТЕМЫ")) == 1


def test_search_by_text_covers_company_and_topic(db):
    db.add(_record(path="a.pdf", company="Полихим"))
    db.add(_record(path="b.pdf", topic="Нейросети"))
    assert len(db.search(text="полихим")) == 1
    assert len(db.search(text="нейросети")) == 1


def test_search_by_date_range(db):
    db.add(_record(path="a.pdf", doc_date="2024-03-15"))
    db.add(_record(path="b.pdf", doc_date="2024-07-01"))
    found = db.search(date_from="2024-01-01", date_to="2024-04-01")
    assert [Path(r.path).name for r in found] == ["a.pdf"]


def test_search_combines_filters(db):
    db.add(_record(path="a.pdf", company="Ромашка", doc_type="Акт"))
    db.add(_record(path="b.pdf", company="Ромашка", doc_type="Счёт"))
    assert len(db.search(company="Ромашка")) == 2
    assert len(db.search(company="Ромашка", doc_type="Акт")) == 1


def test_empty_search_returns_everything(db):
    db.add(_record(path="a.pdf"))
    db.add(_record(path="b.pdf"))
    assert len(db.search()) == 2


def test_distinct_skips_empty_values(db):
    db.add(_record(path="a.pdf", company="Ромашка"))
    db.add(_record(path="b.pdf", company=""))
    assert db.distinct("company") == ["Ромашка"]


def test_distinct_rejects_unknown_column(db):
    with pytest.raises(ValueError, match="Недопустимая колонка"):
        db.distinct("path; DROP TABLE files")


def test_remove_missing(db, tmp_path):
    real = tmp_path / "real.pdf"
    real.write_text("x", encoding="utf-8")
    db.add(_record(path=str(real)))
    db.add(_record(path=str(tmp_path / "исчез.pdf")))

    assert db.remove_missing() == 1
    assert db.count() == 1


def test_record_from_classification(tmp_path):
    file = tmp_path / "akt.pdf"
    file.write_text("x", encoding="utf-8")
    classification = Classification(
        scope="work", doc_type="Акт", company="Ромашка",
        counterparty="Василёк", date="2024-04-12")

    record = index.record_from_classification(file, classification, category="Документы")
    assert record.company == "Ромашка"
    assert record.counterparty == "Василёк"
    assert record.doc_date == "2024-04-12"
    assert record.category == "Документы"


# --- Восстановление метаданных из структуры папок ---

def test_record_from_work_path():
    roots = {"work": Path("D:/Sklad/Work")}
    path = Path("D:/Sklad/Work/Акт/2024-04/ПромЭкоСистемы/акт_1.pdf")

    record = index.record_from_path(path, roots)
    assert record.scope == "work"
    assert record.doc_type == "Акт"
    assert record.company == "ПромЭкоСистемы"
    assert record.doc_date == "2024-04-01"


def test_record_from_photo_path():
    roots = {"photo": Path("D:/Sklad/Photo")}
    path = Path("D:/Sklad/Photo/2017/04_Апрель/foto.jpg")

    record = index.record_from_path(path, roots)
    assert record.scope == "photo"
    assert record.doc_date == "2017-04-01"


def test_record_from_face_path():
    roots = {"face": Path("D:/Sklad/Люди")}
    path = Path("D:/Sklad/Люди/Мама/foto.jpg")

    record = index.record_from_path(path, roots)
    assert record.person == "Мама"


def test_record_from_typed_path():
    roots = {"typed": Path("D:/Sklad")}
    path = Path("D:/Sklad/Видео/2024/film.mp4")

    record = index.record_from_path(path, roots)
    assert record.category == "Видео"
    assert record.doc_date == "2024-01-01"


def test_record_from_path_outside_roots():
    roots = {"work": Path("D:/Sklad/Work")}
    assert index.record_from_path(Path("C:/Другое/файл.pdf"), roots) is None


def test_rebuild_from_disk(tmp_path):
    sklad = tmp_path / "Sklad"
    work = sklad / "Work" / "Акт" / "2024-04" / "Ромашка"
    work.mkdir(parents=True)
    (work / "akt.pdf").write_text("x", encoding="utf-8")
    photo = sklad / "Photo" / "2017" / "04_Апрель"
    photo.mkdir(parents=True)
    (photo / "foto.jpg").write_text("x", encoding="utf-8")

    config = {
        "destinations": {"work_root": str(sklad / "Work"),
                         "personal_root": str(sklad / "Personal"),
                         "files_root": str(sklad)},
        "photo": {"dest_root": str(sklad / "Photo")},
    }
    db = index.MetadataIndex(path=tmp_path / "index.db")
    count = index.rebuild_from_disk(config, db)

    assert count == 2
    assert len(db.search(company="Ромашка")) == 1
    assert len(db.search(date_from="2017-01-01", date_to="2017-12-31")) == 1
