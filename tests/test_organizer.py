"""Тесты построения путей, дедупликации и режимов move/copy."""
from pathlib import Path

from app.core import organizer
from app.core.classifier import Classification


def _work_cls():
    return Classification(scope="work", doc_type="Акт", company="Ромашка",
                          counterparty="Василёк", date="2024-04-12")


def test_work_path(sample_config, make_file):
    f = make_file("akt.pdf")
    plan = organizer.plan(f, _work_cls(), sample_config)
    rel = plan.target.relative_to(sample_config["destinations"]["work_root"])
    assert rel == Path("Акт/2024-04/Ромашка/Акт_Ромашка_Василёк_2024-04-12.pdf")


def test_personal_path(sample_config, make_file):
    f = make_file("note.txt")
    cls = Classification(scope="personal", doc_type="Заметка", topic="Нейросети",
                         short_title="Полезные модели")
    plan = organizer.plan(f, cls, sample_config)
    rel = plan.target.relative_to(sample_config["destinations"]["personal_root"])
    assert rel == Path("Нейросети/Полезные_модели.txt")


def test_typed_path(sample_config, make_file):
    f = make_file("film.mp4")
    cls = Classification(scope="typed", doc_type="Видео", short_title="film")
    plan = organizer.plan(f, cls, sample_config)
    assert "Видео" in str(plan.target)
    assert plan.target.name == "film.mp4"


def test_copy_keeps_source(sample_config, make_file):
    f = make_file("akt.pdf", "CONTENT")
    status, target = organizer.apply(organizer.plan(f, _work_cls(), sample_config), action="copy")
    assert status == organizer.STATUS_COPIED
    assert f.exists() and target.exists()


def test_move_removes_source(sample_config, make_file):
    f = make_file("akt.pdf", "CONTENT")
    status, target = organizer.apply(organizer.plan(f, _work_cls(), sample_config), action="move")
    assert status == organizer.STATUS_MOVED
    assert not f.exists() and target.exists()


def test_duplicate_not_copied_twice(sample_config, make_file):
    f = make_file("akt.pdf", "SAME")
    organizer.apply(organizer.plan(f, _work_cls(), sample_config), action="copy")
    status, _ = organizer.apply(organizer.plan(f, _work_cls(), sample_config), action="copy")
    assert status == organizer.STATUS_DUPLICATE


def test_move_duplicate_removes_source(sample_config, make_file):
    f1 = make_file("akt.pdf", "SAME")
    organizer.apply(organizer.plan(f1, _work_cls(), sample_config), action="copy")
    f2 = make_file("akt_copy.pdf", "SAME")  # то же содержимое
    status, _ = organizer.apply(organizer.plan(f2, _work_cls(), sample_config), action="move")
    assert status == organizer.STATUS_DUPLICATE
    assert not f2.exists()  # лишний оригинал удалён


def test_different_content_same_name_gets_suffix(sample_config, make_file):
    f1 = make_file("akt.pdf", "AAA")
    _, t1 = organizer.apply(organizer.plan(f1, _work_cls(), sample_config), action="copy")
    f2 = make_file("akt2.pdf", "BBB")  # другое содержимое, но имя цели совпадёт
    _, t2 = organizer.apply(organizer.plan(f2, _work_cls(), sample_config), action="copy")
    assert t1 != t2
    assert t2.stem.endswith("_1")


def test_illegal_chars_sanitized(sample_config, make_file):
    f = make_file("doc.pdf")
    cls = Classification(scope="work", doc_type="Акт", company='Ро/ма:шка*')
    plan = organizer.plan(f, cls, sample_config)
    assert not any(ch in plan.target.parent.name for ch in '/:*')
