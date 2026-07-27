"""Тесты истории операций и отката (Undo)."""
from app.core import organizer
from app.core.classifier import Classification
from app.core.history import Entry, HistoryStore


def _cls():
    return Classification(scope="work", doc_type="Акт", company="Ромашка", date="2024-04-12")


def test_undo_move_restores_source(tmp_path, sample_config, make_file):
    store = HistoryStore(path=tmp_path / "history.json")
    f = make_file("akt.pdf", "DATA")
    status, target = organizer.apply(organizer.plan(f, _cls(), sample_config), action="move")
    store.add("docs", "move", [Entry(status=status, source=str(f), target=str(target))])

    stats = store.undo(store.recent()[0].id)
    assert stats["restored"] == 1
    assert f.exists() and not target.exists()


def test_undo_copy_removes_copy(tmp_path, sample_config, make_file):
    store = HistoryStore(path=tmp_path / "history.json")
    f = make_file("akt.pdf", "DATA")
    status, target = organizer.apply(organizer.plan(f, _cls(), sample_config), action="copy")
    store.add("docs", "copy", [Entry(status=status, source=str(f), target=str(target))])

    stats = store.undo(store.recent()[0].id)
    assert stats["removed"] == 1
    assert f.exists() and not target.exists()


def test_history_persists(tmp_path):
    path = tmp_path / "history.json"
    store = HistoryStore(path=path)
    store.add("docs", "move", [Entry(status="moved", source="a", target="b")])
    assert path.exists()
    # Новый экземпляр видит сохранённые данные
    assert len(HistoryStore(path=path).batches) == 1


def test_undo_twice_is_safe(tmp_path, sample_config, make_file):
    store = HistoryStore(path=tmp_path / "history.json")
    f = make_file("akt.pdf", "DATA")
    status, target = organizer.apply(organizer.plan(f, _cls(), sample_config), action="move")
    batch = store.add("docs", "move", [Entry(status=status, source=str(f), target=str(target))])
    store.undo(batch.id)
    second = store.undo(batch.id)  # повторный откат ничего не ломает
    assert second["restored"] == 0
