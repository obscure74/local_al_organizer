"""Вкладка «Поиск» — поиск по разложенным файлам склада.

Ищет по имени с фильтром по категории, открывает файл или его папку в
проводнике Windows.
"""
from __future__ import annotations

import contextlib
import os
import threading
from pathlib import Path

import customtkinter as ctk

from ..core import filetypes, search


class SearchTab(ctk.CTkFrame):
    def __init__(self, master, config_data: dict):
        super().__init__(master, fg_color="transparent")
        self.config_data = config_data
        self._searching = False
        self._stop = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_controls()
        self._build_results()

    def _build_controls(self):
        bar = ctk.CTkFrame(self)
        bar.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 6))
        bar.grid_columnconfigure(0, weight=1)

        self.query_entry = ctk.CTkEntry(bar, placeholder_text="Введите часть имени файла…")
        self.query_entry.grid(row=0, column=0, sticky="ew", padx=(8, 6), pady=8)
        self.query_entry.bind("<Return>", lambda _e: self._start_search())

        categories = [search.ALL_CATEGORIES] + list(filetypes.CATEGORIES.keys()) + ["Прочее"]
        self.category_var = ctk.StringVar(value=search.ALL_CATEGORIES)
        ctk.CTkOptionMenu(bar, values=categories, variable=self.category_var, width=150).grid(
            row=0, column=1, padx=6, pady=8)
        self.search_button = ctk.CTkButton(bar, text="Найти", width=100, command=self._start_search)
        self.search_button.grid(row=0, column=2, padx=(6, 8), pady=8)

        self.status_label = ctk.CTkLabel(self, text="Поиск идёт по всем папкам склада.", anchor="w")
        self.status_label.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 4))

    def _build_results(self):
        self.results = ctk.CTkScrollableFrame(self, label_text="")
        self.results.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        self.results.grid_columnconfigure(0, weight=1)

    def _start_search(self):
        if self._searching:
            return
        query = self.query_entry.get().strip()
        category = self.category_var.get()
        if not query and category == search.ALL_CATEGORIES:
            self.status_label.configure(text="Введите текст для поиска или выберите категорию.")
            return
        self._searching = True
        self._stop = False
        self._clear()
        self.search_button.configure(text="Поиск…", state="disabled")
        self.status_label.configure(text="Ищу…")
        threading.Thread(target=self._worker, args=(query, category), daemon=True).start()

    def _worker(self, query, category):
        try:
            results = search.search(self.config_data, query, category, stop_flag=lambda: self._stop)
        except Exception as exc:  # noqa: BLE001
            self.after(0, self._failed, str(exc))
            return
        self.after(0, self._done, results)

    def _failed(self, message):
        self._searching = False
        self.search_button.configure(text="Найти", state="normal")
        self.status_label.configure(text=f"Ошибка поиска: {message}", text_color="#d9534f")

    def _done(self, results):
        self._searching = False
        self.search_button.configure(text="Найти", state="normal")
        self.status_label.configure(
            text=f"Найдено: {len(results)}" + (" (показаны первые 1000)" if len(results) >= 1000 else ""),
            text_color=("gray10", "gray90"))
        for path in results[:1000]:
            ResultItem(self.results, path).pack(fill="x", padx=2, pady=2)

    def _clear(self):
        for child in self.results.winfo_children():
            child.destroy()


class ResultItem(ctk.CTkFrame):
    """Строка результата: имя, путь и кнопки открыть файл / открыть папку."""

    def __init__(self, master, path: Path):
        super().__init__(master)
        self.path = path
        self.grid_columnconfigure(0, weight=1)

        category = filetypes.category_for(path)
        ctk.CTkLabel(
            self, text=f"{path.name}", anchor="w",
            font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=8, pady=(6, 0))
        ctk.CTkLabel(
            self, text=f"{category}  ·  {path.parent}", anchor="w",
            text_color=("gray30", "gray70")).grid(
            row=1, column=0, sticky="w", padx=8, pady=(0, 6))

        ctk.CTkButton(self, text="Открыть", width=90, command=self._open_file).grid(
            row=0, column=1, rowspan=2, padx=4)
        ctk.CTkButton(self, text="Папка", width=80, command=self._open_folder).grid(
            row=0, column=2, rowspan=2, padx=(4, 8))

    def _open_file(self):
        # Открытие файла средствами Windows (по запросу пользователя)
        with contextlib.suppress(OSError, AttributeError):
            os.startfile(str(self.path))

    def _open_folder(self):
        # Открывает папку файла в проводнике
        with contextlib.suppress(OSError, AttributeError):
            os.startfile(str(self.path.parent))
