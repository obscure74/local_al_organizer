"""Главное окно приложения на CustomTkinter.

Вкладка «Документы»: проверка Ollama, сканирование папки, предпросмотр и
применение перемещений. Вкладка «Настройки»: пути и параметры модели.
Тяжёлые операции (скан, применение) выполняются в отдельном потоке, чтобы
интерфейс не «замерзал».
"""
from __future__ import annotations

import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from ..core import config as config_module
from ..core import filetypes, organizer, scanner
from ..core.ai_client import OllamaClient
from ..core.history import Entry, HistoryStore
from .photo_tab import PhotoTab
from .search_tab import SearchTab
from .summary_dialog import SummaryDialog

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Local AI Organizer")
        self.geometry("980x680")
        self.minsize(820, 560)

        self.config_data = config_module.load_config()
        ctk.set_appearance_mode(self.config_data.get("appearance", "System"))
        self.history = HistoryStore()
        self.plans: list[organizer.MovePlan] = []
        self.rows: list[ResultRow] = []
        self._scanning = False
        self._stop_requested = False

        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=12)
        self.tabs.add("Файлы")
        self.tabs.add("Фото")
        self.tabs.add("Поиск")
        self.tabs.add("История")
        self.tabs.add("Настройки")

        self._build_docs_tab(self.tabs.tab("Файлы"))
        self._build_settings_tab(self.tabs.tab("Настройки"))
        self._build_history_tab(self.tabs.tab("История"))

        # Поиск по разложенным файлам
        self.search_tab = SearchTab(self.tabs.tab("Поиск"), self.config_data)
        self.search_tab.pack(fill="both", expand=True)

        # Модуль 2: вкладка фотографий (сообщает о применённых пакетах в историю)
        self.photo_tab = PhotoTab(
            self.tabs.tab("Фото"), self.config_data, on_batch=self._record_batch)
        self.photo_tab.pack(fill="both", expand=True)

    # ---------- Вкладка «Документы» ----------
    def _build_docs_tab(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(2, weight=1)

        # Верхняя панель: статус Ollama + кнопки
        top = ctk.CTkFrame(parent)
        top.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 8))
        top.grid_columnconfigure(4, weight=1)

        ctk.CTkButton(
            top, text="Проверить Ollama", width=150, command=self._check_ollama
        ).grid(row=0, column=0, padx=6, pady=8)

        self.scan_button = ctk.CTkButton(
            top, text="Сканировать папку", width=160, command=self._start_scan
        )
        self.scan_button.grid(row=0, column=1, padx=6, pady=8)

        self.bulk_button = ctk.CTkButton(
            top, text="Изменить отмеченные", width=170,
            command=self._bulk_edit, state="disabled",
            fg_color=("gray70", "gray30"), hover_color=("gray60", "gray38"),
        )
        self.bulk_button.grid(row=0, column=2, padx=6, pady=8)

        self.apply_button = ctk.CTkButton(
            top, text="Применить отмеченные", width=180,
            command=self._start_apply, state="disabled",
        )
        self.apply_button.grid(row=0, column=3, padx=6, pady=8)

        self.status_label = ctk.CTkLabel(top, text="Готово к работе.", anchor="w")
        self.status_label.grid(row=0, column=4, sticky="ew", padx=10)

        # Панель прогресса
        progress_frame = ctk.CTkFrame(parent)
        progress_frame.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 8))
        progress_frame.grid_columnconfigure(0, weight=1)

        self.progress = ctk.CTkProgressBar(progress_frame)
        self.progress.set(0)
        self.progress.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        self.progress_label = ctk.CTkLabel(progress_frame, text="", width=220)
        self.progress_label.grid(row=0, column=1, padx=8)

        # Таблица результатов (заголовок + прокручиваемая область)
        header = ctk.CTkFrame(parent)
        header.grid(row=2, column=0, sticky="nsew", padx=4, pady=0)
        header.grid_columnconfigure(0, weight=1)
        header.grid_rowconfigure(1, weight=1)

        self.select_all_var = ctk.BooleanVar(value=True)
        head_row = ctk.CTkFrame(header, fg_color="transparent")
        head_row.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 2))
        ctk.CTkCheckBox(
            head_row, text="", width=28, variable=self.select_all_var,
            onvalue=True, offvalue=False, command=self._toggle_all,
        ).pack(side="left")
        ctk.CTkLabel(
            head_row, text="Файл  →  куда переедет", anchor="w",
            font=ctk.CTkFont(weight="bold"),
        ).pack(side="left", padx=4)

        self.results_frame = ctk.CTkScrollableFrame(header, label_text="")
        self.results_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        self.results_frame.grid_columnconfigure(0, weight=1)

        self.summary_label = ctk.CTkLabel(parent, text="", anchor="w")
        self.summary_label.grid(row=3, column=0, sticky="ew", padx=8, pady=(4, 2))

    # ---------- Вкладка «Настройки» ----------
    def _build_settings_tab(self, parent):
        parent.grid_columnconfigure(1, weight=1)
        self._setting_entries: dict[str, ctk.CTkEntry] = {}

        row = 0
        row = self._path_setting(parent, row, "Папка для сканирования (Загрузки):",
                                 self.config_data["source_folder"], "source_folder")
        row = self._path_setting(parent, row, "Куда складывать рабочее:",
                                 self.config_data["destinations"]["work_root"], "work_root")
        row = self._path_setting(parent, row, "Куда складывать личное:",
                                 self.config_data["destinations"]["personal_root"], "personal_root")
        row = self._path_setting(parent, row, "Куда складывать прочие типы (видео, таблицы…):",
                                 self.config_data["destinations"].get("files_root", ""), "files_root")

        # Действие: копировать/перемещать
        ctk.CTkLabel(parent, text="Действие с файлами:").grid(
            row=row, column=0, sticky="w", padx=10, pady=10)
        self.action_var = ctk.StringVar(value=self.config_data.get("action", "copy"))
        action_seg = ctk.CTkSegmentedButton(
            parent, values=["copy", "move"], variable=self.action_var)
        action_seg.grid(row=row, column=1, sticky="w", padx=10, pady=10)
        ctk.CTkLabel(
            parent, text="copy — копировать (безопасно), move — перемещать",
            text_color="gray",
        ).grid(row=row, column=2, sticky="w", padx=6)
        row += 1

        # Тема оформления
        ctk.CTkLabel(parent, text="Тема оформления:").grid(
            row=row, column=0, sticky="w", padx=10, pady=10)
        self.appearance_var = ctk.StringVar(value=self.config_data.get("appearance", "System"))
        ctk.CTkSegmentedButton(
            parent, values=["System", "Light", "Dark"], variable=self.appearance_var,
            command=lambda v: ctk.set_appearance_mode(v)).grid(
            row=row, column=1, sticky="w", padx=10, pady=10)
        row += 1

        # Хост и модель Ollama
        ctk.CTkLabel(parent, text="Адрес Ollama:").grid(
            row=row, column=0, sticky="w", padx=10, pady=10)
        host_entry = ctk.CTkEntry(parent)
        host_entry.insert(0, self.config_data["ollama"]["host"])
        host_entry.grid(row=row, column=1, sticky="ew", padx=10, pady=10)
        self._setting_entries["host"] = host_entry
        row += 1

        ctk.CTkLabel(parent, text="Модель:").grid(
            row=row, column=0, sticky="w", padx=10, pady=10)
        model_entry = ctk.CTkEntry(parent)
        model_entry.insert(0, self.config_data["ollama"]["model"])
        model_entry.grid(row=row, column=1, sticky="ew", padx=10, pady=10)
        self._setting_entries["model"] = model_entry
        row += 1

        ctk.CTkButton(parent, text="Сохранить настройки", command=self._save_settings).grid(
            row=row, column=1, sticky="w", padx=10, pady=20)

    def _path_setting(self, parent, row, label, value, key):
        ctk.CTkLabel(parent, text=label).grid(
            row=row, column=0, sticky="w", padx=10, pady=10)
        entry = ctk.CTkEntry(parent)
        entry.insert(0, value)
        entry.grid(row=row, column=1, sticky="ew", padx=10, pady=10)
        self._setting_entries[key] = entry
        ctk.CTkButton(
            parent, text="Обзор…", width=90,
            command=lambda e=entry: self._browse_folder(e),
        ).grid(row=row, column=2, padx=6)
        return row + 1

    def _browse_folder(self, entry: ctk.CTkEntry):
        folder = filedialog.askdirectory(initialdir=entry.get() or str(Path.home()))
        if folder:
            entry.delete(0, "end")
            entry.insert(0, folder)

    def _save_settings(self):
        self.config_data["source_folder"] = self._setting_entries["source_folder"].get().strip()
        self.config_data["destinations"]["work_root"] = self._setting_entries["work_root"].get().strip()
        self.config_data["destinations"]["personal_root"] = self._setting_entries["personal_root"].get().strip()
        self.config_data["destinations"]["files_root"] = self._setting_entries["files_root"].get().strip()
        self.config_data["action"] = self.action_var.get()
        self.config_data["appearance"] = self.appearance_var.get()
        self.config_data["ollama"]["host"] = self._setting_entries["host"].get().strip()
        self.config_data["ollama"]["model"] = self._setting_entries["model"].get().strip()
        config_module.save_config(self.config_data)
        self._set_status("Настройки сохранены.")

    # ---------- Логика ----------
    def _make_client(self) -> OllamaClient:
        o = self.config_data["ollama"]
        return OllamaClient(o["host"], o["model"], o.get("timeout", 120))

    def _check_ollama(self):
        ok, message = self._make_client().check_connection()
        self._set_status(message, error=not ok)

    def _start_scan(self):
        if self._scanning:
            return
        source = Path(self.config_data["source_folder"])
        if not source.is_dir():
            self._set_status(f"Папка не найдена: {source}", error=True)
            return

        # Ollama нужен только если среди файлов есть документы для ИИ.
        files = scanner.list_files(self.config_data)
        if not files:
            self._set_status("В папке нет файлов для обработки.")
            return
        if any(filetypes.is_ai_document(f) for f in files):
            ok, message = self._make_client().check_connection()
            if not ok:
                self._set_status(message, error=True)
                return

        self._scanning = True
        self._stop_requested = False
        self._clear_results()
        self.scan_button.configure(text="Остановить", command=self._request_stop)
        self.apply_button.configure(state="disabled")
        self.bulk_button.configure(state="disabled")
        self._set_status("Сканирование…")

        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _request_stop(self):
        self._stop_requested = True
        self._set_status("Останавливаю после текущего файла…")

    def _scan_worker(self):
        client = self._make_client()

        def progress(i, total, name):
            self.after(0, self._update_progress, i, total, name)

        try:
            plans = scanner.scan(
                self.config_data, client,
                progress=progress,
                stop_flag=lambda: self._stop_requested,
            )
        except Exception as exc:  # noqa: BLE001 — показываем любую ошибку пользователю
            self.after(0, self._scan_failed, str(exc))
            return

        self.after(0, self._scan_done, plans)

    def _update_progress(self, i, total, name):
        self.progress.set(i / total if total else 0)
        self.progress_label.configure(text=f"{i}/{total}: {name[:30]}")

    def _scan_failed(self, message):
        self._scanning = False
        self.scan_button.configure(text="Сканировать папку", command=self._start_scan)
        self._set_status(f"Ошибка сканирования: {message}", error=True)

    def _scan_done(self, plans: list[organizer.MovePlan]):
        self._scanning = False
        self.plans = plans
        self.scan_button.configure(text="Сканировать папку", command=self._start_scan)
        self._render_results(plans)

        errors = sum(1 for p in plans if p.classification.error)
        if not plans:
            self._set_status("В папке нет подходящих файлов.")
        elif errors:
            self._set_status(
                f"Готово: {len(plans)} файлов, из них {errors} с ошибкой ИИ.",
                error=True)
        else:
            self._set_status(f"Готово: обработано {len(plans)} файлов.")
        self.progress_label.configure(text="")
        if plans:
            self.apply_button.configure(state="normal")
            self.bulk_button.configure(state="normal")

    def _render_results(self, plans):
        for plan in plans:
            row = ResultRow(
                self.results_frame, plan, self.config_data,
                on_toggle=self._update_summary, on_edit=self._edit_row)
            row.pack(fill="x", padx=2, pady=2)
            self.rows.append(row)
        self._update_summary()

    def _edit_row(self, row):
        """Открывает окно правки целевой папки и имени файла для строки."""
        EditDialog(self, row)

    def _bulk_edit(self):
        """Массовая правка: отправить все отмеченные файлы в общую папку."""
        rows = [r for r in self.rows if r.checkbox_var.get() and not r.done]
        if not rows:
            self._set_status("Отметьте файлы галочками для массовой правки.", error=True)
            return
        BulkEditDialog(self, rows, self.config_data, on_done=self._after_bulk_edit)

    def _after_bulk_edit(self, count):
        self._set_status(f"Изменено назначение для {count} файлов.")
        self._update_summary()

    def _clear_results(self):
        for row in self.rows:
            row.destroy()
        self.rows.clear()
        self.plans.clear()
        self.progress.set(0)
        self.summary_label.configure(text="")

    def _toggle_all(self):
        value = self.select_all_var.get()
        for row in self.rows:
            if not row.done:
                row.checkbox_var.set(value)
                row._refresh_highlight()
        self._update_summary()

    def _update_summary(self):
        if not self.rows:
            self.summary_label.configure(text="")
            return
        selected = sum(1 for r in self.rows if r.checkbox_var.get() and not r.done)
        done = sum(1 for r in self.rows if r.done)
        self.summary_label.configure(
            text=f"Всего: {len(self.rows)} · Отмечено: {selected} · Перемещено: {done}")

    def _start_apply(self):
        if self._scanning:
            return
        to_apply = [r for r in self.rows if r.checkbox_var.get() and not r.done]
        if not to_apply:
            self._set_status("Нет отмеченных файлов для применения.", error=True)
            return
        self.apply_button.configure(state="disabled")
        self.scan_button.configure(state="disabled")
        self._set_status(f"Применяю {len(to_apply)} файлов…")
        threading.Thread(
            target=self._apply_worker, args=(to_apply,), daemon=True).start()

    def _apply_worker(self, rows):
        action = self.config_data.get("action", "copy")
        moved = 0
        duplicates = 0
        errors = 0
        entries: list[Entry] = []
        for row in rows:
            try:
                status, final = organizer.apply(row.plan, action=action)
                self.after(0, row.mark_done, status, final)
                entries.append(Entry(status=status, source=str(row.plan.source), target=str(final)))
                if status == organizer.STATUS_DUPLICATE:
                    duplicates += 1
                else:
                    moved += 1
            except Exception as exc:  # noqa: BLE001
                errors += 1
                self.after(0, row.mark_error, str(exc))
        if entries:
            self.after(0, self._record_batch, "docs", action, entries)
        self.after(0, self._apply_done, moved, duplicates, errors, len(rows))

    def _apply_done(self, moved, duplicates, errors, total):
        self.scan_button.configure(state="normal")
        self.apply_button.configure(state="normal")
        self.bulk_button.configure(state="normal")
        verb = "скопировано" if self.config_data.get("action") == "copy" else "перемещено"
        parts = [f"{verb} {moved} из {total}"]
        if duplicates:
            parts.append(f"дубликатов {duplicates}")
        if errors:
            parts.append(f"ошибок {errors}")
        text = "Готово: " + ", ".join(parts) + "."
        if moved == 0 and duplicates and not errors:
            text += " Эти файлы уже были в папке назначения."
        self._set_status(text, error=bool(errors))
        self._update_summary()

        dest = self.config_data["destinations"]
        SummaryDialog(
            self, action=self.config_data.get("action", "copy"),
            moved=moved, duplicates=duplicates, errors=errors,
            dest_folder=Path(dest.get("files_root") or dest["work_root"]))

    def _set_status(self, text, error=False):
        color = "#d9534f" if error else ("gray70", "gray30")
        self.status_label.configure(text=text, text_color=color if error else ("gray10", "gray90"))

    # ---------- Вкладка «История» ----------
    def _build_history_tab(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 2))
        ctk.CTkLabel(
            header, text="Последние операции — можно отменить (файлы вернутся на место)",
            anchor="w", font=ctk.CTkFont(weight="bold")).pack(side="left")
        ctk.CTkButton(header, text="Обновить", width=90,
                      command=self._refresh_history).pack(side="right")

        self.history_frame = ctk.CTkScrollableFrame(parent, label_text="")
        self.history_frame.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        self.history_frame.grid_columnconfigure(0, weight=1)
        self._history_status = ctk.CTkLabel(parent, text="", anchor="w")
        self._history_status.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 4))
        self._refresh_history()

    def _record_batch(self, module, action, entries):
        """Записывает применённый пакет в историю и обновляет вкладку."""
        self.history.add(module, action, entries)
        self._refresh_history()

    def _refresh_history(self):
        for child in self.history_frame.winfo_children():
            child.destroy()
        batches = self.history.recent()
        if not batches:
            ctk.CTkLabel(self.history_frame, text="Пока нет операций.",
                         text_color=("gray40", "gray60")).pack(padx=8, pady=8)
            return
        for batch in batches:
            self._history_row(batch)

    def _history_row(self, batch):
        row = ctk.CTkFrame(self.history_frame)
        row.pack(fill="x", padx=2, pady=3)
        row.grid_columnconfigure(1, weight=1)

        module_name = "Файлы" if batch.module == "docs" else "Фото"
        verb = "скопировано" if batch.action == "copy" else "перемещено"
        title = f"{batch.when()}  ·  {module_name}  ·  {verb} {batch.moved_count}"
        ctk.CTkLabel(row, text=title, anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=8, pady=8)

        if batch.undone:
            ctk.CTkLabel(row, text="↩ отменено", text_color=("gray40", "gray60")).grid(
                row=0, column=2, padx=10)
        else:
            ctk.CTkButton(row, text="Отменить", width=100,
                          command=lambda b=batch: self._undo_batch(b.id)).grid(
                row=0, column=2, padx=8, pady=6)

    def _undo_batch(self, batch_id):
        stats = self.history.undo(batch_id)
        parts = []
        if stats["restored"]:
            parts.append(f"возвращено {stats['restored']}")
        if stats["removed"]:
            parts.append(f"удалено копий {stats['removed']}")
        if stats["skipped"]:
            parts.append(f"пропущено {stats['skipped']}")
        if stats["problems"]:
            parts.append(f"не удалось {stats['problems']}")
        self._history_status.configure(
            text="Отмена: " + (", ".join(parts) if parts else "нечего откатывать"),
            text_color="#d9534f" if stats["problems"] else ("gray10", "gray90"))
        self._refresh_history()

    def _set_history_status(self, text):
        self._history_status.configure(text=text)


