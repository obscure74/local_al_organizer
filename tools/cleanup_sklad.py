"""Утилита разовой чистки папки-склада от дублей.

Что делает:
  1. Пересчитывает «канонический» путь каждого файла той же нормализацией,
     что использует приложение (убирает кавычки и правовые формы в названиях
     компаний, приводит типы документов к единому виду). За счёт этого
     папки-двойники (напр. «ООО_«ПромЭкоСистемы»» и «ООО_ПромЭкоСистемы»,
     «Проектная» и «Проектная_документация») схлопываются в одну.
  2. Находит файлы с одинаковым содержимым (размер + SHA-256) и оставляет
     только один экземпляр.
  3. Ничего не удаляет безвозвратно: лишние файлы перемещаются в папку
     «_Дубликаты_<дата>» внутри склада — потом проверишь и удалишь вручную.

Использование (из корня проекта):
    python tools/cleanup_sklad.py "D:/Sklad"            # показать план
    python tools/cleanup_sklad.py "D:/Sklad" --apply    # выполнить
"""
from __future__ import annotations

import argparse
import contextlib
import shutil
import sys
from datetime import date
from pathlib import Path

# Windows-консоль часто в cp1251 — переключаем вывод на UTF-8, чтобы кириллица
# и спецсимволы не роняли скрипт (errors="replace" — на всякий случай).
with contextlib.suppress(AttributeError, ValueError):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Позволяем запускать скрипт напрямую (добавляем корень проекта в путь)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import organizer  # noqa: E402
from app.core.classifier import (  # noqa: E402
    _DOC_TYPE_CANON,
    _normalize_doc_type,
    normalize_company,
)

TRASH_PREFIX = "_Дубликаты_"


def canonical_segment(segment: str) -> str:
    """Приводит имя одной папки к каноническому виду (как в приложении)."""
    text = segment.replace("_", " ").strip()
    # Тип документа?
    if text.lower() in _DOC_TYPE_CANON:
        return organizer._sanitize(_normalize_doc_type(text))
    # Иначе — как название компании (убираем кавычки/правовые формы)
    normalized = normalize_company(text)
    return organizer._sanitize(normalized) or organizer._sanitize(text) or segment


def canonical_path(root: Path, file: Path) -> Path:
    """Канонический путь файла: каждую папку ниже root нормализуем, имя файла — как есть."""
    rel = file.relative_to(root)
    parts = [canonical_segment(p) for p in rel.parts[:-1]] + [rel.parts[-1]]
    return root.joinpath(*parts)


def collect_files(root: Path) -> list[Path]:
    """Все файлы под root, кроме уже лежащих в папках-корзинах."""
    files = []
    for p in root.rglob("*"):
        if p.is_file() and not any(part.startswith(TRASH_PREFIX) for part in p.relative_to(root).parts):
            files.append(p)
    return files


def build_plan(root: Path):
    """Возвращает (moves, dups, merges).

    moves  — [(src, dst)] перемещения файлов в канонические папки;
    dups   — [src] файлы-дубликаты (в корзину);
    merges — множество пар (старая_папка, новая_папка) для наглядности.
    """
    files = collect_files(root)

    # Группируем по КАНОНИЧЕСКОЙ ПАПКЕ (без учёта имени файла), чтобы поймать
    # дубли с разными именами в одной папке (напр. p.jpg и p_1.jpg).
    folder_groups: dict[Path, list[Path]] = {}
    for f in files:
        folder_groups.setdefault(canonical_path(root, f).parent, []).append(f)

    moves: list[tuple[Path, Path]] = []
    dups: list[Path] = []
    merges: set[tuple[str, str]] = set()

    for cdir, sources in folder_groups.items():
        # Приоритет «оригинала»: файл уже в нужной папке и без суффикса _N.
        sources.sort(key=lambda s: (s.parent != cdir, _has_number_suffix(s), str(s)))
        seen: dict[tuple[int, str], Path] = {}   # содержимое -> оставленный файл
        used_names: dict[str, int] = {}          # имя(lower) -> счётчик

        for src in sources:
            try:
                key = (src.stat().st_size, organizer.file_hash(src))
            except OSError:
                continue
            if key in seen:
                dups.append(src)   # то же содержимое уже есть — в корзину
                continue
            seen[key] = src

            # Имя в целевой папке; конфликт РАЗНОГО содержимого -> _1, _2…
            name = src.name
            n = used_names.get(name.lower(), 0)
            used_names[name.lower()] = n + 1
            dst = cdir / name if n == 0 else _numbered(cdir / name, n)

            if src != dst:
                moves.append((src, dst))
                if src.parent != cdir:
                    merges.add((
                        str(src.parent.relative_to(root)),
                        str(cdir.relative_to(root)),
                    ))

    return moves, dups, merges


def _has_number_suffix(path: Path) -> bool:
    """True, если имя оканчивается на _<цифры> (след прежних копий)."""
    stem = path.stem
    return "_" in stem and stem.rsplit("_", 1)[1].isdigit()


def _numbered(path: Path, i: int) -> Path:
    return path.parent / f"{path.stem}_{i}{path.suffix}"


def print_plan(root: Path, moves, dups, merges):
    print(f"\nСклад: {root}")
    print(f"  файлов-дубликатов (в корзину): {len(dups)}")
    print(f"  перемещений (слияние папок):    {len(moves)}")

    if merges:
        print("\nСлияние папок:")
        for old, new in sorted(merges):
            if old != new:
                print(f"  {old}")
                print(f"    -> {new}")

    if dups:
        print("\nПримеры дубликатов (первые 15):")
        for d in dups[:15]:
            print(f"  • {d.relative_to(root)}")

    if not moves and not dups:
        print("\nДублей и папок для слияния не найдено — всё чисто.")


def apply_plan(root: Path, moves, dups):
    trash = root / f"{TRASH_PREFIX}{date.today():%Y-%m-%d}"

    # 1. Дубликаты — в корзину (с сохранением относительного пути)
    for src in dups:
        _to_trash(root, trash, src)

    # 2. Перемещаем оставшиеся файлы в канонические папки
    for src, dst in moves:
        if not src.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        final = organizer._unique_path(dst)
        shutil.move(str(src), str(final))

    # 3. Удаляем опустевшие папки (пусто = данных нет)
    _remove_empty_dirs(root, trash)
    print(f"\nГотово. Дубликаты перемещены в: {trash}")
    print("Проверь их и, если всё верно, удали эту папку вручную.")


def _to_trash(root: Path, trash: Path, src: Path):
    rel = src.relative_to(root)
    dst = trash / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst = organizer._unique_path(dst)
    shutil.move(str(src), str(dst))


def _remove_empty_dirs(root: Path, trash: Path):
    # Идём снизу вверх, чтобы удалять вложенные пустые папки первыми
    for d in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        if trash in d.parents or d == trash:
            continue
        try:
            if not any(d.iterdir()):
                d.rmdir()
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser(description="Чистка склада от дублей.")
    parser.add_argument("root", nargs="?", default="D:/Sklad", help="Папка склада")
    parser.add_argument("--apply", action="store_true", help="Выполнить (иначе только показать план)")
    args = parser.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        print(f"Папка не найдена: {root}")
        sys.exit(1)

    moves, dups, merges = build_plan(root)
    print_plan(root, moves, dups, merges)

    if not args.apply:
        print("\nЭто предпросмотр. Чтобы выполнить, добавь флаг --apply")
        return
    if not moves and not dups:
        return
    apply_plan(root, moves, dups)


if __name__ == "__main__":
    main()
