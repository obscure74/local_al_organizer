"""Вкладка «Дубли» — поиск визуально одинаковых фотографий.

Показывает группы похожих снимков с миниатюрами: лучший экземпляр (самое
высокое разрешение) отмечен как «оставить», остальные предлагаются к
переносу в корзину. Ничего не удаляется безвозвратно.
"""
from __future__ import annotations

import contextlib
import os
import threading
from datetime import date
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from ..core import duplicates

THUMB_SIZE = (96, 96)
MAX_GROUPS_SHOWN = 60  # чтобы интерфейс не захлебнулся на больших архивах

_LEVELS = {
    "Строгий": duplicates.STRICT,
    "Обычный": duplicates.NORMAL,
    "Мягкий": duplicates.LOOSE,
}


class DuplicatesTab(ctk.CTkFrame):
    def __init__(self, master, config_data: dict):
        super().__init__(master, fg_color="transparent")
        self.config_data = config_data
        self.groups: list[duplicates.DuplicateGroup] = []
        self.group_widgets: list[GroupCard] = []
        self._busy = False
        self._stop = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build_controls()
        self._build_results()

    # ---------- Панель управления ----------
    def _build_controls(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 6))
        frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(frame, text="Где искать:").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.folder_entry = ctk.CTkEntry(frame)
        self.folder_entry.insert(0, self.config_data.get("photo", {}).get("dest_root", ""))
        self.folder_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=6)
        ctk.CTkButton(frame, text="Обзор…", width=90, command=self._browse).grid(
            row=0, column=2, padx=6)

        opts = ctk.CTkFrame(frame, fg_color="transparent")
        opts.grid(row=1, column=0, columnspan=3, sticky="w", padx=4, pady=(0, 4))
        self.recursive_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(opts, text="Вложенные папки", variable=self.recursive_var,
                        onvalue=True, offvalue=False).pack(side="left", padx=8)
        ctk.CTkLabel(opts, text="Строгость:").pack(side="left", padx=(16, 4))
        self.level_var = ctk.StringVar(value="Обычный")
        ctk.CTkSegmentedButton(opts, values=list(_LEVELS), variable=self.level_var).pack(side="left")
        ctk.CTkLabel(opts, text="строгий — почти идентичные, мягкий — просто похожие",
                     text_color=("gray40", "gray60")).pack(side="left", padx=10)

        buttons = ctk.CTkFrame(frame, fg_color="transparent")
        buttons.grid(row=2, column=0, columnspan=3, sticky="ew", padx=4, pady=(0, 6))
        buttons.grid_columnconfigure(3, weight=1)
        self.scan_button = ctk.CTkButton(buttons, text="Найти дубли", width=140,
                                         command=self._start_scan)
        self.scan_button.grid(row=0, column=0, padx=6)
        self.select_button = ctk.CTkButton(
            buttons, text="Отметить все лишние", width=170, state="disabled",
            fg_color=("gray70", "gray30"), command=self._select_all_extras)
        self.select_button.grid(row=0, column=1, padx=6)
        self.trash_button = ctk.CTkButton(buttons, text="Убрать отмеченные", width=170,
                                          state="disabled", command=self._move_to_trash)
        self.trash_button.grid(row=0, column=2, padx=6)
        self.status_label = ctk.CTkLabel(buttons, text="Ничего не удаляется навсегда —"
                                         " лишние копии уедут в папку-корзину.", anchor="w")
        self.status_label.grid(row=0, column=3, sticky="ew", padx=10)

        self.progress = ctk.CTkProgressBar(frame)
        self.progress.set(0)
        self.progress.grid(row=3, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 8))
        self.progress_label = ctk.CTkLabel(frame, text="", width=200)
        self.progress_label.grid(row=3, column=2, padx=8)

    def _build_results(self):
        self.summary_label = ctk.CTkLabel(self, text="", anchor="w",
                                          font=ctk.CTkFont(size=13, weight="bold"))
        self.summary_label.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 4))
        self.results = ctk.CTkScrollableFrame(self, label_text="")
        self.results.grid(row=2, column=0, sticky="nsew", padx=4, pady=4)
        self.results.grid_columnconfigure(0, weight=1)

    def _browse(self):
        folder = filedialog.askdirectory(initialdir=self.folder_entry.get() or str(Path.home()))
        if folder:
            self.folder_entry.delete(0, "end")
            self.folder_entry.insert(0, folder)

    def _set_status(self, text, error=False):
        self.status_label.configure(
            text=text, text_color="#d9534f" if error else ("gray10", "gray90"))

    # ---------- Поиск ----------
    def _start_scan(self):
        if self._busy:
            self._stop = True
            self._set_status("Останавливаю…")
            return
        folder = Path(self.folder_entry.get().strip())
        if not folder.is_dir():
            self._set_status(f"Папка не найдена: {folder}", error=True)
            return

        self._busy = True
        self._stop = False
        self._clear_results()
        self.scan_button.configure(text="Остановить")
        self.trash_button.configure(state="disabled")
        self.select_button.configure(state="disabled")
        self._set_status("Считаю отпечатки изображений…")
        threading.Thread(target=self._scan_worker, args=(folder,), daemon=True).start()

    def _scan_worker(self, folder: Path):
        threshold = _LEVELS[self.level_var.get()]

        def progress(i, total, name):
            self.after(0, self._update_progress, i, total, name)

        try:
            groups = duplicates.find_groups(
                folder, threshold=threshold, recursive=self.recursive_var.get(),
                progress=progress, stop_flag=lambda: self._stop)
        except Exception as exc:  # noqa: BLE001
            self.after(0, self._scan_failed, str(exc))
            return
        self.after(0, self._scan_done, folder, groups)

    def _update_progress(self, i, total, name):
        self.progress.set(i / total if total else 0)
        self.progress_label.configure(text=f"{i}/{total}: {name[:22]}")

    def _scan_failed(self, message):
        self._busy = False
        self.scan_button.configure(text="Найти дубли")
        self._set_status(f"Ошибка: {message}", error=True)

    def _scan_done(self, folder: Path, groups):
        self._busy = False
        self.source_root = folder
        self.groups = groups
        self.scan_button.configure(text="Найти дубли")
        self.progress_label.configure(text="")

        if not groups:
            self._set_status("Визуальных дублей не найдено — архив чистый.")
            self.summary_label.configure(text="")
            return

        wasted = sum(g.wasted_bytes for g in groups) / 1024 / 1024
        extras = sum(len(g.extras) for g in groups)
        self.summary_label.configure(
            text=f"Найдено групп: {len(groups)} · лишних копий: {extras} · "
                 f"освободится: {wasted:.1f} МБ")
        self._set_status("Проверьте миниатюры и отметьте, что убрать.")

        for group in groups[:MAX_GROUPS_SHOWN]:
            card = GroupCard(self.results, group)
            card.pack(fill="x", padx=2, pady=4)
            self.group_widgets.append(card)
        if len(groups) > MAX_GROUPS_SHOWN:
            ctk.CTkLabel(
                self.results,
                text=f"…и ещё {len(groups) - MAX_GROUPS_SHOWN} групп. "
                     "Уберите найденные и запустите поиск снова.",
                text_color=("gray40", "gray60")).pack(pady=8)

        self.trash_button.configure(state="normal")
        self.select_button.configure(state="normal")

    def _clear_results(self):
        for card in self.group_widgets:
            card.destroy()
        self.group_widgets.clear()
        self.groups = []
        self.progress.set(0)
        self.summary_label.configure(text="")

    def _select_all_extras(self):
        for card in self.group_widgets:
            card.select_extras()
        self._set_status("Отмечены все лишние копии (лучший экземпляр сохраняется).")

    # ---------- Перенос в корзину ----------
    def _move_to_trash(self):
        selected: list[Path] = []
        for card in self.group_widgets:
            selected.extend(card.selected_paths())
        if not selected:
            self._set_status("Ничего не отмечено.", error=True)
            return

        trash = self.source_root / f"_Дубликаты_{date.today():%Y-%m-%d}"
        moved = duplicates.move_to_trash(selected, trash, self.source_root)
        self._set_status(
            f"Перенесено в корзину: {moved}. Проверьте папку и удалите её вручную.")
        self.trash_dir = trash

        for card in self.group_widgets:
            card.mark_done()
        ctk.CTkButton(self.results, text="Открыть папку-корзину",
                      command=lambda: self._open(trash)).pack(pady=10)

    def _open(self, path: Path):
        with contextlib.suppress(OSError, AttributeError):
            os.startfile(str(path))


