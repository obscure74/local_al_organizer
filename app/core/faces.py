"""Распознавание лиц на фотографиях (локально, через OpenCV).

Использует две ONNX-модели из официального репозитория OpenCV Zoo:
  * YuNet  — находит лица на изображении;
  * SFace  — превращает лицо в вектор признаков (эмбеддинг), по которому
             можно понять, один и тот же это человек или разные.

Всё считается на вашем компьютере, интернет нужен только один раз — чтобы
скачать модели. Никакие фотографии никуда не отправляются.

Два сценария:
  1. Детекция — есть ли на фото люди (отделить живые фото от скриншотов).
  2. Узнавание — кто именно на фото (раскладка по людям).
"""
from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

from .config import BASE_DIR

MODELS_DIR = BASE_DIR / "models"
DETECTOR_FILE = MODELS_DIR / "face_detection_yunet_2023mar.onnx"
RECOGNIZER_FILE = MODELS_DIR / "face_recognition_sface_2021dec.onnx"
PEOPLE_PATH = BASE_DIR / "people.json"

# Откуда скачиваются модели (официальный репозиторий OpenCV)
MODEL_URLS = {
    DETECTOR_FILE.name: (
        "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "face_detection_yunet/face_detection_yunet_2023mar.onnx"
    ),
    RECOGNIZER_FILE.name: (
        "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "face_recognition_sface/face_recognition_sface_2021dec.onnx"
    ),
}

# Порог косинусного сходства для SFace: выше — тот же человек.
# 0.363 — значение, рекомендованное авторами модели.
SIMILARITY_THRESHOLD = 0.363

# Перед детекцией уменьшаем снимок: на 24-мегапиксельных фото это ускоряет
# обработку в разы, а качество распознавания практически не страдает.
MAX_SIDE = 1024

_detector = None
_recognizer = None


class FacesUnavailable(Exception):
    """OpenCV не установлен или модели не скачаны."""


def models_ready() -> bool:
    """True, если обе модели на месте и OpenCV доступен."""
    if not (DETECTOR_FILE.exists() and RECOGNIZER_FILE.exists()):
        return False
    try:
        import cv2  # noqa: F401
    except ImportError:
        return False
    return True


def missing_models() -> list[str]:
    """Имена недостающих файлов моделей."""
    return [f.name for f in (DETECTOR_FILE, RECOGNIZER_FILE) if not f.exists()]


def download_models(progress=None) -> None:
    """Скачивает недостающие модели из репозитория OpenCV.

    progress(имя_файла, скачано_байт, всего_байт) — колбэк для интерфейса.
    Вызывается только по явному действию пользователя.
    """
    import urllib.request

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    for name in missing_models():
        target = MODELS_DIR / name

        def hook(block, block_size, total, _name=name):
            if progress:
                progress(_name, min(block * block_size, total), total)

        # Скачиваем во временный файл, чтобы прерванная загрузка не оставила
        # битую модель под правильным именем.
        tmp = target.with_suffix(".part")
        urllib.request.urlretrieve(MODEL_URLS[name], tmp, reporthook=hook)
        tmp.replace(target)


def _get_models():
    """Ленивая загрузка моделей — один раз за сессию."""
    global _detector, _recognizer
    if _detector is not None and _recognizer is not None:
        return _detector, _recognizer

    try:
        import cv2
    except ImportError as exc:
        raise FacesUnavailable(
            "Не установлен OpenCV. Выполните: pip install opencv-python"
        ) from exc

    missing = missing_models()
    if missing:
        raise FacesUnavailable(
            "Не хватает моделей: " + ", ".join(missing) +
            ". Нажмите «Скачать модели» на вкладке «Лица»."
        )

    _detector = cv2.FaceDetectorYN.create(
        str(DETECTOR_FILE), "", (320, 320), 0.7, 0.3, 5000)
    _recognizer = cv2.FaceRecognizerSF.create(str(RECOGNIZER_FILE), "")
    return _detector, _recognizer


def read_image(path: Path):
    """Читает изображение с поддержкой кириллицы в пути.

    cv2.imread не умеет открывать пути с не-ASCII символами на Windows,
    поэтому читаем файл сами и декодируем из памяти.
    """
    import cv2
    import numpy as np

    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _resize_for_detection(image):
    """Уменьшает изображение до MAX_SIDE по длинной стороне."""
    import cv2

    h, w = image.shape[:2]
    longest = max(h, w)
    if longest <= MAX_SIDE:
        return image
    scale = MAX_SIDE / longest
    return cv2.resize(image, (int(w * scale), int(h * scale)),
                      interpolation=cv2.INTER_AREA)


