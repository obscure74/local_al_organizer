"""Индекс метаданных разложенных файлов.

Когда локальная модель разбирает документ, она извлекает ценные сведения:
тип документа, компанию, контрагента, дату. После раскладки эти данные
терялись — оставалось только имя файла. Здесь они сохраняются в базу SQLite,
и по ним можно искать: «все акты за март», «всё по ПромЭкоСистемы».

База лежит рядом с приложением (index.db) и никуда не отправляется.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import BASE_DIR

INDEX_PATH = BASE_DIR / "index.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path          TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    scope         TEXT,     -- work | personal | typed | photo | face
    category      TEXT,     -- Документы, Видео, Таблицы…
    doc_type      TEXT,     -- Акт, Счёт, Договор…
    company       TEXT,
    counterparty  TEXT,
    doc_date      TEXT,     -- ГГГГ-ММ-ДД
    topic         TEXT,
    person        TEXT,     -- кто на фото
    size          INTEGER,
    mtime         REAL,
    indexed_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_company  ON files(company);
CREATE INDEX IF NOT EXISTS idx_doc_type ON files(doc_type);
CREATE INDEX IF NOT EXISTS idx_doc_date ON files(doc_date);
CREATE INDEX IF NOT EXISTS idx_scope    ON files(scope);
CREATE INDEX IF NOT EXISTS idx_person   ON files(person);
"""


@dataclass
class Record:
    """Одна запись индекса."""

    path: str
    name: str = ""
    scope: str = ""
    category: str = ""
    doc_type: str = ""
    company: str = ""
    counterparty: str = ""
    doc_date: str = ""
    topic: str = ""
    person: str = ""
    size: int = 0
    mtime: float = 0.0

    @property
    def as_path(self) -> Path:
        return Path(self.path)

    def __post_init__(self):
        if not self.name:
            self.name = Path(self.path).name


