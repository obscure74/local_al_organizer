"""Вкладка «Лица» — раскладка фотографий по людям.

Сначала вы показываете приложению, кто есть кто («это я», «это мама»),
загрузив по нескольку эталонных снимков. Затем оно проходит по папке с фото
и раскладывает их по папкам людей. Всё считается локально.
"""
from __future__ import annotations

import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from ..core import config as config_module
from ..core import face_organizer, faces
from .summary_dialog import SummaryDialog

_ROW_SELECTED = ("#dbeafe", "#1e3a5f")
_ROW_NORMAL = ("gray92", "gray16")


class FacesTab(ctk.CTkFrame):
    def __init__(self, master, config_data: dict, on_batch=None):
        super().__init__(master, fg_color="transparent")
        self.config_data = config_data
        self.on_batch = on_batch
        self.store = faces.PeopleStore()
        self.plans: list[face_organizer.FacePlan] = []
        self.group_rows: list[PersonGroupRow] = []
        self._busy = False
        self._stop = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        self._build_models_bar()
        self._build_people_bar()
        self._build_scan_bar()
        self._build_results()
        self._refresh_models_state()
        self._refresh_people()

    def _cfg(self) -> dict:
        return self.config_data["faces"]

    # ---------- Панель моделей ----------
    def _build_models_bar(self):
        self.models_frame = ctk.CTkFrame(self)
        self.models_frame.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 6))
        self.models_frame.grid_columnconfigure(0, weight=1)
        self.models_label = ctk.CTkLabel(self.models_frame, text="", anchor="w")
        self.models_label.grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        self.models_button = ctk.CTkButton(
            self.models_frame, text="Скачать модели", width=150,
            command=self._download_models)
        self.models_button.grid(row=0, column=1, padx=8, pady=8)

    def _refresh_models_state(self):
        if faces.models_ready():
            self.models_frame.grid_remove()  # всё готово — панель не нужна
            return
        self.models_frame.grid()
        missing = ", ".join(faces.missing_models())
        self.models_label.configure(
            text=f"Для распознавания нужны модели OpenCV (~39 МБ): {missing}",
            text_color="#b8860b")

    def _download_models(self):
        self.models_button.configure(state="disabled", text="Скачиваю…")

        def worker():
            try:
                faces.download_models(progress=lambda n, done, total: self.after(
                    0, self.models_label.configure,
                    {"text": f"Скачиваю {n}: {done * 100 // max(total, 1)}%"}))
            except Exception as exc:  # noqa: BLE001
                self.after(0, self._models_failed, str(exc))
                return
            self.after(0, self._models_done)

        threading.Thread(target=worker, daemon=True).start()

    def _models_done(self):
        self.models_button.configure(state="normal", text="Скачать модели")
        self._refresh_models_state()
        self._set_status("Модели загружены — распознавание готово к работе.")

    def _models_failed(self, message):
        self.models_button.configure(state="normal", text="Скачать модели")
        self.models_label.configure(text=f"Не удалось скачать: {message}",
                                    text_color="#d9534f")

    # ---------- Панель людей ----------
    def _build_people_bar(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 6))
        frame.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 0))
        ctk.CTkLabel(header, text="Кого узнавать:",
                     font=ctk.CTkFont(weight="bold")).pack(side="left", padx=4)
        ctk.CTkButton(header, text="Добавить человека", width=160,
                      command=self._add_person).pack(side="right", padx=4)

        self.people_frame = ctk.CTkScrollableFrame(
            frame, height=90, orientation="horizontal", fg_color="transparent")
        self.people_frame.grid(row=1, column=0, sticky="ew", padx=6, pady=6)

    def _refresh_people(self):
        for child in self.people_frame.winfo_children():
            child.destroy()
        if not self.store.people:
            ctk.CTkLabel(
                self.people_frame,
                text="Пока никого нет. Нажмите «Добавить человека» и укажите"
                     " несколько его фото — лучше там, где он один в кадре.",
                text_color=("gray40", "gray60")).pack(padx=8, pady=10)
            return
        for person in self.store.people:
            card = ctk.CTkFrame(self.people_frame)
            card.pack(side="left", padx=4, pady=4)
            ctk.CTkLabel(card, text=person.name,
                         font=ctk.CTkFont(size=13, weight="bold")).pack(padx=10, pady=(8, 0))
            ctk.CTkLabel(card, text=f"эталонов: {person.sample_count}",
                         text_color=("gray30", "gray70")).pack(padx=10)
            buttons = ctk.CTkFrame(card, fg_color="transparent")
            buttons.pack(padx=8, pady=(2, 8))
            ctk.CTkButton(buttons, text="+ фото", width=70, height=24,
                          command=lambda n=person.name: self._add_samples(n)).pack(side="left", padx=2)
            ctk.CTkButton(buttons, text="Удалить", width=70, height=24,
                          fg_color=("gray70", "gray30"),
                          command=lambda n=person.name: self._remove_person(n)).pack(side="left", padx=2)

    def _add_person(self):
        if not self._require_models():
            return
        dialog = ctk.CTkInputDialog(text="Имя человека (например: Я, Мама, Брат):",
                                    title="Новый человек")
        name = (dialog.get_input() or "").strip()
        if not name:
            return
        self._add_samples(name)

    def _add_samples(self, name: str):
        if not self._require_models():
            return
        files = filedialog.askopenfilenames(
            title=f"Выберите фото: {name} (лучше где он(а) один в кадре)",
            filetypes=[("Изображения", "*.jpg *.jpeg *.png *.bmp *.webp"), ("Все файлы", "*.*")])
        if not files:
            return
        self._set_status(f"Обрабатываю эталонные фото ({len(files)})…")

        def worker():
            try:
                added = self.store.add_samples(name, [Path(f) for f in files])
            except Exception as exc:  # noqa: BLE001
                self.after(0, self._set_status, f"Ошибка: {exc}", True)
                return
            self.after(0, self._samples_done, name, added, len(files))

        threading.Thread(target=worker, daemon=True).start()

    def _samples_done(self, name, added, total):
        self._refresh_people()
        if added:
            self._set_status(f"{name}: распознано лиц на {added} из {total} фото.")
        else:
            self._set_status(
                f"{name}: лиц не найдено ни на одном фото. Выберите снимки,"
                " где лицо крупное и хорошо видно.", error=True)

    def _remove_person(self, name: str):
        self.store.remove(name)
        self._refresh_people()
        self._set_status(f"Удалён: {name}")

    def _require_models(self) -> bool:
        if faces.models_ready():
            return True
        self._set_status("Сначала скачайте модели распознавания.", error=True)
        self._refresh_models_state()
        return False

    # ---------- Панель сканирования ----------
    def _build_scan_bar(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=2, column=0, sticky="ew", padx=4, pady=(0, 6))
        frame.grid_columnconfigure(1, weight=1)
        cfg = self._cfg()

        ctk.CTkLabel(frame, text="Папка с фото:").grid(
            row=0, column=0, sticky="w", padx=8, pady=6)
        self.source_entry = ctk.CTkEntry(frame)
        self.source_entry.insert(0, cfg["source_folder"])
        self.source_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=6)
        ctk.CTkButton(frame, text="Обзор…", width=90,
                      command=lambda: self._browse(self.source_entry)).grid(row=0, column=2, padx=6)

        ctk.CTkLabel(frame, text="Куда раскладывать:").grid(
            row=1, column=0, sticky="w", padx=8, pady=6)
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
        self.no_faces_var = ctk.BooleanVar(value=cfg.get("separate_no_faces", True))
        ctk.CTkCheckBox(opts, text="Фото без людей — отдельно", variable=self.no_faces_var,
                        onvalue=True, offvalue=False).pack(side="left", padx=8)
        ctk.CTkLabel(opts, text="Действие:").pack(side="left", padx=(16, 4))
        self.action_var = ctk.StringVar(value=cfg.get("action", "copy"))
        ctk.CTkSegmentedButton(opts, values=["copy", "move"],
                               variable=self.action_var).pack(side="left")

        buttons = ctk.CTkFrame(frame, fg_color="transparent")
        buttons.grid(row=3, column=0, columnspan=3, sticky="ew", padx=4, pady=(0, 6))
        buttons.grid_columnconfigure(2, weight=1)
        self.scan_button = ctk.CTkButton(buttons, text="Найти людей на фото", width=170,
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
        self.results = ctk.CTkScrollableFrame(self, label_text="Кто найден на фотографиях")
        self.results.grid(row=3, column=0, sticky="nsew", padx=4, pady=4)
        self.results.grid_columnconfigure(0, weight=1)

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
        cfg["separate_no_faces"] = self.no_faces_var.get()
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
        if not self._require_models():
            return
        if not self.store.people:
            self._set_status(
                "Сначала добавьте хотя бы одного человека — иначе некого узнавать.",
                error=True)
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
        self._set_status("Ищу лица на фотографиях… это может занять время.")
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        def progress(i, total, name):
            self.after(0, self._update_progress, i, total, name)

        try:
            plans = face_organizer.scan(
                self._cfg(), self.store, progress=progress, stop_flag=lambda: self._stop)
        except Exception as exc:  # noqa: BLE001
            self.after(0, self._scan_failed, str(exc))
            return
        self.after(0, self._scan_done, plans)

    def _update_progress(self, i, total, name):
        self.progress.set(i / total if total else 0)
        self.progress_label.configure(text=f"{i}/{total}: {name[:24]}")

    def _scan_failed(self, message):
        self._busy = False
        self.scan_button.configure(text="Найти людей на фото")
        self._set_status(f"Ошибка: {message}", error=True)

    def _scan_done(self, plans):
        self._busy = False
        self.plans = plans
        self.scan_button.configure(text="Найти людей на фото")
        self.progress_label.configure(text="")
        if not plans:
            self._set_status("Фотографий не найдено (или ни на одной нет лиц).")
            return

        groups = face_organizer.group_by_person(plans)
        for person in sorted(groups, key=lambda p: (p in (
                face_organizer.UNKNOWN_FOLDER, face_organizer.NO_FACES_FOLDER), p)):
            row = PersonGroupRow(self.results, person, groups[person])
            row.pack(fill="x", padx=2, pady=2)
            self.group_rows.append(row)

        known = sum(len(v) for k, v in groups.items()
                    if k not in (face_organizer.UNKNOWN_FOLDER, face_organizer.NO_FACES_FOLDER))
        self._set_status(f"Готово: узнано снимков {known}, всего записей {len(plans)}.")
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
            self._set_status("Отметьте, кого раскладывать.", error=True)
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
                    status, final = face_organizer.apply(plan, action=action)
                    entries.append(Entry(status=status, source=str(plan.source), target=str(final)))
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
            self.after(0, self.on_batch, "faces", action, entries)
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


class PersonGroupRow(ctk.CTkFrame):
    """Строка результата: человек + сколько его фото найдено."""

    def __init__(self, master, person: str, plans: list):
        super().__init__(master, fg_color=_ROW_NORMAL)
        self.person = person
        self.plans = plans
        self.done = False
        self.grid_columnconfigure(2, weight=1)

        self.checkbox_var = ctk.BooleanVar(value=True)
        self.checkbox = ctk.CTkCheckBox(self, text="", width=28, variable=self.checkbox_var,
                                        onvalue=True, offvalue=False, command=self._refresh)
        self.checkbox.grid(row=0, column=0, padx=(6, 4), pady=8)

        if person == face_organizer.NO_FACES_FOLDER:
            icon, color = "🖼", "#6a4c93"
            title = "Без людей (скриншоты, картинки)"
        elif person == face_organizer.UNKNOWN_FOLDER:
            icon, color = "❓", "#b8860b"
            title = "Неизвестные (лица есть, но не узнаны)"
        else:
            icon, color = "👤", "#1565c0"
            title = person

        ctk.CTkLabel(self, text=f" {icon} ", fg_color=color, corner_radius=6,
                     text_color="white").grid(row=0, column=1, padx=4)
        label = ctk.CTkLabel(self, text=f"{title}  —  {len(plans)} фото", anchor="w",
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
