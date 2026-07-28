"""Вкладка «Сюжеты» — раскладка фотографий по содержимому.

Определяет, что изображено на снимке: коты, природа, документы, счётчики,
скриншоты и так далее. Категории можно менять и дополнять своими — модель
CLIP сопоставляет картинку с текстовым описанием, поэтому переобучение не
требуется.
"""
from __future__ import annotations

import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from ..core import config as config_module
from ..core import scene_organizer, vision
from .summary_dialog import SummaryDialog

_ROW_SELECTED = ("#dbeafe", "#1e3a5f")
_ROW_NORMAL = ("gray92", "gray16")


class ScenesTab(ctk.CTkFrame):
    def __init__(self, master, config_data: dict, on_batch=None):
        super().__init__(master, fg_color="transparent")
        self.config_data = config_data
        self.on_batch = on_batch
        self.categories = vision.load_categories()
        self.plans: list[scene_organizer.ScenePlan] = []
        self.group_rows: list[CategoryRow] = []
        self._busy = False
        self._stop = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self._build_models_bar()
        self._build_categories_bar()
        self._build_scan_bar()
        self._build_results()
        self._refresh_models_state()
        self._refresh_categories()

    def _cfg(self) -> dict:
        return self.config_data["scenes"]

    # ---------- Модели ----------
    def _build_models_bar(self):
        self.models_frame = ctk.CTkFrame(self)
        self.models_frame.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 6))
        self.models_frame.grid_columnconfigure(0, weight=1)
        self.models_label = ctk.CTkLabel(self.models_frame, text="", anchor="w")
        self.models_label.grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        self.models_button = ctk.CTkButton(
            self.models_frame, text="Скачать модели", width=150, command=self._download)
        self.models_button.grid(row=0, column=1, padx=8, pady=8)

    def _refresh_models_state(self):
        if vision.models_ready():
            self.models_frame.grid_remove()
            return
        self.models_frame.grid()
        self.models_label.configure(
            text="Для распознавания сюжета нужна модель CLIP (~150 МБ): "
                 + ", ".join(vision.missing_models()),
            text_color="#b8860b")

    def _download(self):
        self.models_button.configure(state="disabled", text="Скачиваю…")

        def worker():
            try:
                vision.download_models(progress=lambda name, done, total: self.after(
                    0, self.models_label.configure,
                    {"text": f"Скачиваю {name}: {done * 100 // max(total, 1)}%"}))
            except Exception as exc:  # noqa: BLE001
                self.after(0, self._download_failed, str(exc))
                return
            self.after(0, self._download_done)

        threading.Thread(target=worker, daemon=True).start()

    def _download_done(self):
        self.models_button.configure(state="normal", text="Скачать модели")
        self._refresh_models_state()
        self._set_status("Модель загружена — можно распознавать сюжеты.")

    def _download_failed(self, message):
        self.models_button.configure(state="normal", text="Скачать модели")
        self.models_label.configure(text=f"Не удалось скачать: {message}",
                                    text_color="#d9534f")

    # ---------- Категории ----------
    def _build_categories_bar(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 6))
        frame.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 0))
        ctk.CTkLabel(header, text="Что искать на фото:",
                     font=ctk.CTkFont(weight="bold")).pack(side="left", padx=4)
        ctk.CTkButton(header, text="Своя категория", width=140,
                      command=self._add_category).pack(side="right", padx=4)
        ctk.CTkButton(header, text="Вернуть стандартные", width=170,
                      fg_color=("gray70", "gray30"),
                      command=self._reset_categories).pack(side="right", padx=4)

        self.categories_frame = ctk.CTkScrollableFrame(
            frame, height=70, orientation="horizontal", fg_color="transparent")
        self.categories_frame.grid(row=1, column=0, sticky="ew", padx=6, pady=6)

    def _refresh_categories(self):
        for child in self.categories_frame.winfo_children():
            child.destroy()
        for name in self.categories:
            chip = ctk.CTkFrame(self.categories_frame, fg_color=("gray85", "gray25"))
            chip.pack(side="left", padx=3, pady=4)
            ctk.CTkLabel(chip, text=name, font=ctk.CTkFont(size=12)).pack(
                side="left", padx=(10, 4), pady=6)
            ctk.CTkButton(chip, text="✕", width=22, height=22,
                          fg_color="transparent", hover_color=("gray70", "gray40"),
                          command=lambda n=name: self._remove_category(n)).pack(
                side="left", padx=(0, 4))

    def _add_category(self):
        dialog = ctk.CTkInputDialog(
            text="Название папки (например: Мемы).\n"
                 "Затем укажите описание по-английски — модель понимает его точнее.",
            title="Своя категория")
        name = (dialog.get_input() or "").strip()
        if not name:
            return
        prompt_dialog = ctk.CTkInputDialog(
            text=f"Опишите «{name}» по-английски, например: a funny meme image",
            title=f"Описание для «{name}»")
        prompt = (prompt_dialog.get_input() or "").strip()
        if not prompt:
            return
        self.categories[name] = [prompt]
        vision.save_categories(self.categories)
        self._refresh_categories()
        self._set_status(f"Категория «{name}» добавлена.")

    def _remove_category(self, name: str):
        self.categories.pop(name, None)
        vision.save_categories(self.categories)
        self._refresh_categories()

    def _reset_categories(self):
        self.categories = {k: list(v) for k, v in vision.DEFAULT_CATEGORIES.items()}
        vision.save_categories(self.categories)
        self._refresh_categories()
        self._set_status("Восстановлен стандартный набор категорий.")

    # ---------- Панель сканирования ----------
    def _build_scan_bar(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=2, column=0, sticky="ew", padx=4, pady=(0, 6))
        frame.grid_columnconfigure(1, weight=1)
        cfg = self._cfg()

        ctk.CTkLabel(frame, text="Папка с фото:").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.source_entry = ctk.CTkEntry(frame)
        self.source_entry.insert(0, cfg["source_folder"])
        self.source_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=6)
        ctk.CTkButton(frame, text="Обзор…", width=90,
                      command=lambda: self._browse(self.source_entry)).grid(row=0, column=2, padx=6)

        ctk.CTkLabel(frame, text="Куда раскладывать:").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        self.dest_entry = ctk.CTkEntry(frame)
        self.dest_entry.insert(0, cfg["dest_root"])
        self.dest_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=6)
        ctk.CTkButton(frame, text="Обзор…", width=90,
                      command=lambda: self._browse(self.dest_entry)).grid(row=1, column=2, padx=6)

        opts = ctk.CTkFrame(frame, fg_color="transparent")
        opts.grid(row=2, column=0, columnspan=3, sticky="w", padx=4, pady=(0, 4))
        self.recursive_var = ctk.BooleanVar(value=cfg.get("recursive", True))
        ctk.CTkCheckBox(opts, text="Вложенные папки", variable=self.recursive_var,
                        onvalue=True, offvalue=False).pack(side="left", padx=8)
        ctk.CTkLabel(opts, text="Действие:").pack(side="left", padx=(16, 4))
        self.action_var = ctk.StringVar(value=cfg.get("action", "copy"))
        ctk.CTkSegmentedButton(opts, values=["copy", "move"],
                               variable=self.action_var).pack(side="left")
        ctk.CTkLabel(opts, text="Строгость:").pack(side="left", padx=(16, 4))
        self.threshold_var = ctk.StringVar(value="Обычная")
        ctk.CTkSegmentedButton(opts, values=["Мягкая", "Обычная", "Строгая"],
                               variable=self.threshold_var).pack(side="left")

        buttons = ctk.CTkFrame(frame, fg_color="transparent")
        buttons.grid(row=3, column=0, columnspan=3, sticky="ew", padx=4, pady=(0, 6))
        buttons.grid_columnconfigure(2, weight=1)
        self.scan_button = ctk.CTkButton(buttons, text="Распознать сюжеты", width=170,
                                         command=self._start_scan)
        self.scan_button.grid(row=0, column=0, padx=6)
        self.apply_button = ctk.CTkButton(buttons, text="Разложить отмеченные", width=180,
                                          command=self._start_apply, state="disabled")
        self.apply_button.grid(row=0, column=1, padx=6)
        self.status_label = ctk.CTkLabel(buttons, text="", anchor="w")
        self.status_label.grid(row=0, column=2, sticky="ew", padx=10)

        self.progress = ctk.CTkProgressBar(frame)
        self.progress.set(0)
        self.progress.grid(row=4, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 8))
        self.progress_label = ctk.CTkLabel(frame, text="", width=200)
        self.progress_label.grid(row=4, column=2, padx=8)

    def _build_results(self):
        self.results = ctk.CTkScrollableFrame(self, label_text="Что нашлось на фотографиях")
        self.results.grid(row=3, column=0, sticky="nsew", padx=4, pady=4)
        self.results.grid_columnconfigure(0, weight=1)

    def _browse(self, entry):
        folder = filedialog.askdirectory(initialdir=entry.get() or str(Path.home()))
        if folder:
            entry.delete(0, "end")
            entry.insert(0, folder)

    def _threshold(self) -> float:
        return {"Мягкая": 0.22, "Обычная": 0.35, "Строгая": 0.5}[self.threshold_var.get()]

    def _persist(self):
        cfg = self._cfg()
        cfg["source_folder"] = self.source_entry.get().strip()
        cfg["dest_root"] = self.dest_entry.get().strip()
        cfg["recursive"] = self.recursive_var.get()
        cfg["action"] = self.action_var.get()
        cfg["threshold"] = self._threshold()
        config_module.save_config(self.config_data)

    def _set_status(self, text, error=False):
        self.status_label.configure(
            text=text, text_color="#d9534f" if error else ("gray10", "gray90"))

    # ---------- Распознавание ----------
    def _start_scan(self):
        if self._busy:
            self._stop = True
            self._set_status("Останавливаю…")
            return
        if not vision.models_ready():
            self._set_status("Сначала скачайте модель CLIP.", error=True)
            self._refresh_models_state()
            return
        if not self.categories:
            self._set_status("Добавьте хотя бы одну категорию.", error=True)
            return
        self._persist()
        if not Path(self._cfg()["source_folder"]).is_dir():
            self._set_status("Папка с фото не найдена.", error=True)
            return

        self._busy = True
        self._stop = False
        self._clear_results()
        self.scan_button.configure(text="Остановить")
        self.apply_button.configure(state="disabled")
        self._set_status("Распознаю содержимое снимков…")
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        def progress(i, total, name):
            self.after(0, self._update_progress, i, total, name)

        try:
            classifier = vision.SceneClassifier(self.categories, threshold=self._threshold())
            plans = scene_organizer.scan(
                self._cfg(), classifier, progress=progress, stop_flag=lambda: self._stop)
        except Exception as exc:  # noqa: BLE001
            self.after(0, self._scan_failed, str(exc))
            return
        self.after(0, self._scan_done, plans)

    def _update_progress(self, i, total, name):
        self.progress.set(i / total if total else 0)
        self.progress_label.configure(text=f"{i}/{total}: {name[:24]}")

    def _scan_failed(self, message):
        self._busy = False
        self.scan_button.configure(text="Распознать сюжеты")
        self._set_status(f"Ошибка: {message}", error=True)

    def _scan_done(self, plans):
        self._busy = False
        self.plans = plans
        self.scan_button.configure(text="Распознать сюжеты")
        self.progress_label.configure(text="")
        if not plans:
            self._set_status("Фотографий не найдено.")
            return

        groups = scene_organizer.group_by_category(plans)
        # «Разное» показываем последним
        for category in sorted(groups, key=lambda c: (c == vision.UNSURE_FOLDER,
                                                      -len(groups[c]))):
            row = CategoryRow(self.results, category, groups[category])
            row.pack(fill="x", padx=2, pady=2)
            self.group_rows.append(row)

        unsure = len(groups.get(vision.UNSURE_FOLDER, []))
        self._set_status(f"Разобрано {len(plans)} фото, категорий {len(groups)}, "
                         f"неуверенных {unsure}.")
        self.apply_button.configure(state="normal")

    def _clear_results(self):
        for row in self.group_rows:
            row.destroy()
        self.group_rows.clear()
        self.plans = []
        self.progress.set(0)

    # ---------- Применение ----------
    def _start_apply(self):
        if self._busy:
            return
        rows = [r for r in self.group_rows if r.checkbox_var.get() and not r.done]
        if not rows:
            self._set_status("Отметьте категории для раскладки.", error=True)
            return
        self._busy = True
        self.scan_button.configure(state="disabled")
        self.apply_button.configure(state="disabled")
        total = sum(len(r.plans) for r in rows)
        self._set_status(f"Раскладываю {total} фото…")
        threading.Thread(target=self._apply_worker, args=(rows, total), daemon=True).start()

    def _apply_worker(self, rows, total):
        from ..core import organizer
        from ..core.history import Entry

        action = self._cfg().get("action", "copy")
        done = moved = duplicates = errors = 0
        first_error = ""
        entries: list[Entry] = []
        for row in rows:
            for plan in row.plans:
                try:
                    status, final = scene_organizer.apply(plan, action=action)
                    entries.append(Entry(status=status, source=str(plan.source),
                                         target=str(final)))
                    if status == organizer.STATUS_DUPLICATE:
                        duplicates += 1
                    else:
                        moved += 1
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    if not first_error:
                        first_error = str(exc)
                done += 1
                self.after(0, self._update_progress, done, total, plan.source.name)
            self.after(0, row.mark_done)
        if entries and self.on_batch:
            self.after(0, self.on_batch, "scenes", action, entries)
        self.after(0, self._apply_done, moved, duplicates, errors, first_error)

    def _apply_done(self, moved, duplicates, errors, first_error):
        self._busy = False
        self.scan_button.configure(state="normal")
        self.apply_button.configure(state="normal")
        self.progress_label.configure(text="")
        verb = "скопировано" if self._cfg().get("action") == "copy" else "перемещено"
        self._set_status(f"Готово: {verb} {moved}, дубликатов {duplicates}, ошибок {errors}.",
                         error=bool(errors))
        SummaryDialog(
            self.winfo_toplevel(), action=self._cfg().get("action", "copy"),
            moved=moved, duplicates=duplicates, errors=errors,
            dest_folder=Path(self._cfg()["dest_root"]), first_error=first_error)


