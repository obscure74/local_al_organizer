"""Тесты раскладки фотографий по дате и определения скриншотов."""
from pathlib import Path

from PIL import Image

from app.core import photo_organizer


def _make_image(path: Path, color: str = "red"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (10, 10), color).save(path)


def test_date_fallback_to_mtime(tmp_path):
    img = tmp_path / "photo.jpg"
    _make_image(img)
    dt, from_exif = photo_organizer.get_photo_date(img)
    assert from_exif is False  # у сгенерированной картинки нет EXIF
    assert dt is not None


def test_screenshot_detection_by_name():
    assert photo_organizer.is_screenshot(Path("Screenshot_2020.png"), False) is True
    assert photo_organizer.is_screenshot(Path("снимок экрана 5.png"), False) is True
    assert photo_organizer.is_screenshot(Path("IMG_1234.jpg"), True) is False


def test_plan_routes_by_year_month(tmp_path):
    img = tmp_path / "src" / "photo.jpg"
    _make_image(img)
    cfg = {"dest_root": str(tmp_path / "out"), "separate_screenshots": True}
    plan = photo_organizer.plan(img, cfg)
    parts = plan.target.relative_to(tmp_path / "out").parts
    assert len(parts[0]) == 4 and parts[0].isdigit()      # год
    assert parts[1][:2].isdigit() and "_" in parts[1]     # 07_Июль


def test_plan_routes_screenshot_separately(tmp_path):
    img = tmp_path / "src" / "Screenshot_1.png"
    _make_image(img, "blue")
    cfg = {"dest_root": str(tmp_path / "out"), "separate_screenshots": True}
    plan = photo_organizer.plan(img, cfg)
    assert "Скриншоты" in plan.target.parts


def test_scan_finds_nested_photos(tmp_path):
    _make_image(tmp_path / "src" / "a.jpg")
    _make_image(tmp_path / "src" / "nested" / "b.png")
    cfg = {
        "source_folder": str(tmp_path / "src"),
        "dest_root": str(tmp_path / "out"),
        "recursive": True,
        "separate_screenshots": True,
        "extensions": [".jpg", ".png"],
    }
    plans = photo_organizer.scan(cfg)
    assert len(plans) == 2
