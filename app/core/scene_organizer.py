"""Раскладка фотографий по сюжету: коты, природа, документы, счётчики…

Схема прежняя: scan() строит планы, apply() переносит файлы.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import organizer, photo_organizer, vision

ProgressCb = Callable[[int, int, str], None]

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}


@dataclass
class ScenePlan:
    """План переноса снимка в папку его категории."""

    source: Path
    target: Path
    category: str
    confidence: float

    @property
    def target_dir(self) -> Path:
        return self.target.parent


def scan(
    config_scenes: dict,
    classifier: vision.SceneClassifier | None = None,
    progress: ProgressCb | None = None,
    stop_flag: Callable[[], bool] | None = None,
) -> list[ScenePlan]:
    """Определяет сюжет каждого снимка и строит планы раскладки."""
    source = Path(config_scenes["source_folder"])
    root = Path(config_scenes["dest_root"])
    classifier = classifier or vision.SceneClassifier(
        threshold=config_scenes.get("threshold", vision.DEFAULT_THRESHOLD))

    photos = photo_organizer.list_photos(
        source, SUPPORTED_EXTS, config_scenes.get("recursive", True))
    total = len(photos)
    plans: list[ScenePlan] = []

    for i, photo in enumerate(photos, start=1):
        if stop_flag and stop_flag():
            break
        if progress:
            progress(i, total, photo.name)

        result = classifier.classify(photo)
        if result is None:
            continue
        folder = root / organizer._sanitize(result.category)
        plans.append(ScenePlan(
            source=photo,
            target=folder / photo.name,
            category=result.category,
            confidence=result.confidence,
        ))

    return plans


def apply(scene_plan: ScenePlan, action: str = "copy") -> tuple[str, Path]:
    """Копирует/перемещает снимок в папку категории."""
    import shutil

    source = scene_plan.source
    target_dir = scene_plan.target_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    existing = organizer.find_duplicate(target_dir, source)
    if existing is not None:
        if action == "move":
            import os

            os.remove(source)
        return organizer.STATUS_DUPLICATE, existing

    target = organizer._unique_path(scene_plan.target)
    if action == "move":
        shutil.move(str(source), str(target))
        return organizer.STATUS_MOVED, target
    shutil.copy2(str(source), str(target))
    return organizer.STATUS_COPIED, target


def group_by_category(plans: list[ScenePlan]) -> dict[str, list[ScenePlan]]:
    """Группирует планы по категориям — для показа в интерфейсе."""
    groups: dict[str, list[ScenePlan]] = {}
    for plan in plans:
        groups.setdefault(plan.category, []).append(plan)
    return groups
