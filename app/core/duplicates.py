"""Поиск визуально одинаковых изображений.

Обычная дедупликация (см. organizer.find_duplicate) сравнивает файлы побайтно
и находит только точные копии. Но одна и та же фотография, пересохранённая
с другим качеством, уменьшенная или переименованная, даёт другие байты —
и остаётся в архиве вторым экземпляром.

Здесь используется перцептивный хеш (pHash): картинка сводится к 64-битному
«отпечатку», который почти не меняется при пережатии и смене размера.
Похожесть измеряется расстоянием Хэмминга — числом различающихся битов.

Ограничение: pHash не распознаёт сильно обрезанные или повёрнутые копии —
для них отпечаток получается другим.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import organizer

# Порог различия в битах (из 64). Чем больше — тем «мягче» поиск.
STRICT = 2       # практически идентичные
NORMAL = 8       # пережатые, изменённого размера
LOOSE = 14       # похожие (риск ложных срабатываний)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp", ".gif"}

ProgressCb = Callable[[int, int, str], None]


@dataclass
class DuplicateFile:
    """Файл-кандидат с характеристиками, по которым выбирают лучший экземпляр."""

    path: Path
    size: int          # размер файла в байтах
    pixels: int        # разрешение (ширина × высота)
    phash: int

    @property
    def megapixels(self) -> float:
        return self.pixels / 1_000_000


@dataclass
class DuplicateGroup:
    """Группа визуально одинаковых изображений."""

    files: list[DuplicateFile]
    exact: bool = False     # True — файлы совпадают побайтно

    @property
    def best(self) -> DuplicateFile:
        """Лучший экземпляр: наибольшее разрешение, затем размер файла."""
        return max(self.files, key=lambda f: (f.pixels, f.size))

    @property
    def extras(self) -> list[DuplicateFile]:
        """Все, кроме лучшего, — кандидаты на удаление."""
        best = self.best
        return [f for f in self.files if f.path != best.path]

    @property
    def wasted_bytes(self) -> int:
        return sum(f.size for f in self.extras)


def perceptual_hash(path: Path) -> int | None:
    """Считает 64-битный перцептивный хеш изображения (pHash через DCT).

    Возвращает None, если файл не удалось прочитать как изображение.
    """
    import cv2
    import numpy as np

    from .faces import read_image  # чтение с поддержкой кириллицы в путях

    image = read_image(path)
    if image is None:
        return None

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # 32×32 — рабочий размер для DCT
    small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(np.float32(small))
    # Низкочастотный блок 8×8 несёт основную структуру изображения
    block = dct[:8, :8].flatten()
    # Первый коэффициент (яркость) исключаем — он мешает сравнению
    median = np.median(block[1:])

    bits = 0
    for i, value in enumerate(block):
        if value > median:
            bits |= 1 << i
    return bits


def hamming_distance(first: int, second: int) -> int:
    """Число различающихся битов в двух хешах (0 — отпечатки идентичны)."""
    return bin(first ^ second).count("1")


def list_images(folder: Path, recursive: bool = True) -> list[Path]:
    """Все изображения в папке."""
    if not folder.is_dir():
        return []
    it = folder.rglob("*") if recursive else folder.iterdir()
    return sorted(p for p in it if p.is_file() and p.suffix.lower() in IMAGE_EXTS)


def _describe(path: Path) -> DuplicateFile | None:
    """Собирает характеристики файла: размер, разрешение, отпечаток."""
    from .faces import read_image

    phash = perceptual_hash(path)
    if phash is None:
        return None
    image = read_image(path)
    if image is None:
        return None
    height, width = image.shape[:2]
    try:
        size = path.stat().st_size
    except OSError:
        return None
    return DuplicateFile(path=path, size=size, pixels=width * height, phash=phash)


def find_groups(
    folder: Path,
    threshold: int = NORMAL,
    recursive: bool = True,
    progress: ProgressCb | None = None,
    stop_flag: Callable[[], bool] | None = None,
) -> list[DuplicateGroup]:
    """Находит группы визуально одинаковых изображений.

    threshold — допустимое различие в битах (см. STRICT / NORMAL / LOOSE).
    """
    images = list_images(folder, recursive)
    total = len(images)

    described: list[DuplicateFile] = []
    for i, path in enumerate(images, start=1):
        if stop_flag and stop_flag():
            return []
        if progress:
            progress(i, total, path.name)
        info = _describe(path)
        if info is not None:
            described.append(info)

    # Группируем: каждый файл сравниваем с уже собранными группами.
    # Для архивов такого размера этого достаточно и без сложных структур.
    groups: list[list[DuplicateFile]] = []
    for info in described:
        for group in groups:
            if hamming_distance(info.phash, group[0].phash) <= threshold:
                group.append(info)
                break
        else:
            groups.append([info])

    result: list[DuplicateGroup] = []
    for group in groups:
        if len(group) < 2:
            continue  # одиночки не интересны
        # Точные копии определяем по содержимому — их удалять безопаснее всего
        exact = _all_identical(group)
        result.append(DuplicateGroup(files=group, exact=exact))

    # Сначала те, где можно освободить больше места
    result.sort(key=lambda g: g.wasted_bytes, reverse=True)
    return result


def _all_identical(files: list[DuplicateFile]) -> bool:
    """True, если все файлы в группе совпадают побайтно."""
    if len({f.size for f in files}) > 1:
        return False
    try:
        hashes = {organizer.file_hash(f.path) for f in files}
    except OSError:
        return False
    return len(hashes) == 1


def move_to_trash(paths: list[Path], trash_dir: Path, source_root: Path) -> int:
    """Переносит лишние копии в папку-корзину, сохраняя структуру подпапок.

    Файлы не удаляются безвозвратно: пользователь сам проверит корзину.
    Возвращает число перенесённых файлов.
    """
    import shutil

    moved = 0
    for path in paths:
        try:
            relative = path.relative_to(source_root)
        except ValueError:
            relative = Path(path.name)
        target = trash_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target = organizer._unique_path(target)
        try:
            shutil.move(str(path), str(target))
            moved += 1
        except OSError:
            continue
    return moved
