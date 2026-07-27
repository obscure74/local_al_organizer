"""Извлечение текста из файлов разных форматов.

Поддержка: PDF, DOCX, TXT/MD/RTF. OCR для сканов и картинок — опционально
(включается автоматически, если установлены pytesseract + Pillow + Tesseract).
Если текст извлечь не удалось, возвращается пустая строка — классификатор
в этом случае опирается на имя файла.
"""
from __future__ import annotations

from pathlib import Path

# OCR подключаем "мягко": если библиотек нет, приложение всё равно работает.
try:
    import pytesseract
    from PIL import Image

    _OCR_AVAILABLE = True
except ImportError:
    _OCR_AVAILABLE = False

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}


def extract_text(path: Path, max_chars: int = 4000) -> str:
    """Возвращает текст файла, обрезанный до max_chars символов."""
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            text = _read_pdf(path)
        elif ext == ".docx":
            text = _read_docx(path)
        elif ext in {".txt", ".md", ".rtf"}:
            text = _read_plain(path)
        elif ext in IMAGE_EXTS:
            text = _read_image_ocr(path)
        else:
            text = ""
    except Exception:
        # Любая ошибка чтения не должна ронять весь скан
        text = ""

    text = (text or "").strip()
    return text[:max_chars]


def _read_pdf(path: Path) -> str:
    import pdfplumber

    parts: list[str] = []
    with pdfplumber.open(path) as pdf:
        # Первых нескольких страниц обычно достаточно для классификации
        for page in pdf.pages[:5]:
            parts.append(page.extract_text() or "")
    text = "\n".join(parts).strip()

    # Скан без текстового слоя — пробуем OCR
    if not text and _OCR_AVAILABLE:
        text = _read_pdf_ocr(path)
    return text


def _read_pdf_ocr(path: Path) -> str:
    """OCR первой страницы PDF (для сканов). Требует pdfplumber + pytesseract."""
    import pdfplumber

    parts: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages[:3]:
            image = page.to_image(resolution=200).original
            parts.append(pytesseract.image_to_string(image, lang="rus+eng"))
    return "\n".join(parts).strip()


def _read_docx(path: Path) -> str:
    import docx

    document = docx.Document(str(path))
    return "\n".join(p.text for p in document.paragraphs).strip()


def _read_plain(path: Path) -> str:
    # utf-8 с откатом к cp1251 (частая кодировка для русских txt из Windows)
    for encoding in ("utf-8", "cp1251"):
        try:
            return path.read_text(encoding=encoding).strip()
        except (UnicodeDecodeError, OSError):
            continue
    return ""


def _read_image_ocr(path: Path) -> str:
    if not _OCR_AVAILABLE:
        return ""
    image = Image.open(path)
    return pytesseract.image_to_string(image, lang="rus+eng").strip()


def ocr_available() -> bool:
    """True, если OCR-стек установлен и готов к работе."""
    return _OCR_AVAILABLE
