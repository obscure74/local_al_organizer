"""Раскладка фотографий по людям на основе распознавания лиц.

Схема та же, что и в остальных модулях: сначала scan() строит планы
(ничего не двигает), затем apply() переносит файлы.

Особенность: на одном снимке может быть несколько знакомых людей, поэтому
такое фото попадает в папку каждого из них. По этой причине по умолчанию
используется режим «копировать», иначе оригинал достался бы только первому.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import faces, organizer, photo_organizer

# Папки для фото, которые не удалось отнести к конкретному человеку
UNKNOWN_FOLDER = "Неизвестные"
NO_FACES_FOLDER = "Без_людей"

ProgressCb = Callable[[int, int, str], None]


@dataclass
class FacePlan:
    """План переноса одного файла в папку одного человека."""

    source: Path
    target: Path
    person: str          # имя человека, UNKNOWN_FOLDER или NO_FACES_FOLDER
    face_count: int      # сколько лиц найдено на снимке

    @property
    def target_dir(self) -> Path:
        return self.target.parent


def scan(
    config_faces: dict,
    store: faces.PeopleStore,
    progress: ProgressCb | None = None,
    stop_flag: Callable[[], bool] | None = None,
) -> list[FacePlan]:
    """Определяет людей на каждом фото и строит планы раскладки.

    Одно фото с несколькими знакомыми людьми даёт несколько планов — по
    одному на человека.
    """
    source = Path(config_faces["source_folder"])
    root = Path(config_faces["dest_root"])
    threshold = config_faces.get("threshold", faces.SIMILARITY_THRESHOLD)
    separate_no_faces = config_faces.get("separate_no_faces", True)

    photos = photo_organizer.list_photos(
        source,
        {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"},
        config_faces.get("recursive", True),
    )
    total = len(photos)
    plans: list[FacePlan] = []

    for i, photo in enumerate(photos, start=1):
        if stop_flag and stop_flag():
            break
        if progress:
            progress(i, total, photo.name)

        names, face_count = faces.identify_photo(photo, store, threshold)

        if face_count == 0:
            # Лиц нет: скриншот, картинка из интернета, пейзаж
            if not separate_no_faces:
                continue
            targets = [NO_FACES_FOLDER]
        elif not names:
            # Лица есть, но никого не узнали
            targets = [UNKNOWN_FOLDER]
        else:
            targets = names

        for person in targets:
            folder = root / organizer._sanitize(person)
            plans.append(FacePlan(
                source=photo,
                target=folder / photo.name,
                person=person,
                face_count=face_count,
            ))

    return plans


def apply(face_plan: FacePlan, action: str = "copy") -> tuple[str, Path]:
    """Копирует/перемещает фото в папку человека.

    Возвращает (статус, итоговый путь) — как и остальные модули.
    """
    import shutil

    source = face_plan.source
    target_dir = face_plan.target_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    existing = organizer.find_duplicate(target_dir, source)
    if existing is not None:
        # Фото уже в этой папке — не дублируем. Источник не трогаем: он может
        # понадобиться для папки другого человека с этого же снимка.
        return organizer.STATUS_DUPLICATE, existing

    target = organizer._unique_path(face_plan.target)
    if action == "move":
        shutil.move(str(source), str(target))
        return organizer.STATUS_MOVED, target
    shutil.copy2(str(source), str(target))
    return organizer.STATUS_COPIED, target


def group_by_person(plans: list[FacePlan]) -> dict[str, list[FacePlan]]:
    """Группирует планы по людям — для наглядного показа в интерфейсе."""
    groups: dict[str, list[FacePlan]] = {}
    for plan in plans:
        groups.setdefault(plan.person, []).append(plan)
    return groups