class MetadataIndex:
    """Хранилище метаданных на SQLite."""

    def __init__(self, path: Path = INDEX_PATH):
        self.path = path
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        # Встроенный LOWER() в SQLite понижает регистр только у латиницы, из-за
        # чего «ПромЭкоСистемы» и «промэкосистемы» считались бы разными.
        # Регистрируем питоновский вариант, который корректно работает с кириллицей.
        connection.create_function("RULOWER", 1, _rulower, deterministic=True)
        return connection

    def _ensure_schema(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(_SCHEMA)
            connection.commit()

    # ---------- Запись ----------
    def add(self, record: Record) -> None:
        self.add_many([record])

    def add_many(self, records: Iterable[Record]) -> int:
        """Добавляет или обновляет записи. Возвращает их количество."""
        now = datetime.now().isoformat(timespec="seconds")
        rows = []
        for record in records:
            file_path = Path(record.path)
            size, mtime = record.size, record.mtime
            if not size or not mtime:
                try:
                    stat = file_path.stat()
                    size, mtime = stat.st_size, stat.st_mtime
                except OSError:
                    pass
            rows.append((
                str(file_path), record.name or file_path.name, record.scope,
                record.category, record.doc_type, record.company,
                record.counterparty, record.doc_date, record.topic,
                record.person, size, mtime, now,
            ))

        with closing(self._connect()) as connection:
            connection.executemany(
                """INSERT INTO files
                   (path, name, scope, category, doc_type, company, counterparty,
                    doc_date, topic, person, size, mtime, indexed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(path) DO UPDATE SET
                     name=excluded.name, scope=excluded.scope,
                     category=excluded.category, doc_type=excluded.doc_type,
                     company=excluded.company, counterparty=excluded.counterparty,
                     doc_date=excluded.doc_date, topic=excluded.topic,
                     person=excluded.person, size=excluded.size,
                     mtime=excluded.mtime, indexed_at=excluded.indexed_at""",
                rows)
            connection.commit()
        return len(rows)

    def remove_missing(self) -> int:
        """Убирает из индекса записи о файлах, которых больше нет на диске."""
        with closing(self._connect()) as connection:
            paths = [row["path"] for row in connection.execute("SELECT path FROM files")]
            gone = [(p,) for p in paths if not Path(p).exists()]
            if gone:
                connection.executemany("DELETE FROM files WHERE path = ?", gone)
                connection.commit()
        return len(gone)

    def clear(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("DELETE FROM files")
            connection.commit()

    # ---------- Чтение ----------
    def count(self) -> int:
        with closing(self._connect()) as connection:
            return connection.execute("SELECT COUNT(*) FROM files").fetchone()[0]

    def distinct(self, column: str) -> list[str]:
        """Список непустых значений колонки — для выпадающих списков фильтров."""
        if column not in {"company", "doc_type", "category", "scope", "person", "topic"}:
            raise ValueError(f"Недопустимая колонка: {column}")
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT DISTINCT {column} FROM files "  # noqa: S608 — колонка из белого списка
                f"WHERE {column} IS NOT NULL AND {column} != '' ORDER BY {column}")
            return [row[0] for row in rows]

    def search(
        self,
        text: str = "",
        company: str = "",
        doc_type: str = "",
        category: str = "",
        person: str = "",
        date_from: str = "",
        date_to: str = "",
        limit: int = 500,
    ) -> list[Record]:
        """Ищет записи по сочетанию фильтров. Пустые поля не ограничивают выборку."""
        conditions: list[str] = []
        params: list = []

        if text:
            like = f"%{text.lower()}%"
            conditions.append(
                "(RULOWER(name) LIKE ? OR RULOWER(company) LIKE ?"
                " OR RULOWER(counterparty) LIKE ? OR RULOWER(topic) LIKE ?)")
            params += [like, like, like, like]
        for column, value in (("company", company), ("doc_type", doc_type),
                              ("category", category), ("person", person)):
            if value:
                conditions.append(f"RULOWER({column}) = ?")
                params.append(value.lower())
        if date_from:
            conditions.append("doc_date >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("doc_date <= ?")
            params.append(date_to)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = (f"SELECT * FROM files {where} "  # noqa: S608 — условия параметризованы
                 f"ORDER BY doc_date DESC, name LIMIT ?")
        params.append(limit)

        with closing(self._connect()) as connection:
            rows = connection.execute(query, params).fetchall()
        return [_row_to_record(row) for row in rows]


def _rulower(value):
    """Понижение регистра с поддержкой кириллицы (для SQLite)."""
    return value.lower() if isinstance(value, str) else value


def _row_to_record(row: sqlite3.Row) -> Record:
    return Record(
        path=row["path"], name=row["name"], scope=row["scope"] or "",
        category=row["category"] or "", doc_type=row["doc_type"] or "",
        company=row["company"] or "", counterparty=row["counterparty"] or "",
        doc_date=row["doc_date"] or "", topic=row["topic"] or "",
        person=row["person"] or "", size=row["size"] or 0, mtime=row["mtime"] or 0.0)


# ---------- Построение записей ----------

def record_from_classification(path: Path, classification, category: str = "") -> Record:
    """Создаёт запись из результата разбора документа локальной моделью."""
    return Record(
        path=str(path),
        name=path.name,
        scope=classification.scope,
        category=category or classification.doc_type,
        doc_type=classification.doc_type,
        company=classification.company,
        counterparty=classification.counterparty,
        doc_date=classification.date,
        topic=classification.topic,
    )


def record_from_path(path: Path, roots: dict[str, Path]) -> Record | None:
    """Восстанавливает метаданные из структуры папок склада.

    Позволяет проиндексировать то, что было разложено раньше: приложение само
    создавало эти папки, поэтому их имена читаются обратно.

    Ожидаемые схемы:
      work_root/<Тип>/<ГГГГ-ММ>/<Компания>/файл
      personal_root/<Тема>/файл
      files_root/<Категория>/<Год>/файл
      photo_root/<Год>/<ММ_Месяц>/файл
      faces_root/<Имя человека>/файл
    """
    for scope, root in roots.items():
        if not root:
            continue
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue

        parts = relative.parts[:-1]  # без имени файла
        record = Record(path=str(path), name=path.name, scope=scope)

        if scope == "work" and len(parts) >= 3:
            record.doc_type = parts[0].replace("_", " ")
            record.category = record.doc_type
            record.doc_date = _month_to_date(parts[1])
            record.company = parts[2].replace("_", " ")
        elif scope == "personal" and parts:
            record.topic = parts[0].replace("_", " ")
            record.category = "Документы"
        elif scope == "typed" and parts:
            record.category = parts[0].replace("_", " ")
            if len(parts) >= 2 and parts[1].isdigit():
                record.doc_date = f"{parts[1]}-01-01"
        elif scope == "photo" and parts:
            record.category = "Изображения"
            record.doc_date = _photo_folders_to_date(parts)
        elif scope == "face" and parts:
            record.category = "Изображения"
            record.person = parts[0].replace("_", " ")
        else:
            record.category = record.category or ""

        return record
    return None


def _month_to_date(folder: str) -> str:
    """«2024-04» -> «2024-04-01»."""
    parts = folder.split("-")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{parts[0]}-{parts[1]:0>2}-01"
    return ""


def _photo_folders_to_date(parts: tuple[str, ...]) -> str:
    """(«2017», «04_Апрель») -> «2017-04-01»."""
    year = parts[0]
    if not year.isdigit():
        return ""
    month = "01"
    if len(parts) >= 2:
        head = parts[1].split("_")[0]
        if head.isdigit():
            month = f"{int(head):02d}"
    return f"{year}-{month}-01"


def roots_from_config(config: dict) -> dict[str, Path]:
    """Соответствие «область -> корневая папка» для разбора путей."""
    destinations = config.get("destinations", {})
    result: dict[str, Path] = {}
    mapping = {
        "work": destinations.get("work_root"),
        "personal": destinations.get("personal_root"),
        "typed": destinations.get("files_root"),
        "photo": config.get("photo", {}).get("dest_root"),
        "face": config.get("faces", {}).get("dest_root"),
    }
    for scope, value in mapping.items():
        if value:
            result[scope] = Path(value)
    return result


def rebuild_from_disk(
    config: dict,
    index: MetadataIndex,
    progress=None,
    stop_flag=None,
) -> int:
    """Переиндексирует склад, восстанавливая метаданные из структуры папок.

    Возвращает число проиндексированных файлов.
    """
    roots = roots_from_config(config)
    # Более специфичные корни идут первыми: work_root может лежать внутри files_root
    ordered = dict(sorted(roots.items(), key=lambda kv: len(str(kv[1])), reverse=True))

    files: list[Path] = []
    seen: set[str] = set()
    for root in ordered.values():
        if not root.is_dir():
            continue
        for item in root.rglob("*"):
            key = str(item).lower()
            if item.is_file() and key not in seen:
                seen.add(key)
                files.append(item)

    total = len(files)
    records: list[Record] = []
    for i, file_path in enumerate(files, start=1):
        if stop_flag and stop_flag():
            break
        if progress:
            progress(i, total, file_path.name)
        record = record_from_path(file_path, ordered)
        if record is not None:
            records.append(record)

    if records:
        index.add_many(records)
    return len(records)