# Цвета подсветки строки: (светлая тема, тёмная тема)
_ROW_SELECTED = ("#dbeafe", "#1e3a5f")
_ROW_NORMAL = ("gray92", "gray16")


class ResultRow(ctk.CTkFrame):
    """Одна строка предпросмотра: галочка + исходный файл + куда переедет."""

    def __init__(self, master, plan: organizer.MovePlan, config: dict,
                 on_toggle=None, on_edit=None):
        super().__init__(master, fg_color=_ROW_NORMAL)
        self.plan = plan
        self.config = config
        self.done = False
        self.on_toggle = on_toggle
        self.on_edit = on_edit
        self.grid_columnconfigure(2, weight=1)

        cls = plan.classification
        # Галочка всегда активна: даже нераспознанный файл можно переместить
        # (он попадёт в Личное/Разное). По умолчанию отмечаем только успешные.
        self.checkbox_var = ctk.BooleanVar(value=not bool(cls.error))
        self.checkbox = ctk.CTkCheckBox(
            self, text="", width=28, variable=self.checkbox_var,
            onvalue=True, offvalue=False, command=self._on_toggle)
        self.checkbox.grid(row=0, column=0, rowspan=2, padx=(6, 4), pady=6)

        # Метка категории
        if cls.error:
            badge_text, badge_color = " ⚠ НЕ РАСПОЗНАНО ", "#d9534f"
        elif cls.scope == "typed":
            badge_text, badge_color = f" {cls.doc_type} ", "#6a4c93"
        else:
            scope_text = "РАБОЧЕЕ" if cls.scope == "work" else "ЛИЧНОЕ"
            badge_color = "#2e7d32" if cls.scope == "work" else "#1565c0"
            badge_text = f" {scope_text} · {cls.doc_type} "
        badge = ctk.CTkLabel(
            self, text=badge_text, fg_color=badge_color, corner_radius=6,
            text_color="white", font=ctk.CTkFont(size=11, weight="bold"))
        badge.grid(row=0, column=1, sticky="w", padx=4, pady=(6, 0))

        name_label = ctk.CTkLabel(
            self, text=plan.source.name, anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"))
        name_label.grid(row=0, column=2, sticky="w", padx=6, pady=(6, 0))

        # Куда переедет (относительный путь от корня назначения)
        if cls.error:
            target_text = f"⚠ {cls.error}"
            target_color = "#d9534f"
        else:
            target_text = self._relative_target(plan, config)
            target_color = ("gray30", "gray70")
        self.target_label = ctk.CTkLabel(
            self, text=target_text, anchor="w", text_color=target_color)
        self.target_label.grid(row=1, column=1, columnspan=2, sticky="w", padx=6, pady=(0, 6))

        # Кнопка правки целевой папки/имени
        self.edit_button = ctk.CTkButton(
            self, text="✎", width=34, command=self._edit,
            fg_color=("gray80", "gray28"), hover_color=("gray70", "gray35"),
            text_color=("gray10", "gray90"))
        self.edit_button.grid(row=0, column=3, rowspan=2, padx=(2, 6), pady=6)

        # Клик по любой части строки тоже переключает галочку
        for widget in (self, badge, name_label, self.target_label):
            widget.bind("<Button-1>", self._row_click)

        self._refresh_highlight()

    def _edit(self):
        if self.done or not self.on_edit:
            return
        self.on_edit(self)

    def update_target(self, new_target: Path):
        """Обновляет план и подпись после ручной правки."""
        self.plan.target = new_target
        self.target_label.configure(
            text=self._relative_target(self.plan, self.config),
            text_color=("gray30", "gray70"))

    def _row_click(self, _event=None):
        if self.done:
            return
        self.checkbox_var.set(not self.checkbox_var.get())
        self._on_toggle()

    def _on_toggle(self):
        self._refresh_highlight()
        if self.on_toggle:
            self.on_toggle()

    def _refresh_highlight(self):
        if self.done:
            return
        self.configure(fg_color=_ROW_SELECTED if self.checkbox_var.get() else _ROW_NORMAL)

    def _relative_target(self, plan, config):
        dest = config["destinations"]
        roots = [Path(dest["work_root"]), Path(dest["personal_root"])]
        if dest.get("files_root"):
            roots.append(Path(dest["files_root"]))
        target = plan.target
        for root in roots:
            try:
                return "→  " + str(target.relative_to(root.parent))
            except ValueError:
                continue
        return "→  " + str(target)

    def mark_done(self, status: str, final_path: Path):
        self.done = True
        self.checkbox_var.set(False)
        self.checkbox.configure(state="disabled")
        if status == organizer.STATUS_DUPLICATE:
            self.configure(fg_color=("#fff8e1", "#3a2f14"))
            self.target_label.configure(
                text=f"⏭  Уже есть, пропущено: {final_path}", text_color="#b8860b")
        else:
            verb = "Перемещён" if status == organizer.STATUS_MOVED else "Скопирован"
            self.configure(fg_color=("#e8f5e9", "#1b3a1e"))
            self.target_label.configure(text=f"✓  {verb}: {final_path}", text_color="#2e7d32")

    def mark_error(self, message: str):
        self.target_label.configure(text=f"✗  Ошибка: {message}", text_color="#d9534f")


class EditDialog(ctk.CTkToplevel):
    """Окно правки целевой папки и имени файла для одной строки предпросмотра."""

    def __init__(self, master, row: ResultRow):
        super().__init__(master)
        self.row = row
        self.title("Изменить назначение")
        self.geometry("640x230")
        self.resizable(False, False)
        self.grid_columnconfigure(1, weight=1)

        target = row.plan.target
        ctk.CTkLabel(self, text=f"Файл: {row.plan.source.name}",
                     font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(16, 8))

        ctk.CTkLabel(self, text="Папка назначения:").grid(
            row=1, column=0, sticky="w", padx=14, pady=8)
        self.folder_entry = ctk.CTkEntry(self)
        self.folder_entry.insert(0, str(target.parent))
        self.folder_entry.grid(row=1, column=1, sticky="ew", padx=6, pady=8)
        ctk.CTkButton(self, text="Обзор…", width=80, command=self._browse).grid(
            row=1, column=2, padx=(6, 14))

        ctk.CTkLabel(self, text="Имя файла:").grid(
            row=2, column=0, sticky="w", padx=14, pady=8)
        self.name_entry = ctk.CTkEntry(self)
        self.name_entry.insert(0, target.name)
        self.name_entry.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(6, 14), pady=8)

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=3, column=0, columnspan=3, sticky="e", padx=14, pady=(16, 12))
        ctk.CTkButton(buttons, text="Отмена", width=100, fg_color=("gray70", "gray30"),
                      command=self.destroy).pack(side="left", padx=6)
        ctk.CTkButton(buttons, text="Сохранить", width=120, command=self._save).pack(side="left")

        # Модальное окно поверх основного
        self.transient(master)
        self.after(100, self.grab_set)
        self.name_entry.focus_set()

    def _browse(self):
        folder = filedialog.askdirectory(initialdir=self.folder_entry.get() or str(Path.home()))
        if folder:
            self.folder_entry.delete(0, "end")
            self.folder_entry.insert(0, folder)

    def _save(self):
        folder = self.folder_entry.get().strip()
        name = self.name_entry.get().strip()
        if not folder or not name:
            return
        self.row.update_target(Path(folder) / name)
        self.destroy()