class GroupCard(ctk.CTkFrame):
    """Карточка одной группы дублей: миниатюры всех копий."""

    def __init__(self, master, group: duplicates.DuplicateGroup):
        super().__init__(master)
        self.group = group
        self.items: list[FileItem] = []
        self.done = False

        tag = "точные копии" if group.exact else "визуально одинаковые"
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=8, pady=(8, 2))
        ctk.CTkLabel(header, text=f"{tag} · {len(group.files)} шт · "
                     f"лишнего {group.wasted_bytes / 1024 / 1024:.1f} МБ",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=("gray25", "gray75")).pack(side="left")

        strip = ctk.CTkFrame(self, fg_color="transparent")
        strip.pack(fill="x", padx=6, pady=(0, 8))
        best_path = group.best.path
        for file in sorted(group.files, key=lambda f: f.path != best_path):
            item = FileItem(strip, file, is_best=file.path == best_path)
            item.pack(side="left", padx=4)
            self.items.append(item)

    def select_extras(self):
        if self.done:
            return
        for item in self.items:
            if not item.is_best:
                item.checkbox_var.set(True)
                item.refresh()

    def selected_paths(self) -> list[Path]:
        if self.done:
            return []
        return [i.file.path for i in self.items if i.checkbox_var.get() and not i.is_best]

    def mark_done(self):
        self.done = True
        for item in self.items:
            item.checkbox.configure(state="disabled")


