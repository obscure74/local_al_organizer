"""Построение целевого пути/имени и физическое перемещение файлов.

Разделено на два этапа:
  1. plan()  — вычисляет, куда и под каким именем поедет файл (ничего не двигает);
  2. apply() — реально перемещает/копирует по готовому плану.
Такое разделение позволяет показать пользователю предпросмотр перед действием.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .classifier import Classification

# Статусы результата apply()
STATUS_MOVED = "moved"          # файл перемещён (удалён из источника)
STATUS_COPIED = "copied"        # файл скопирован (источник остался)
STATUS_DUPLICATE = "duplicate"  # такой файл уже есть в назначении — пропущен

# Символы, запрещённые в именах файлов/папок Windows
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class MovePlan:
    source: Path
    target: Path          # полный путь назначения (папка + новое имя)
    classification: Classification

    @property
    def target_dir(self) -> Path:
        return self.target.parent

    @property
    def new_name(self) -> str:
        return self.target.name


def plan(source: Path, cls: Classification, config: dict) -> MovePlan:
    """Вычисляет целевой путь для файла на основе классификации."""
    ext = source.suffix.lower()
    dest = config["destinations"]

    if cls.scope == "typed":
        # Типовой файл (видео, таблица, архив…) — по категории и году, без ИИ.
        target_dir = _typed_dir(source, cls, Path(dest.get("files_root", dest["personal_root"])))
        # Имя оригинала сохраняем как есть
        target = target_dir / source.name
        return MovePlan(source=source, target=target, classification=cls)

    if cls.scope == "work":
        target_dir = _work_dir(source, cls, Path(dest["work_root"]))
        stem = _work_filename(cls, source.stem)
    else:
        target_dir = _personal_dir(cls, Path(dest["personal_root"]))
        stem = _personal_filename(cls, source.stem)

    # "Идеальный" путь без суффиксов _1/_2 — уникальность и проверка на дубли
    # выполняются в apply(), чтобы предпросмотр показывал понятное имя.
    target = target_dir / f"{_sanitize(stem)}{ext}"
    return MovePlan(source=source, target=target, classification=cls)


def apply(move_plan: MovePlan, action: str = "copy") -> tuple[str, Path]:
    """Копирует/перемещает файл. Возвращает (статус, итоговый_путь).

    Правило переноса:
    - если в целевой папке уже есть идентичный файл (тот же размер и хеш) —
      он не дублируется; в режиме move источник удаляется как лишний;
    - при обычном перемещении shutil.move удаляет источник только после
      успешного копирования. Если возникнет ошибка — исключение пробрасывается,
      и исходный файл остаётся на месте (в «Загрузках»).
    """
    source = move_plan.source
    target_dir = move_plan.target_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    # 1. Проверка на дубликат по содержимому
    existing = find_duplicate(target_dir, source)
    if existing is not None:
        if action == "move":
            os.remove(source)  # копия уже есть — убираем лишний из источника
        return STATUS_DUPLICATE, existing

    # 2. Разрешаем возможное совпадение имён (разные файлы, одно имя)
    target = _unique_path(move_plan.target)
    if action == "move":
        shutil.move(str(source), str(target))
        return STATUS_MOVED, target
    shutil.copy2(str(source), str(target))
    return STATUS_COPIED, target


# --- Внутренняя логика построения путей и имён ---

def _work_dir(source: Path, cls: Classification, root: Path) -> Path:
    """Рабочее/<Тип>/<ГГГГ-ММ>/<Компания>"""
    month = _month_folder(cls.date, source)
    company = _sanitize(cls.company) or "Без_компании"
    doc_type = _sanitize(cls.doc_type) or "Прочее"
    return root / doc_type / month / company


def _personal_dir(cls: Classification, root: Path) -> Path:
    """Личное/<Тема>"""
    topic = _sanitize(cls.topic) or "Разное"
    return root / topic


def _typed_dir(source: Path, cls: Classification, root: Path) -> Path:
    """<Категория>/<Год> — категория лежит в cls.doc_type, год по дате файла."""
    category = _sanitize(cls.doc_type) or "Прочее"
    try:
        year = datetime.fromtimestamp(source.stat().st_mtime).strftime("%Y")
    except OSError:
        year = "Без_даты"
    return root / category / year


def _work_filename(cls: Classification, fallback_stem: str) -> str:
    """Например: Акт_Ромашка_Василёк_2024-04-12"""
    parts = [cls.doc_type, cls.company, cls.counterparty, cls.date]
    parts = [p for p in parts if p]
    name = "_".join(parts)
    return name or cls.short_title or fallback_stem


def _personal_filename(cls: Classification, fallback_stem: str) -> str:
    return cls.short_title or fallback_stem


def _month_folder(date_str: str, source: Path) -> str:
    """Возвращает папку вида '2024-04'. Дата берётся из документа, иначе из
    времени изменения файла."""
    dt = _parse_date(date_str)
    if dt is None:
        dt = datetime.fromtimestamp(source.stat().st_mtime)
    return dt.strftime("%Y-%m")


def _parse_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


def _sanitize(name: str) -> str:
    """Убирает запрещённые символы и лишние пробелы; заменяет пробелы на '_'."""
    if not name:
        return ""
    cleaned = _ILLEGAL.sub("", name).strip().strip(".")
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned[:100]  # ограничиваем длину сегмента пути


def _unique_path(path: Path) -> Path:
    """Если файл с таким именем уже есть — добавляет _1, _2, ..."""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    i = 1
    while True:
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def file_hash(path: Path, chunk: int = 1 << 16) -> str:
    """SHA-256 содержимого файла (читается блоками, память не забивается)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def find_duplicate(target_dir: Path, source: Path) -> Path | None:
    """Ищет в целевой папке файл, идентичный source (тот же размер и хеш).

    Сравнение по содержимому, а не по имени — поэтому дубликат ловится, даже
    если ИИ назвал файл чуть иначе при повторном сканировании. Хеш считаем
    только для файлов совпадающего размера (это быстро).
    """
    if not target_dir.exists():
        return None
    try:
        src_size = source.stat().st_size
    except OSError:
        return None

    src_hash: str | None = None
    for candidate in target_dir.iterdir():
        if not candidate.is_file():
            continue
        try:
            if candidate.stat().st_size != src_size:
                continue
        except OSError:
            continue
        if src_hash is None:
            src_hash = file_hash(source)
        try:
            if file_hash(candidate) == src_hash:
                return candidate
        except OSError:
            continue
    return None