class BulkEditDialog(ctk.CTkToplevel):
    """Массовая правка: отправить все отмеченные файлы в общую папку.

    Имена файлов сохраняются (включая сгенерированные ИИ), меняется только
    папка назначения. Кнопки-категории быстро подставляют типовые пути.
    """

    def __init__(self, master, rows: list[ResultRow], config: dict, on_done=None):
        super().__init__(master)
        self.rows = rows
        self.config = config
        self.on_done = on_done
        self.title("Массовая правка")
        self.geometry("620x300")
        self.resizable(False, False)
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self, text=f"Отмечено файлов: {len(rows)}",
            font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(16, 4))
        ctk.CTkLabel(
            self, text="Все они отправятся в одну папку (имена сохранятся).",
            text_color=("gray30", "gray70")).grid(
            row=1, column=0, columnspan=3, sticky="w", padx=14, pady=(0, 8))

        ctk.CTkLabel(self, text="Папка назначения:").grid(
            row=2, column=0, sticky="w", padx=14, pady=8)
        self.folder_entry = ctk.CTkEntry(self)
        self.folder_entry.grid(row=2, column=1, sticky="ew", padx=6, pady=8)
        ctk.CTkButton(self, text="Обзор…", width=80, command=self._browse).grid(
            row=2, column=2, padx=(6, 14))

        # Быстрые кнопки категорий
        ctk.CTkLabel(self, text="Быстрый выбор:").grid(
            row=3, column=0, sticky="nw", padx=14, pady=8)
        quick = ctk.CTkScrollableFrame(self, height=70, orientation="horizontal",
                                       fg_color="transparent")
        quick.grid(row=3, column=1, columnspan=2, sticky="ew", padx=6, pady=4)
        for label, folder in self._quick_targets().items():
            ctk.CTkButton(
                quick, text=label, width=110, height=28,
                fg_color=("gray75", "gray30"), hover_color=("gray65", "gray40"),
                command=lambda f=folder: self._set_folder(f)).pack(side="left", padx=3)

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=4, column=0, columnspan=3, sticky="e", padx=14, pady=(16, 12))
        ctk.CTkButton(buttons, text="Отмена", width=100, fg_color=("gray70", "gray30"),
                      command=self.destroy).pack(side="left", padx=6)
        ctk.CTkButton(buttons, text="Применить ко всем", width=160, command=self._save).pack(side="left")

        self.transient(master)
        self.after(100, self.grab_set)

    def _quick_targets(self) -> dict[str, Path]:
        """Ярлыки папок: рабочее/личное + основные категории типовых файлов."""
        dest = self.config["destinations"]
        targets: dict[str, Path] = {
            "Рабочее": Path(dest["work_root"]),
            "Личное": Path(dest["personal_root"]),
        }
        files_root = Path(dest.get("files_root", dest["personal_root"]))
        for category in ("Документы", "Таблицы", "Видео", "Аудио", "Изображения", "Архивы"):
            targets[category] = files_root / category
        return targets

    def _set_folder(self, folder: Path):
        self.folder_entry.delete(0, "end")
        self.folder_entry.insert(0, str(folder))

    def _browse(self):
        folder = filedialog.askdirectory(initialdir=self.folder_entry.get() or str(Path.home()))
        if folder:
            self._set_folder(Path(folder))

    def _save(self):
        folder = self.folder_entry.get().strip()
        if not folder:
            return
        for row in self.rows:
            row.update_target(Path(folder) / row.plan.target.name)
        if self.on_done:
            self.on_done(len(self.rows))
        self.destroy()


def run():
    app = MainWindow()
    app.mainloop()
