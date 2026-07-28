"""Тесты поиска визуально одинаковых изображений."""
from pathlib import Path

import pytest

from app.core import duplicates

# Модуль опирается на OpenCV — без него тесты изображений не имеют смысла
cv2 = pytest.importorskip("cv2")
Image = pytest.importorskip("PIL.Image")


def _photo(path: Path, size=(240, 240), quality=95, seed=0):
    """Создаёт фотоподобное изображение с текстурой.

    Именно текстура (а не гладкий градиент) даёт устойчивый перцептивный
    хеш — как на настоящих фотографиях. На однотонных и плавных картинках
    pHash нестабилен по своей природе.
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    base = rng.integers(0, 255, (240, 240, 3), dtype=np.uint8)
    image = Image.fromarray(base, "RGB").resize(size)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in (".jpg", ".jpeg"):
        image.save(path, quality=quality)
    else:
        image.save(path)
    return path


def test_hamming_distance():
    assert duplicates.hamming_distance(0b1010, 0b1010) == 0
    assert duplicates.hamming_distance(0b1010, 0b1011) == 1
    assert duplicates.hamming_distance(0b0000, 0b1111) == 4


def test_phash_stable_for_same_image(tmp_path):
    a = _photo(tmp_path / "a.png")
    assert duplicates.perceptual_hash(a) == duplicates.perceptual_hash(a)


def test_phash_survives_recompression(tmp_path):
    """Пережатая копия должна остаться визуальным дублем."""
    original = _photo(tmp_path / "orig.jpg", quality=95)
    recompressed = _photo(tmp_path / "small.jpg", size=(120, 120), quality=40)

    distance = duplicates.hamming_distance(
        duplicates.perceptual_hash(original), duplicates.perceptual_hash(recompressed))
    assert distance <= duplicates.NORMAL


def test_phash_none_for_non_image(tmp_path):
    broken = tmp_path / "not_image.jpg"
    broken.write_text("это не картинка", encoding="utf-8")
    assert duplicates.perceptual_hash(broken) is None


def test_find_groups_detects_duplicate(tmp_path):
    folder = tmp_path / "photos"
    _photo(folder / "original.jpg", quality=95)
    _photo(folder / "copy.jpg", size=(150, 150), quality=50)   # тот же кадр
    _photo(folder / "other.jpg", seed=99)                    # другая картинка

    groups = duplicates.find_groups(folder, threshold=duplicates.NORMAL)
    assert len(groups) == 1
    names = {f.path.name for f in groups[0].files}
    assert names == {"original.jpg", "copy.jpg"}


def test_best_keeps_highest_resolution(tmp_path):
    folder = tmp_path / "photos"
    _photo(folder / "big.jpg", size=(400, 400), quality=95)
    _photo(folder / "small.jpg", size=(100, 100), quality=95)

    groups = duplicates.find_groups(folder, threshold=duplicates.LOOSE)
    assert groups
    assert groups[0].best.path.name == "big.jpg"
    assert [f.path.name for f in groups[0].extras] == ["small.jpg"]


def test_exact_copies_flagged(tmp_path):
    import shutil

    folder = tmp_path / "photos"
    original = _photo(folder / "a.png")
    shutil.copy2(original, folder / "b.png")

    groups = duplicates.find_groups(folder, threshold=duplicates.STRICT)
    assert groups[0].exact is True


def test_no_groups_for_unique_images(tmp_path):
    folder = tmp_path / "photos"
    _photo(folder / "one.png", seed=1)
    _photo(folder / "two.png", seed=77)

    assert duplicates.find_groups(folder, threshold=duplicates.STRICT) == []


def test_move_to_trash_preserves_structure(tmp_path):
    root = tmp_path / "Sklad"
    nested = root / "2024" / "Март"
    nested.mkdir(parents=True)
    victim = nested / "dup.jpg"
    victim.write_text("x", encoding="utf-8")

    trash = root / "_Дубликаты_тест"
    moved = duplicates.move_to_trash([victim], trash, root)

    assert moved == 1
    assert not victim.exists()
    assert (trash / "2024" / "Март" / "dup.jpg").exists()


def test_wasted_bytes(tmp_path):
    folder = tmp_path / "photos"
    _photo(folder / "big.jpg", size=(400, 400))
    _photo(folder / "small.jpg", size=(100, 100))

    groups = duplicates.find_groups(folder, threshold=duplicates.LOOSE)
    assert groups[0].wasted_bytes == groups[0].extras[0].size


def test_list_images_filters_by_extension(tmp_path):
    (tmp_path / "photo.jpg").write_text("x", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")

    found = duplicates.list_images(tmp_path)
    assert [p.name for p in found] == ["photo.jpg"]
