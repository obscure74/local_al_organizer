"""Модуль 2: раскладка фотографий по годам и месяцам.

Дата съёмки берётся из EXIF (тег DateTimeOriginal). Если EXIF нет (скачанная
картинка, скриншот) — берётся дата изменения файла. Скриншоты по желанию
складываются в отдельную папку.

Как и с документами: сначала plan() (ничего не двигает), потом apply().
Распознавание лиц — отдельный модуль, будет добавлен позже.
"""
from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import organizer  # переиспользуем _sanitize и _unique_path

# Русские названия месяцев для папок: 01_Январь ... 12_Декабрь
_MONTHS_RU = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]

# EXIF-тег DateTimeOriginal (когда снят кадр)
_EXIF_DATETIME_ORIGINAL = 36867
_EXIF_DATETIME = 306  # запасной тег

# Признаки скриншотов по имени файла
_SCREENSHOT_RE = re.compile(
    r"(screenshot|screen[\s_-]?shot|снимок\s*экрана|scr[_-]?\d)", re.IGNORECASE)

ProgressCb = Callable[[int, int, str], None]


@dataclass
class PhotoPlan:
    source: Path
    target: Path
    date: datetime
    date_from_exif: bool          # True — дата из EXIF, False — из файла
    is_screenshot: bool

    @property
    def target_dir(self) -> Path:
        return self.target.parent


def list_photos(source: Path, extensions: set[str], recursive: bool) -> list[Path]:
    """Собирает пути к фото. recursive=True — включая вложенные папки."""
    if not source.is_dir():
        return []
    exts = {e.lower() for e in extensions}
    it = source.rglob("*") if recursive else source.iterdir()
    return sorted(p for p in it if p.is_file() and p.suffix.lower() in exts)


def get_photo_date(path: Path) -> tuple[datetime, bool]:
    """Возвращает (дата, из_exif). При отсутствии EXIF — время изменения файла."""
    exif_dt = _read_exif_date(path)
    if exif_dt is not None:
        return exif_dt, True
    return datetime.fromtimestamp(path.stat().st_mtime), False


def _read_exif_date(path: Path) -> datetime | None:
    """Пытается прочитать дату съёмки из EXIF через Pillow."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if not exif:
                return None
            raw = exif.get(_EXIF_DATETIME_ORIGINAL) or exif.get(_EXIF_DATETIME)
            # DateTimeOriginal часто лежит в под-IFD Exif
            if not raw:
                ifd = exif.get_ifd(0x8769)  # ExifIFD
                raw = ifd.get(_EXIF_DATETIME_ORIGINAL) if ifd else None
            if not raw:
                return None
            # Формат EXIF: "2017:04:12 15:30:00"
            return datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
    except Exception:
        return None


def is_screenshot(path: Path, date_from_exif: bool) -> bool:
    """Эвристика: скриншот определяется по имени файла."""
    return bool(_SCREENSHOT_RE.search(path.name))


def plan(source: Path, config_photo: dict) -> PhotoPlan:
    """Строит план раскладки для одного фото."""
    root = Path(config_photo["dest_root"])
    dt, from_exif = get_photo_date(source)
    screenshot = is_screenshot(source, from_exif)

    if screenshot and config_photo.get("separate_screenshots", True):
        target_dir = root / "Скриншоты" / str(dt.year)
    else:
        month_folder = f"{dt.month:02d}_{_MONTHS_RU[dt.month - 1]}"
        target_dir = root / str(dt.year) / month_folder

    # Имя оригинала сохраняем; уникальность и дедуп — в apply()
    target = target_dir / source.name
    return PhotoPlan(
        source=source, target=target, date=dt,
        date_from_exif=from_exif, is_screenshot=screenshot)


def apply(photo_plan: PhotoPlan, action: str = "copy") -> tuple[str, Path]:
    """Копирует/перемещает фото. Возвращает (статус, итоговый_путь).

    Если идентичное фото уже лежит в целевой папке — не дублируем; в режиме
    move лишний исходник удаляется. При ошибке переноса источник остаётся.
    """
    import shutil

    source = photo_plan.source
    target_dir = photo_plan.target_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    existing = organizer.find_duplicate(target_dir, source)
    if existing is not None:
        if action == "move":
            os.remove(source)
        return organizer.STATUS_DUPLICATE, existing

    target = organizer._unique_path(photo_plan.target)
    if action == "move":
        shutil.move(str(source), str(target))
        return organizer.STATUS_MOVED, target
    shutil.copy2(str(source), str(target))
    return organizer.STATUS_COPIED, target


def scan(
    config_photo: dict,
    progress: ProgressCb | None = None,
    stop_flag: Callable[[], bool] | None = None,
) -> list[PhotoPlan]:
    """Строит планы для всех фото в исходной папке."""
    source = Path(config_photo["source_folder"])
    photos = list_photos(
        source,
        set(config_photo["extensions"]),
        config_photo.get("recursive", True),
    )
    total = len(photos)
    plans: list[PhotoPlan] = []
    for i, path in enumerate(photos, start=1):
        if stop_flag and stop_flag():
            break
        if progress:
            progress(i, total, path.name)
        plans.append(plan(path, config_photo))
    return plans