class FileItem(ctk.CTkFrame):
    """Миниатюра одного файла с галочкой и характеристиками."""

    def __init__(self, master, file: duplicates.DuplicateFile, is_best: bool):
        super().__init__(master, fg_color=("gray92", "gray16"))
        self.file = file
        self.is_best = is_best

        thumb = _load_thumbnail(file.path)
        if thumb is not None:
            ctk.CTkLabel(self, image=thumb, text="").pack(padx=6, pady=(6, 2))
        else:
            ctk.CTkLabel(self, text="🖼", font=ctk.CTkFont(size=32)).pack(padx=24, pady=(6, 2))

        ctk.CTkLabel(self, text=file.path.name[:22], font=ctk.CTkFont(size=10)).pack(padx=6)
        ctk.CTkLabel(self, text=f"{file.megapixels:.1f} Мп · {file.size / 1024 / 1024:.1f} МБ",
                     font=ctk.CTkFont(size=10), text_color=("gray35", "gray65")).pack(padx=6)

        self.checkbox_var = ctk.BooleanVar(value=False)
        if is_best:
            ctk.CTkLabel(self, text="✓ оставить", text_color="#2e7d32",
                         font=ctk.CTkFont(size=11, weight="bold")).pack(pady=(2, 8))
            self.checkbox = ctk.CTkCheckBox(self, text="", width=1)  # заглушка
        else:
            self.checkbox = ctk.CTkCheckBox(
                self, text="убрать", variable=self.checkbox_var, onvalue=True,
                offvalue=False, command=self.refresh, font=ctk.CTkFont(size=11))
            self.checkbox.pack(pady=(2, 8))

    def refresh(self):
        selected = self.checkbox_var.get()
        self.configure(fg_color=("#ffe0e0", "#4a2020") if selected else ("gray92", "gray16"))


def _load_thumbnail(path: Path):
    """Готовит миниатюру для показа; None, если файл не читается."""
    try:
        from PIL import Image

        image = Image.open(path)
        image.thumbnail(THUMB_SIZE)
        return ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
    except Exception:  # noqa: BLE001 — битый файл не должен ломать список
        return None
