"""Поиск по разложенным файлам.

Ищет по всем корневым папкам склада (рабочее, личное, прочие типы, фото)
по части имени файла, с необязательным фильтром по категории.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from . import filetypes

ALL_CATEGORIES = "Все"


def roots_from_config(config: dict) -> list[Path]:
    """Уникальные существующие корневые папки для поиска, без вложенных.

    Если один корень лежит внутри другого (напр. files_root=Sklad содержит
    work_root=Sklad/Work), вложенный отбрасывается — иначе файлы нашлись бы
    дважды.
    """
    dest = config.get("destinations", {})
    candidates = [
        dest.get("work_root"),
        dest.get("personal_root"),
        dest.get("files_root"),
        config.get("photo", {}).get("dest_root"),
    ]
    resolved: list[Path] = []
    seen: set[str] = set()
    for c in candidates:
        if not c:
            continue
        p = Path(c)
        if not p.is_dir():
            continue
        key = str(p.resolve()).lower()
        if key not in seen:
            seen.add(key)
            resolved.append(p.resolve())

    # Отбрасываем корни, вложенные в другой корень из списка
    roots: list[Path] = []
    for p in resolved:
        if not any(p != other and _is_relative_to(p, other) for other in resolved):
            roots.append(p)
    return roots


def _is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
        return True
    except ValueError:
        return False


def search(
    config: dict,
    query: str,
    category: str = ALL_CATEGORIES,
    limit: int = 1000,
    stop_flag: Callable[[], bool] | None = None,
) -> list[Path]:
    """Возвращает файлы, чьё имя содержит query, с фильтром по категории."""
    query_l = query.lower().strip()
    results: list[Path] = []
    seen: set[str] = set()
    for root in roots_from_config(config):
        for p in root.rglob("*"):
            if stop_flag and stop_flag():
                return results
            if not p.is_file():
                continue
            if query_l and query_l not in p.name.lower():
                continue
            if category != ALL_CATEGORIES and filetypes.category_for(p) != category:
                continue
            key = str(p).lower()
            if key in seen:
                continue
            seen.add(key)
            results.append(p)
            if len(results) >= limit:
                return results
    return results