class CategoryRow(ctk.CTkFrame):
    """Строка результата: категория, количество снимков и уверенность."""

    def __init__(self, master, category: str, plans: list):
        super().__init__(master, fg_color=_ROW_NORMAL)
        self.category = category
        self.plans = plans
        self.done = False
        self.grid_columnconfigure(2, weight=1)

        self.checkbox_var = ctk.BooleanVar(value=category != vision.UNSURE_FOLDER)
        self.checkbox = ctk.CTkCheckBox(self, text="", width=28, variable=self.checkbox_var,
                                        onvalue=True, offvalue=False, command=self._refresh)
        self.checkbox.grid(row=0, column=0, padx=(6, 4), pady=8)

        unsure = category == vision.UNSURE_FOLDER
        color = "#b8860b" if unsure else "#1565c0"
        ctk.CTkLabel(self, text=f" {'❓' if unsure else '🏷'} ", fg_color=color,
                     corner_radius=6, text_color="white").grid(row=0, column=1, padx=4)

        average = sum(p.confidence for p in plans) / len(plans) * 100
        title = f"{category}  —  {len(plans)} фото  ·  уверенность {average:.0f}%"
        label = ctk.CTkLabel(self, text=title, anchor="w",
                             font=ctk.CTkFont(size=13, weight="bold"))
        label.grid(row=0, column=2, sticky="w", padx=8)

        for widget in (self, label):
            widget.bind("<Button-1>", self._click)
        self._refresh()

    def _click(self, _event=None):
        if self.done:
            return
        self.checkbox_var.set(not self.checkbox_var.get())
        self._refresh()

    def _refresh(self):
        if self.done:
            return
        self.configure(fg_color=_ROW_SELECTED if self.checkbox_var.get() else _ROW_NORMAL)

    def mark_done(self):
        self.done = True
        self.checkbox_var.set(False)
        self.checkbox.configure(state="disabled")
        self.configure(fg_color=("#e8f5e9", "#1b3a1e"))