def detect_faces(path: Path) -> int:
    """Возвращает количество лиц на фотографии (0 — лиц нет)."""
    image = read_image(path)
    if image is None:
        return 0
    detector, _ = _get_models()
    image = _resize_for_detection(image)
    h, w = image.shape[:2]
    detector.setInputSize((w, h))
    _, faces = detector.detect(image)
    return 0 if faces is None else len(faces)


def face_embeddings(path: Path) -> list[np.ndarray]:
    """Возвращает векторы признаков всех лиц на фотографии."""
    image = read_image(path)
    if image is None:
        return []
    detector, recognizer = _get_models()
    image = _resize_for_detection(image)
    h, w = image.shape[:2]
    detector.setInputSize((w, h))
    _, faces = detector.detect(image)
    if faces is None:
        return []

    embeddings = []
    for face in faces:
        try:
            aligned = recognizer.alignCrop(image, face)
            embeddings.append(recognizer.feature(aligned).flatten().copy())
        except Exception:  # noqa: BLE001 — пропускаем лицо, которое не обработалось
            continue
    return embeddings


def similarity(a, b) -> float:
    """Косинусное сходство двух эмбеддингов: 1.0 — идентичны."""
    import numpy as np

    a = np.asarray(a, dtype="float32")
    b = np.asarray(b, dtype="float32")
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denominator == 0:
        return 0.0
    return float(np.dot(a, b) / denominator)


@dataclass
class Person:
    """Человек и эталонные векторы его лица."""

    name: str
    embeddings: list[list[float]] = field(default_factory=list)

    @property
    def sample_count(self) -> int:
        return len(self.embeddings)


class PeopleStore:
    """Хранилище известных людей (people.json)."""

    def __init__(self, path: Path = PEOPLE_PATH):
        self.path = path
        self.people: list[Person] = self._load()

    def _load(self) -> list[Person]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        return [Person(name=p.get("name", ""), embeddings=p.get("embeddings", []))
                for p in raw if p.get("name")]

    def save(self) -> None:
        data = [{"name": p.name, "embeddings": p.embeddings} for p in self.people]
        with contextlib.suppress(OSError):
            self.path.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def get(self, name: str) -> Person | None:
        return next((p for p in self.people if p.name.lower() == name.lower()), None)

    def add_samples(self, name: str, photos: list[Path]) -> int:
        """Добавляет эталонные фото человека. Возвращает число распознанных лиц.

        Если на эталонном фото несколько лиц, берётся первое — поэтому для
        обучения стоит выбирать снимки, где человек один.
        """
        person = self.get(name)
        if person is None:
            person = Person(name=name)
            self.people.append(person)

        added = 0
        for photo in photos:
            embeddings = face_embeddings(photo)
            if not embeddings:
                continue
            person.embeddings.append([float(x) for x in embeddings[0]])
            added += 1
        self.save()
        return added

    def remove(self, name: str) -> None:
        self.people = [p for p in self.people if p.name.lower() != name.lower()]
        self.save()

    def identify(self, embedding, threshold: float = SIMILARITY_THRESHOLD) -> tuple[str | None, float]:
        """Определяет, кому принадлежит лицо.

        Возвращает (имя, сходство). Имя = None, если совпадений нет.
        """
        best_name: str | None = None
        best_score = 0.0
        for person in self.people:
            for sample in person.embeddings:
                score = similarity(embedding, sample)
                if score > best_score:
                    best_score = score
                    best_name = person.name
        if best_score < threshold:
            return None, best_score
        return best_name, best_score


def identify_photo(path: Path, store: PeopleStore,
                   threshold: float = SIMILARITY_THRESHOLD) -> tuple[list[str], int]:
    """Кто изображён на фото.

    Возвращает (имена_найденных_людей, всего_лиц_на_фото).
    """
    embeddings = face_embeddings(path)
    names: list[str] = []
    for embedding in embeddings:
        name, _ = store.identify(embedding, threshold)
        if name and name not in names:
            names.append(name)
    return names, len(embeddings)
