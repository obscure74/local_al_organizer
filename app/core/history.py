"""История операций и откат (Undo).

Каждое нажатие «Применить» — это один «пакет» (batch) операций. Пакеты
пишутся в history.json, чтобы их можно было отменить: перемещённые файлы
возвращаются на место, скопированные — удаляются (если оригинал цел).

Это ключевая защита: перемещение файлов необратимо на уровне ОС, но здесь
у пользователя всегда есть кнопка «Отменить».
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .config import BASE_DIR
from .organizer import STATUS_COPIED, STATUS_DUPLICATE, STATUS_MOVED

HISTORY_PATH = BASE_DIR / "history.json"
MAX_BATCHES = 50  # храним последние N пакетов


@dataclass
class Entry:
    status: str          # moved | copied | duplicate
    source: str          # откуда (исходный путь)
    target: str          # куда (итоговый путь)


@dataclass
class Batch:
    module: str                       # "docs" | "photo"
    action: str                       # "move" | "copy"
    entries: list[Entry] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    undone: bool = False

    @property
    def moved_count(self) -> int:
        return sum(1 for e in self.entries if e.status in (STATUS_MOVED, STATUS_COPIED))

    def when(self) -> str:
        try:
            return datetime.fromisoformat(self.timestamp).strftime("%d.%m.%Y %H:%M")
        except ValueError:
            return self.timestamp


class HistoryStore:
    def __init__(self, path: Path = HISTORY_PATH):
        self.path = path
        self.batches: list[Batch] = self._load()

    def _load(self) -> list[Batch]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        batches = []
        for b in raw:
            entries = [Entry(**e) for e in b.get("entries", [])]
            batches.append(Batch(
                module=b.get("module", ""), action=b.get("action", ""),
                entries=entries, id=b.get("id", uuid.uuid4().hex[:8]),
                timestamp=b.get("timestamp", ""), undone=b.get("undone", False)))
        return batches

    def _save(self) -> None:
        data = [asdict(b) for b in self.batches[-MAX_BATCHES:]]
        with contextlib.suppress(OSError):
            self.path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, module: str, action: str, entries: list[Entry]) -> Batch:
        batch = Batch(module=module, action=action, entries=entries)
        self.batches.append(batch)
        self.batches = self.batches[-MAX_BATCHES:]
        self._save()
        return batch

    def recent(self) -> list[Batch]:
        """Пакеты от новых к старым."""
        return list(reversed(self.batches))

    def undo(self, batch_id: str) -> dict:
        """Откатывает пакет. Возвращает статистику: restored/removed/skipped/problems."""
        batch = next((b for b in self.batches if b.id == batch_id), None)
        if batch is None or batch.undone:
            return {"restored": 0, "removed": 0, "skipped": 0, "problems": 0}

        stats = {"restored": 0, "removed": 0, "skipped": 0, "problems": 0}
        for entry in batch.entries:
            result = _undo_entry(entry)
            if result == "restored":
                stats["restored"] += 1
            elif result == "removed":
                stats["removed"] += 1
            elif result == "skip":
                stats["skipped"] += 1
            else:
                stats["problems"] += 1

        batch.undone = True
        self._save()
        return stats


def _undo_entry(entry: Entry) -> str:
    """Отменяет одну операцию. Возвращает: restored | removed | skip | problem."""
    src = Path(entry.source)
    tgt = Path(entry.target)

    # Дубликаты ничего не двигали — отменять нечего
    if entry.status == STATUS_DUPLICATE:
        return "skip"
    # Целевого файла нет (переименован/удалён вручную) — откатить нельзя
    if not tgt.exists():
        return "problem"

    try:
        if entry.status == STATUS_MOVED:
            if src.exists():
                return "problem"  # на месте источника уже что-то есть
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(tgt), str(src))
            return "restored"

        if entry.status == STATUS_COPIED:
            if src.exists():
                os.remove(str(tgt))  # оригинал цел — убираем копию
                return "removed"
            # оригинал потерян — возвращаем копию на его место
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(tgt), str(src))
            return "restored"
    except OSError:
        return "problem"
    return "problem"
