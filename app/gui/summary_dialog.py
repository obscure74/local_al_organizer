"""Итоговое окно со сводкой после раскладки файлов.

Показывает наглядно, что произошло: сколько файлов перенесено, сколько
пропущено как дубликаты и сколько завершилось ошибкой. Появляется после
нажатия «Применить» на вкладках «Файлы» и «Фото».
"""
from __future__ import annotations

import contextlib
import os
from pathlib import Path

import customtkinter as ctk


class SummaryDialog(ctk.CTkToplevel):
    """Модальное окно с результатами операции."""

    def __init__(
        self,
        master,
        action: str,
        moved: int,
        duplicates: int = 0,
        errors: int = 0,
        dest_folder: Path | None = None,
        first_error: str = "",
    ):
        super().__init__(master)
        self.dest_folder = dest_folder

        self.title("Результат")
        self.geometry("480x330")
        self.resizable(False, False)
        self.grid_columnconfigure(0, weight=1)

        moved_label = "Скопировано" if action == "copy" else "Перемещено"
        # Заголовок отражает суть: успех, «всё уже на месте» или проблемы
        if errors:
            head, head_color = "Завершено с ошибками", "#d9534f"
        elif moved == 0 and duplicates:
            head, head_color = "Новых файлов не было", "#b8860b"
        elif moved == 0:
            head, head_color = "Нечего переносить", ("gray30", "gray70")
        else:
            head, head_color = "Готово!", "#2e7d32"

        ctk.CTkLabel(
            self, text=head, font=ctk.CTkFont(size=20, weight="bold"),
            text_color=head_color).grid(row=0, column=0, pady=(20, 12))

        stats = ctk.CTkFrame(self)
        stats.grid(row=1, column=0, sticky="ew", padx=20)
        stats.grid_columnconfigure((0, 1, 2), weight=1)
        self._stat(stats, 0, moved_label, moved, "#2e7d32")
        self._stat(stats, 1, "Дубликаты", duplicates, "#b8860b")
        self._stat(stats, 2, "Ошибки", errors, "#d9534f" if errors else ("gray50", "gray50"))

        # Пояснение под цифрами
        note = ""
        if moved == 0 and duplicates and not errors:
            note = ("Все файлы уже лежали в папке назначения, поэтому копии не создавались.\n"
                    "Это не ошибка — дубликаты не плодятся.")
        elif errors and first_error:
            note = f"Первая ошибка: {first_error}"
        elif moved:
            note = "Файлы разложены по папкам. Операцию можно отменить во вкладке «История»."
        if note:
            ctk.CTkLabel(self, text=note, wraplength=420, justify="left",
                         text_color=("gray30", "gray70")).grid(
                row=2, column=0, padx=20, pady=(14, 4), sticky="w")

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=3, column=0, pady=(16, 16))
        if dest_folder is not None:
            ctk.CTkButton(buttons, text="Открыть папку", width=140,
                          command=self._open_folder).pack(side="left", padx=6)
        ctk.CTkButton(buttons, text="Закрыть", width=120,
                      fg_color=("gray70", "gray30"), command=self.destroy).pack(side="left", padx=6)

        self.transient(master)
        self.after(100, self.grab_set)

    def _stat(self, parent, column: int, title: str, value: int, color):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=0, column=column, padx=8, pady=14)
        ctk.CTkLabel(box, text=str(value), font=ctk.CTkFont(size=28, weight="bold"),
                     text_color=color).pack()
        ctk.CTkLabel(box, text=title, text_color=("gray30", "gray70")).pack()

    def _open_folder(self):
        if self.dest_folder is None:
            return
        with contextlib.suppress(OSError, AttributeError):
            os.startfile(str(self.dest_folder))
