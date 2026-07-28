"""Вкладка «Поиск» — поиск по разложенным файлам.

Работает в двух режимах:
  * по метаданным — ищет в индексе по компании, типу документа и датам,
    то есть по тому, что распознала локальная модель;
  * по имени файла — обходит папки склада напрямую, без индекса.
"""
from __future__ import annotations

import contextlib
import os
import threading
from pathlib import Path

import customtkinter as ctk

from ..core import filetypes, index, search

ANY = "Любой"


class SearchTab(ctk.CTkFrame):
    def __init__(self, master, config_data: dict, metadata_index=None):
        super().__init__(master, fg_color="transparent")
        self.config_data = config_data
        self.metadata_index = metadata_index or index.MetadataIndex()
        self._searching = False
        self._stop = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build_controls()
        self._build_results()
        self._refresh_filters()

    # ---------- Панель поиска ----------
    def _build_controls(self):
        bar = ctk.CTkFrame(self)
        bar.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 4))
        bar.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(bar, text="Искать:").grid(row=0, column=0, sticky="w", padx=(8, 4), pady=8)
        self.query_entry = ctk.CTkEntry(
            bar, placeholder_text="часть имени, компания или тема…")
        self.query_entry.grid(row=0, column=1, sticky="ew", padx=6, pady=8)
        self.query_entry.bind("<Return>", lambda _e: self._start_search())
        self.search_button = ctk.CTkButton(bar, text="Найти", width=100,
                                           command=self._start_search)
        self.search_button.grid(row=0, column=2, padx=(6, 8), pady=8)

        # Фильтры по метаданным
        filters = ctk.CTkFrame(bar, fg_color="transparent")
        filters.grid(row=1, column=0, columnspan=3, sticky="ew", padx=4, pady=(0, 6))

        ctk.CTkLabel(filters, text="Компания:").pack(side="left", padx=(6, 2))
        self.company_var = ctk.StringVar(value=ANY)
        self.company_menu = ctk.CTkOptionMenu(filters, values=[ANY],
                                              variable=self.company_var, width=160)
        self.company_menu.pack(side="left", padx=4)

        ctk.CTkLabel(filters, text="Тип:").pack(side="left", padx=(10, 2))
        self.doctype_var = ctk.StringVar(value=ANY)
        self.doctype_menu = ctk.CTkOptionMenu(filters, values=[ANY],
                                              variable=self.doctype_var, width=170)
        self.doctype_menu.pack(side="left", padx=4)

        ctk.CTkLabel(filters, text="Период:").pack(side="left", padx=(10, 2))
        self.date_from = ctk.CTkEntry(filters, width=100, placeholder_text="2024-01")
        self.date_from.pack(side="left", padx=2)
        ctk.CTkLabel(filters, text="—").pack(side="left")
        self.date_to = ctk.CTkEntry(filters, width=100, placeholder_text="2024-12")
        self.date_to.pack(side="left", padx=2)

        ctk.CTkButton(filters, text="Сбросить", width=90, fg_color=("gray70", "gray30"),
                      command=self._reset_filters).pack(side="left", padx=10)

        # Служебная строка: режим и переиндексация
        service = ctk.CTkFrame(self, fg_color="transparent")
        service.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 2))
        self.mode_var = ctk.StringVar(value="По метаданным")
        ctk.CTkSegmentedButton(service, values=["По метаданным", "По имени файла"],
                               variable=self.mode_var, command=lambda _v: self._refresh_filters()
                               ).pack(side="left")
        self.reindex_button = ctk.CTkButton(
            service, text="Переиндексировать склад", width=190,
            fg_color=("gray70", "gray30"), command=self._start_reindex)
        self.reindex_button.pack(side="right", padx=4)
        self.status_label = ctk.CTkLabel(service, text="", anchor="w")
        self.status_label.pack(side="left", padx=12)

    def _build_results(self):
        self.results = ctk.CTkScrollableFrame(self, label_text="")
        self.results.grid(row=2, column=0, sticky="nsew", padx=4, pady=4)
        self.results.grid_columnconfigure(0, weight=1)

    def _refresh_filters(self):
        """Подтягивает списки компаний и типов из индекса."""
        by_metadata = self.mode_var.get() == "По метаданным"
        state = "normal" if by_metadata else "disabled"
        for widget in (self.company_menu, self.doctype_menu, self.date_from, self.date_to):
            widget.configure(state=state)

        try:
            companies = [ANY] + self.metadata_index.distinct("company")
            doc_types = [ANY] + self.metadata_index.distinct("doc_type")
            total = self.metadata_index.count()
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Индекс недоступен: {exc}", error=True)
            return

        self.company_menu.configure(values=companies)
        self.doctype_menu.configure(values=doc_types)
        if self.company_var.get() not in companies:
            self.company_var.set(ANY)
        if self.doctype_var.get() not in doc_types:
            self.doctype_var.set(ANY)

        if by_metadata:
            if total:
                self._set_status(f"В индексе {total} файлов.")
            else:
                self._set_status(
                    "Индекс пуст — нажмите «Переиндексировать склад».")

    def _reset_filters(self):
        self.company_var.set(ANY)
        self.doctype_var.set(ANY)
        self.date_from.delete(0, "end")
        self.date_to.delete(0, "end")
        self.query_entry.delete(0, "end")

    def _set_status(self, text, error=False):
        self.status_label.configure(
            text=text, text_color="#d9534f" if error else ("gray10", "gray90"))

    # ---------- Переиндексация ----------
    def _start_reindex(self):
        if self._searching:
            return
        self._searching = True
        self.reindex_button.configure(state="disabled", text="Индексирую…")
        self._set_status("Собираю метаданные из структуры папок…")

        def worker():
            try:
                self.metadata_index.remove_missing()
                count = index.rebuild_from_disk(
                    self.config_data, self.metadata_index,
                    progress=lambda i, total, name: self.after(
                        0, self._set_status, f"Индексирую {i}/{total}: {name[:26]}"))
            except Exception as exc:  # noqa: BLE001
                self.after(0, self._reindex_failed, str(exc))
                return
            self.after(0, self._reindex_done, count)

        threading.Thread(target=worker, daemon=True).start()

    def _reindex_done(self, count):
        self._searching = False
        self.reindex_button.configure(state="normal", text="Переиндексировать склад")
        self._set_status(f"Проиндексировано файлов: {count}.")
        self._refresh_filters()

    def _reindex_failed(self, message):
        self._searching = False
        self.reindex_button.configure(state="normal", text="Переиндексировать склад")
        self._set_status(f"Ошибка индексации: {message}", error=True)

    # ---------- Поиск ----------
    def _start_search(self):
        if self._searching:
            return
        self._searching = True
        self._stop = False
        self._clear()
        self.search_button.configure(text="Поиск…", state="disabled")

        by_metadata = self.mode_var.get() == "По метаданным"
        params = {
            "text": self.query_entry.get().strip(),
            "company": "" if self.company_var.get() == ANY else self.company_var.get(),
            "doc_type": "" if self.doctype_var.get() == ANY else self.doctype_var.get(),
            "date_from": _normalize_date(self.date_from.get().strip(), start=True),
            "date_to": _normalize_date(self.date_to.get().strip(), start=False),
        }
        threading.Thread(target=self._worker, args=(by_metadata, params), daemon=True).start()

    def _worker(self, by_metadata: bool, params: dict):
        try:
            if by_metadata:
                results = self.metadata_index.search(**params)
            else:
                paths = search.search(self.config_data, params["text"],
                                      stop_flag=lambda: self._stop)
                results = [index.Record(path=str(p), name=p.name,
                                        category=filetypes.category_for(p)) for p in paths]
        except Exception as exc:  # noqa: BLE001
            self.after(0, self._failed, str(exc))
            return
        self.after(0, self._done, results)

    def _failed(self, message):
        self._searching = False
        self.search_button.configure(text="Найти", state="normal")
        self._set_status(f"Ошибка поиска: {message}", error=True)

    def _done(self, results):
        self._searching = False
        self.search_button.configure(text="Найти", state="normal")
        if not results:
            self._set_status("Ничего не найдено. Попробуйте ослабить фильтры.")
            return
        self._set_status(f"Найдено: {len(results)}")
        for record in results[:500]:
            ResultItem(self.results, record).pack(fill="x", padx=2, pady=2)

    def _clear(self):
        for child in self.results.winfo_children():
            child.destroy()


