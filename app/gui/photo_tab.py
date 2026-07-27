"""Вкладка «Фото»: раскладка фотографий по годам и месяцам (Модуль 2).

Результат показывается сгруппированно (год/месяц + количество), т.к. фото
могут быть тысячи. Тяжёлые операции — в отдельном потоке.
"""
from __future__ import annotations

import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from ..core import config as config_module
from ..core import photo_organizer

_ROW_SELECTED = ("#dbeafe", "#1e3a5f")
_ROW_NORMAL = ("gray92", "gray16")


class PhotoTab(ctk.CTkFrame):
    def __init__(self, master, config_data: dict, on_batch=None):
        super().__init__(master, fg_color="transparent")
        self.config_data = config_data
        # Колбэк для записи применённого пакета в историю: (module, action, entries)
        self.on_batch = on_batch
        self.plans: list[photo_organizer.PhotoPlan] = []
        self.group_rows: list[GroupRow] = []
        self._busy = False
        self._stop = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        self._build_settings()
        self._build_controls()
        self._build_progress()
        self._build_results()

    def _cfg(self) -> dict:
        return self.config_data["photo"]

    # ---------- Настройки источника/назначения ----------
    def _build_settings(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 6))
        frame.grid_columnconfigure(1, weight=1)
        cfg = self._cfg()

        ctk.CTkLabel(frame, text="Папка с фото (можно внешний диск):").grid(
            row=0, column=0, sticky="w", padx=8, pady=6)
        self.source_entry = ctk.CTkEntry(frame)
        self.source_entry.insert(0, cfg["source_folder"])
        self.source_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=6)
        ctk.CTkButton(frame, text="Обзор…", width=90,
                      command=lambda: self._browse(self.source_entry)).grid(
            row=0, column=2, padx=6)

        ctk.CTkLabel(frame, text="Куда раскладывать:").grid(
            row=1, column=0, sticky="w", padx=8, pady=6)
        self.dest_entry = ctk.CTkEntry(frame)
        self.dest_entry.insert(0, cfg["dest_root"])
        self.dest_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=6)
        ctk.CTkButton(frame, text="Обзор…", width=90,
                      command=lambda: self._browse(self.dest_entry)).grid(
            row=1, column=2, padx=6)

        opts = ctk.CTkFrame(frame, fg_color="transparent")
        opts.grid(row=2, column=0, columnspan=3, sticky="w", padx=4, pady=(0, 4))
        self.recursive_var = ctk.BooleanVar(value=cfg.get("recursive", True))
        ctk.CTkCheckBox(opts, text="Искать во вложенных папках",
                        variable=self.recursive_var, onvalue=True, offvalue=False).pack(
            side="left", padx=8)
        self.screenshots_var = ctk.BooleanVar(value=cfg.get("separate_screenshots", True))
        ctk.CTkCheckBox(opts, text="Скриншоты — в отдельную папку",
                        variable=self.screenshots_var, onvalue=True, offvalue=False).pack(
            side="left", padx=8)
        ctk.CTkLabel(opts, text="Действие:").pack(side="left", padx=(16, 4))
        self.action_var = ctk.StringVar(value=cfg.get("action", "copy"))
        ctk.CTkSegmentedButton(opts, values=["copy", "move"],
                               variable=self.action_var).pack(side="left")

    # ---------- Кнопки ----------
    def _build_controls(self):
        bar = ctk.CTkFrame(self)
        bar.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 6))
        bar.grid_columnconfigure(2, weight=1)

        self.scan_button = ctk.CTkButton(
            bar, text="Сканировать фото", width=160, command=self._start_scan)
        self.scan_button.grid(row=0, column=0, padx=6, pady=8)
        self.apply_button = ctk.CTkButton(
            bar, text="Применить отмеченные", width=180,
            command=self._start_apply, state="disabled")
        self.apply_button.grid(row=0, column=1, padx=6, pady=8)
        self.status_label = ctk.CTkLabel(bar, text="Укажи папку с фото и нажми «Сканировать».", anchor="w")
        self.status_label.grid(row=0, column=2, sticky="ew", padx=10)

    def _build_progress(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=2, column=0, sticky="ew", padx=4, pady=(0, 6))
        frame.grid_columnconfigure(0, weight=1)
        self.progress = ctk.CTkProgressBar(frame)
        self.progress.set(0)
        self.progress.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        self.progress_label = ctk.CTkLabel(frame, text="", width=220)
        self.progress_label.grid(row=0, column=1, padx=8)

    def _build_results(self):
        self.results = ctk.CTkScrollableFrame(self, label_text="Что получится (по годам и месяцам)")
        self.results.grid(row=3, column=0, sticky="nsew", padx=4, pady=4)
        self.results.grid_columnconfigure(0, weight=1)
        self.summary_label = ctk.CTkLabel(self, text="", anchor="w")
        self.summary_label.grid(row=4, column=0, sticky="ew", padx=8, pady=(2, 4))

    # ---------- Вспомогательное ----------
    def _browse(self, entry):
        folder = filedialog.askdirectory(initialdir=entry.get() or str(Path.home()))
        if folder:
            entry.delete(0, "end")
            entry.insert(0, folder)

    def _persist(self):
        cfg = self._cfg()
        cfg["source_folder"] = self.source_entry.get().strip()
        cfg["dest_root"] = self.dest_entry.get().strip()
        cfg["recursive"] = self.recursive_var.get()
        cfg["separate_screenshots"] = self.screenshots_var.get()
        cfg["action"] = self.action_var.get()
        config_module.save_config(self.config_data)

    def _set_status(self, text, error=False):
        self.status_label.configure(
            text=text, text_color="#d9534f" if error else ("gray10", "gray90"))

    # ---------- Сканирование ----------
    def _start_scan(self):
        if self._busy:
            self._stop = True
            self._set_status("Останавливаю…")
            return
        self._persist()
        source = Path(self._cfg()["source_folder"])
        if not source.is_dir():
            self._set_status(f"Папка не найдена: {source}", error=True)
            return

        self._busy = True
        self._stop = False
        self._clear_results()
        self.scan_button.configure(text="Остановить")
        self.apply_button.configure(state="disabled")
        self._set_status("Сканирование фото…")
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        def progress(i, total, name):
            self.after(0, self._update_progress, i, total, name)
        try:
            plans = photo_organizer.scan(
                self._cfg(), progress=progress, stop_flag=lambda: self._stop)
        except Exception as exc:  # noqa: BLE001
            self.after(0, self._scan_failed, str(exc))
            return
        self.after(0, self._scan_done, plans)

    def _update_progress(self, i, total, name):
        self.progress.set(i / total if total else 0)
        self.progress_label.configure(text=f"{i}/{total}: {name[:28]}")

    def _scan_failed(self, message):
        self._busy = False
        self.scan_button.configure(text="Сканировать фото")
        self._set_status(f"Ошибка: {message}", error=True)

    def _scan_done(self, plans):
        self._busy = False
        self.plans = plans
        self.scan_button.configure(text="Сканировать фото")
        self.progress_label.configure(text="")
        if not plans:
            self._set_status("Фотографий не найдено.")
            return
        self._render_groups(plans)
        exif = sum(1 for p in plans if p.date_from_exif)
        self._set_status(
            f"Найдено {len(plans)} фото. Дата из EXIF: {exif}, по дате файла: {len(plans) - exif}.")
        self.apply_button.configure(state="normal")

    # ---------- Группировка результатов ----------
    def _render_groups(self, plans):
        root = Path(self._cfg()["dest_root"])
        groups: dict[str, list] = {}
        for p in plans:
            try:
                key = str(p.target_dir.relative_to(root))
            except ValueError:
                key = str(p.target_dir)
            groups.setdefault(key, []).append(p)

        for key in sorted(groups):
            row = GroupRow(self.results, key, groups[key], on_toggle=self._update_summary)
            row.pack(fill="x", padx=2, pady=2)
            self.group_rows.append(row)
        self._update_summary()

    def _clear_results(self):
        for row in self.group_rows:
            row.destroy()
        self.group_rows.clear()
        self.plans = []
        self.progress.set(0)
        self.summary_label.configure(text="")

    def _update_summary(self):
        if not self.group_rows:
            self.summary_label.configure(text="")
            return
        selected = sum(len(r.plans) for r in self.group_rows if r.checkbox_var.get() and not r.done)
        self.summary_label.configure(
            text=f"Групп: {len(self.group_rows)} · Отмечено фото: {selected}")

    # ---------- Применение ----------
    def _start_apply(self):
        if self._busy:
            return
        rows = [r for r in self.group_rows if r.checkbox_var.get() and not r.done]
        if not rows:
            self._set_status("Нет отмеченных групп.", error=True)
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
        done = 0
        moved = 0
        duplicates = 0
        errors = 0
        first_error = None
        entries: list[Entry] = []
        for row in rows:
            for p in row.plans:
                try:
                    status, final = photo_organizer.apply(p, action=action)
                    entries.append(Entry(status=status, source=str(p.source), target=str(final)))
                    if status == organizer.STATUS_DUPLICATE:
                        duplicates += 1
                    else:
                        moved += 1
                except Exception as exc:  # noqa: BLE001 — считаем сбой, но продолжаем
                    errors += 1
                    if first_error is None:
                        first_error = str(exc)
                done += 1
                self.after(0, self._update_progress, done, total, p.source.name)
            self.after(0, row.mark_done)
        if entries and self.on_batch:
            self.after(0, self.on_batch, "photo", action, entries)
        self.after(0, self._apply_done, moved, duplicates, errors, first_error)

    def _apply_done(self, moved, duplicates, errors, first_error):
        self._busy = False
        self.scan_button.configure(state="normal")
        self.apply_button.configure(state="normal")
        verb = "скопировано" if self._cfg().get("action") == "copy" else "перемещено"
        parts = [f"{verb} {moved}"]
        if duplicates:
            parts.append(f"дубликатов {duplicates}")
        if errors:
            parts.append(f"ошибок {errors}")
        text = "Готово: " + ", ".join(parts) + " фото."
        if moved == 0 and duplicates and not errors:
            text += " Все фото уже были в папке назначения."
        if first_error:
            text += f" Первая ошибка: {first_error}"
        self._set_status(text, error=bool(errors))
        self.progress_label.configure(text="")
        self._update_summary()


