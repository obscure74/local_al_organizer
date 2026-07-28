"""Тесты распознавания сюжета фотографий (CLIP).

Тесты, требующие скачанной модели, пропускаются, если её нет.
"""
from pathlib import Path

import pytest

from app.core import scene_organizer, vision

requires_models = pytest.mark.skipif(
    not vision.models_ready(), reason="Модель CLIP не скачана")


# --- Не требуют модели ---

def test_default_categories_have_prompts():
    assert vision.DEFAULT_CATEGORIES
    for name, prompts in vision.DEFAULT_CATEGORIES.items():
        assert prompts, f"У категории «{name}» нет описаний"
        assert all(isinstance(p, str) and p for p in prompts)


def test_expected_categories_present():
    for name in ("Коты", "Природа", "Документы", "Счётчики", "Скриншоты"):
        assert name in vision.DEFAULT_CATEGORIES


def test_load_categories_falls_back_to_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(vision, "CATEGORIES_PATH", tmp_path / "нет.json")
    assert vision.load_categories() == {
        k: list(v) for k, v in vision.DEFAULT_CATEGORIES.items()}


def test_load_categories_survives_broken_file(tmp_path, monkeypatch):
    broken = tmp_path / "categories.json"
    broken.write_text("{это не json", encoding="utf-8")
    monkeypatch.setattr(vision, "CATEGORIES_PATH", broken)
    assert "Коты" in vision.load_categories()


def test_save_and_load_categories(tmp_path, monkeypatch):
    path = tmp_path / "categories.json"
    monkeypatch.setattr(vision, "CATEGORIES_PATH", path)

    vision.save_categories({"Мемы": ["a funny meme image"]})
    assert vision.load_categories() == {"Мемы": ["a funny meme image"]}


def test_missing_models_lists_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(vision, "VISION_FILE", tmp_path / "v.onnx")
    monkeypatch.setattr(vision, "TEXT_FILE", tmp_path / "t.onnx")
    monkeypatch.setattr(vision, "TOKENIZER_FILE", tmp_path / "tok.json")
    assert vision.missing_models() == ["v.onnx", "t.onnx", "tok.json"]
    assert vision.models_ready() is False


def test_scene_result_confidence_flag():
    confident = vision.SceneResult(category="Коты", confidence=0.9)
    unsure = vision.SceneResult(category=vision.UNSURE_FOLDER, confidence=0.1)
    assert confident.is_confident is True
    assert unsure.is_confident is False


def test_group_by_category():
    plans = [
        scene_organizer.ScenePlan(Path("a.jpg"), Path("out/Коты/a.jpg"), "Коты", 0.9),
        scene_organizer.ScenePlan(Path("b.jpg"), Path("out/Коты/b.jpg"), "Коты", 0.8),
        scene_organizer.ScenePlan(Path("c.jpg"), Path("out/Природа/c.jpg"), "Природа", 0.7),
    ]
    groups = scene_organizer.group_by_category(plans)
    assert set(groups) == {"Коты", "Природа"}
    assert len(groups["Коты"]) == 2


def test_scene_apply_copy(tmp_path):
    source = tmp_path / "photo.jpg"
    source.write_text("IMG", encoding="utf-8")
    plan = scene_organizer.ScenePlan(
        source, tmp_path / "out" / "Коты" / "photo.jpg", "Коты", 0.9)

    status, target = scene_organizer.apply(plan, action="copy")
    assert status == "copied"
    assert target.exists() and source.exists()


def test_scene_apply_detects_duplicate(tmp_path):
    source = tmp_path / "photo.jpg"
    source.write_text("IMG", encoding="utf-8")
    plan = scene_organizer.ScenePlan(
        source, tmp_path / "out" / "Коты" / "photo.jpg", "Коты", 0.9)

    scene_organizer.apply(plan, action="copy")
    status, _ = scene_organizer.apply(plan, action="copy")
    assert status == "duplicate"


# --- Требуют скачанной модели ---

@requires_models
def test_classifier_prepares_text_embeddings():
    classifier = vision.SceneClassifier({"Коты": ["a photo of a cat"],
                                         "Природа": ["a landscape photo"]})
    classifier.prepare()
    # 512 — размерность эмбеддинга CLIP ViT-B/32
    assert classifier._text_embeddings.shape == (2, 512)


@requires_models
def test_classify_returns_none_for_broken_file(tmp_path):
    broken = tmp_path / "broken.jpg"
    broken.write_text("не картинка", encoding="utf-8")

    classifier = vision.SceneClassifier({"Коты": ["a photo of a cat"]})
    assert classifier.classify(broken) is None


@requires_models
def test_classify_recognizes_solid_color_as_unsure(tmp_path):
    """Однотонный квадрат ни на что не похож — уходит в «Разное»."""
    from PIL import Image

    blank = tmp_path / "blank.png"
    Image.new("RGB", (300, 300), (128, 128, 128)).save(blank)

    classifier = vision.SceneClassifier(
        {"Коты": ["a photo of a cat"], "Природа": ["a landscape photo of nature"],
         "Еда": ["a photo of food"]}, threshold=0.9)
    result = classifier.classify(blank)
    assert result.category == vision.UNSURE_FOLDER


@requires_models
def test_classify_returns_confidence_range(tmp_path):
    from PIL import Image

    image = tmp_path / "img.png"
    Image.new("RGB", (300, 300), (60, 120, 200)).save(image)

    classifier = vision.SceneClassifier({"Небо": ["a photo of blue sky"],
                                         "Коты": ["a photo of a cat"]})
    result = classifier.classify(image)
    assert 0.0 <= result.confidence <= 1.0
    assert result.category in {"Небо", "Коты", vision.UNSURE_FOLDER}