def _normalize_date(value: str, start: bool) -> str:
    """Приводит «2024» или «2024-03» к полной дате для сравнения."""
    value = value.strip()
    if not value:
        return ""
    parts = value.replace(".", "-").replace("/", "-").split("-")
    if len(parts) == 1 and parts[0].isdigit():
        return f"{parts[0]}-01-01" if start else f"{parts[0]}-12-31"
    if len(parts) == 2:
        year, month = parts
        return f"{year}-{int(month):02d}-01" if start else f"{year}-{int(month):02d}-31"
    return value


class ResultItem(ctk.CTkFrame):
    """Строка результата: имя, метаданные и кнопки открытия."""

    def __init__(self, master, record: index.Record):
        super().__init__(master)
        self.record = record
        self.path = Path(record.path)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text=record.name, anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=8, pady=(6, 0))

        # Собираем строку метаданных из непустых полей
        chips = [c for c in (record.doc_type or record.category, record.company,
                             record.person, record.topic, record.doc_date) if c]
        subtitle = "  ·  ".join(chips) if chips else str(self.path.parent)
        ctk.CTkLabel(self, text=subtitle, anchor="w",
                     text_color=("gray30", "gray70")).grid(
            row=1, column=0, sticky="w", padx=8)
        ctk.CTkLabel(self, text=str(self.path.parent), anchor="w",
                     font=ctk.CTkFont(size=10), text_color=("gray45", "gray55")).grid(
            row=2, column=0, sticky="w", padx=8, pady=(0, 6))

        ctk.CTkButton(self, text="Открыть", width=90, command=self._open_file).grid(
            row=0, column=1, rowspan=3, padx=4)
        ctk.CTkButton(self, text="Папка", width=80, command=self._open_folder).grid(
            row=0, column=2, rowspan=3, padx=(4, 8))

    def _open_file(self):
        with contextlib.suppress(OSError, AttributeError):
            os.startfile(str(self.path))

    def _open_folder(self):
        with contextlib.suppress(OSError, AttributeError):
            os.startfile(str(self.path.parent))
