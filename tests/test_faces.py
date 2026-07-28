"""Тесты распознавания лиц и раскладки по людям.

Тесты, требующие ONNX-моделей, пропускаются, если модели не скачаны, —
набор остаётся зелёным на машине без них.
"""
from pathlib import Path

import pytest

from app.core import face_organizer, faces

requires_models = pytest.mark.skipif(
    not faces.models_ready(), reason="ONNX-модели распознавания не скачаны")


# --- Тесты, не требующие моделей ---

def test_similarity_identical_vectors():
    vec = [0.1, 0.2, 0.3, 0.4]
    assert faces.similarity(vec, vec) == pytest.approx(1.0)


def test_similarity_orthogonal_vectors():
    assert faces.similarity([1, 0], [0, 1]) == pytest.approx(0.0)


def test_similarity_zero_vector_is_safe():
    # Нулевой вектор не должен приводить к делению на ноль
    assert faces.similarity([0, 0], [1, 1]) == 0.0


def test_people_store_add_and_remove(tmp_path):
    store = faces.PeopleStore(path=tmp_path / "people.json")
    store.people.append(faces.Person(name="Я", embeddings=[[1.0, 0.0]]))
    store.save()

    assert store.get("Я") is not None
    assert store.get("я") is not None  # регистр не важен
    assert store.get("Мама") is None

    store.remove("Я")
    assert store.people == []


def test_people_store_persists(tmp_path):
    path = tmp_path / "people.json"
    store = faces.PeopleStore(path=path)
    store.people.append(faces.Person(name="Мама", embeddings=[[0.5, 0.5]]))
    store.save()

    reloaded = faces.PeopleStore(path=path)
    assert len(reloaded.people) == 1
    assert reloaded.people[0].name == "Мама"


def test_identify_picks_best_match(tmp_path):
    store = faces.PeopleStore(path=tmp_path / "people.json")
    store.people.append(faces.Person(name="Я", embeddings=[[1.0, 0.0, 0.0]]))
    store.people.append(faces.Person(name="Брат", embeddings=[[0.0, 1.0, 0.0]]))

    name, score = store.identify([0.99, 0.1, 0.0])
    assert name == "Я"
    assert score > faces.SIMILARITY_THRESHOLD


def test_identify_returns_none_below_threshold(tmp_path):
    store = faces.PeopleStore(path=tmp_path / "people.json")
    store.people.append(faces.Person(name="Я", embeddings=[[1.0, 0.0]]))

    name, _ = store.identify([0.0, 1.0])  # совсем непохожий вектор
    assert name is None


def test_read_image_missing_file(tmp_path):
    assert faces.read_image(tmp_path / "нет-такого.jpg") is None


def test_missing_models_lists_absent_files(monkeypatch, tmp_path):
    monkeypatch.setattr(faces, "DETECTOR_FILE", tmp_path / "detector.onnx")
    monkeypatch.setattr(faces, "RECOGNIZER_FILE", tmp_path / "recognizer.onnx")
    assert faces.missing_models() == ["detector.onnx", "recognizer.onnx"]
    assert faces.models_ready() is False


def test_group_by_person():
    plans = [
        face_organizer.FacePlan(Path("a.jpg"), Path("out/Я/a.jpg"), "Я", 1),
        face_organizer.FacePlan(Path("b.jpg"), Path("out/Я/b.jpg"), "Я", 2),
        face_organizer.FacePlan(Path("b.jpg"), Path("out/Мама/b.jpg"), "Мама", 2),
    ]
    groups = face_organizer.group_by_person(plans)
    assert set(groups) == {"Я", "Мама"}
    assert len(groups["Я"]) == 2


def test_face_apply_copy(tmp_path):
    src = tmp_path / "photo.jpg"
    src.write_text("IMG", encoding="utf-8")
    plan = face_organizer.FacePlan(src, tmp_path / "out" / "Я" / "photo.jpg", "Я", 1)

    status, target = face_organizer.apply(plan, action="copy")
    assert target.exists()
    assert src.exists()  # оригинал нужен для папок других людей
    assert status == "copied"


def test_face_apply_skips_duplicate(tmp_path):
    src = tmp_path / "photo.jpg"
    src.write_text("IMG", encoding="utf-8")
    plan = face_organizer.FacePlan(src, tmp_path / "out" / "Я" / "photo.jpg", "Я", 1)

    face_organizer.apply(plan, action="copy")
    status, _ = face_organizer.apply(plan, action="copy")
    assert status == "duplicate"


# --- Тесты, требующие скачанных моделей ---

@requires_models
def test_detect_faces_on_blank_image(tmp_path):
    from PIL import Image

    blank = tmp_path / "blank.png"
    Image.new("RGB", (200, 200), "white").save(blank)
    # На пустой картинке лиц быть не должно
    assert faces.detect_faces(blank) == 0


@requires_models
def test_embeddings_empty_for_blank_image(tmp_path):
    from PIL import Image

    blank = tmp_path / "blank.png"
    Image.new("RGB", (200, 200), "gray").save(blank)
    assert faces.face_embeddings(blank) == []