class GroupRow(ctk.CTkFrame):
    """Строка группы: год/месяц + количество фото + галочка."""

    def __init__(self, master, key: str, plans: list, on_toggle=None):
        super().__init__(master, fg_color=_ROW_NORMAL)
        self.plans = plans
        self.done = False
        self.on_toggle = on_toggle
        self.grid_columnconfigure(2, weight=1)

        self.checkbox_var = ctk.BooleanVar(value=True)
        self.checkbox = ctk.CTkCheckBox(
            self, text="", width=28, variable=self.checkbox_var,
            onvalue=True, offvalue=False, command=self._on_toggle)
        self.checkbox.grid(row=0, column=0, padx=(6, 4), pady=8)

        exif = sum(1 for p in plans if p.date_from_exif)
        title = ctk.CTkLabel(
            self, text=f"📁 {key}", anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"))
        title.grid(row=0, column=1, sticky="w", padx=6)
        info = ctk.CTkLabel(
            self, text=f"{len(plans)} фото  ·  EXIF: {exif}, по дате файла: {len(plans) - exif}",
            anchor="w", text_color=("gray30", "gray70"))
        info.grid(row=0, column=2, sticky="w", padx=6)

        for w in (self, title, info):
            w.bind("<Button-1>", self._row_click)
        self._refresh()

    def _row_click(self, _e=None):
        if self.done:
            return
        self.checkbox_var.set(not self.checkbox_var.get())
        self._on_toggle()

    def _on_toggle(self):
        self._refresh()
        if self.on_toggle:
            self.on_toggle()

    def _refresh(self):
        if self.done:
            return
        self.configure(fg_color=_ROW_SELECTED if self.checkbox_var.get() else _ROW_NORMAL)

    def mark_done(self):
        self.done = True
        self.checkbox_var.set(False)
        self.checkbox.configure(state="disabled")
        self.configure(fg_color=("#e8f5e9", "#1b3a1e"))
