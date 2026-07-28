"""Распознавание сюжета фотографии (коты, природа, документы, счётчики…).

Работает на модели CLIP: она умеет сопоставлять изображение с текстовым
описанием, поэтому категории задаются обычными фразами и меняются без
переобучения. Достаточно дописать строку в список — и появится новая папка.

Всё считается локально через onnxruntime. Интернет нужен один раз, чтобы
скачать модель (~150 МБ).

Категории описываются по-английски: CLIP обучалась на английских подписях
и понимает их точнее. Пользователю показываются русские названия — они же
становятся именами папок.
"""
from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import BASE_DIR

MODELS_DIR = BASE_DIR / "models"
VISION_FILE = MODELS_DIR / "clip_vision.onnx"
TEXT_FILE = MODELS_DIR / "clip_text.onnx"
TOKENIZER_FILE = MODELS_DIR / "clip_tokenizer.json"
CATEGORIES_PATH = BASE_DIR / "categories.json"

_BASE_URL = "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/"
MODEL_URLS = {
    VISION_FILE.name: _BASE_URL + "onnx/vision_model_quantized.onnx",
    TEXT_FILE.name: _BASE_URL + "onnx/text_model_quantized.onnx",
    TOKENIZER_FILE.name: _BASE_URL + "tokenizer.json",
}

# Параметры предобработки, заданные авторами CLIP
IMAGE_SIZE = 224
_MEAN = (0.48145466, 0.4578275, 0.40821073)
_STD = (0.26862954, 0.26130258, 0.27577711)
_CONTEXT_LENGTH = 77
_LOGIT_SCALE = 100.0

# Ниже этого порога уверенности снимок считается неопознанным
DEFAULT_THRESHOLD = 0.35
UNSURE_FOLDER = "Разное"

# Категории по умолчанию: русское имя папки -> английские описания.
# Несколько формулировок на категорию заметно повышают точность.
DEFAULT_CATEGORIES: dict[str, list[str]] = {
    "Люди": ["a photo of people", "a portrait of a person", "a group of people"],
    "Коты": ["a photo of a cat", "a kitten"],
    "Собаки": ["a photo of a dog", "a puppy"],
    "Животные": ["a photo of an animal", "a bird", "a wild animal"],
    "Природа": ["a landscape photo of nature", "a photo of mountains or forest",
                "a photo of the sea or a lake"],
    "Цветы": ["a photo of flowers", "a blooming plant"],
    "Документы": ["a scanned document", "a photo of a paper document with text",
                  "a receipt or invoice"],
    "Счётчики": ["a photo of a utility meter", "a water or electricity meter display",
                 "a gas meter with digits"],
    "Скриншоты": ["a screenshot of a computer screen", "a screenshot of a website",
                  "a screenshot of a mobile app"],
    "Еда": ["a photo of food on a plate", "a photo of a meal in a restaurant"],
    "Транспорт": ["a photo of a car", "a photo of a vehicle or motorcycle"],
    "Здания": ["a photo of a building", "a photo of architecture or a city street"],
    "Чеки": ["a photo of a paper receipt", "a shopping receipt with prices"],
    "Схемы": ["a diagram or chart", "a graph or infographic"],
}

_session_cache: dict[str, object] = {}


class VisionUnavailable(Exception):
    """Не установлен onnxruntime или не скачаны модели CLIP."""


@dataclass
class SceneResult:
    """Результат распознавания сюжета."""

    category: str          # название категории или UNSURE_FOLDER
    confidence: float      # 0.0–1.0
    runner_up: str = ""    # второй по вероятности вариант

    @property
    def is_confident(self) -> bool:
        return self.category != UNSURE_FOLDER


# ---------- Модели ----------

def models_ready() -> bool:
    """True, если модели скачаны и onnxruntime доступен."""
    if not all(f.exists() for f in (VISION_FILE, TEXT_FILE, TOKENIZER_FILE)):
        return False
    try:
        import onnxruntime  # noqa: F401
        import tokenizers  # noqa: F401
    except ImportError:
        return False
    return True


def missing_models() -> list[str]:
    return [f.name for f in (VISION_FILE, TEXT_FILE, TOKENIZER_FILE) if not f.exists()]


def download_models(progress: Callable[[str, int, int], None] | None = None) -> None:
    """Скачивает модели CLIP. Вызывается только по действию пользователя."""
    import urllib.request

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    for name in missing_models():
        target = MODELS_DIR / name

        def hook(block, block_size, total, _name=name):
            if progress:
                progress(_name, min(block * block_size, total), total)

        temporary = target.with_suffix(".part")
        urllib.request.urlretrieve(MODEL_URLS[name], temporary, reporthook=hook)
        temporary.replace(target)


def _load():
    """Ленивая загрузка моделей и токенизатора (один раз за сессию)."""
    if _session_cache:
        return _session_cache["vision"], _session_cache["text"], _session_cache["tokenizer"]

    try:
        import onnxruntime as ort
        from tokenizers import Tokenizer
    except ImportError as exc:
        raise VisionUnavailable(
            "Не установлены onnxruntime и tokenizers. "
            "Выполните: pip install onnxruntime tokenizers"
        ) from exc

    missing = missing_models()
    if missing:
        raise VisionUnavailable(
            "Не хватает моделей: " + ", ".join(missing) +
            ". Нажмите «Скачать модели» на вкладке «Сюжеты»."
        )

    options = ort.SessionOptions()
    options.log_severity_level = 3  # не засорять вывод предупреждениями
    _session_cache["vision"] = ort.InferenceSession(
        str(VISION_FILE), options, providers=["CPUExecutionProvider"])
    _session_cache["text"] = ort.InferenceSession(
        str(TEXT_FILE), options, providers=["CPUExecutionProvider"])
    _session_cache["tokenizer"] = Tokenizer.from_file(str(TOKENIZER_FILE))
    return _session_cache["vision"], _session_cache["text"], _session_cache["tokenizer"]


# ---------- Категории ----------

def load_categories() -> dict[str, list[str]]:
    """Читает пользовательские категории; при отсутствии — набор по умолчанию."""
    if not CATEGORIES_PATH.exists():
        return {name: list(prompts) for name, prompts in DEFAULT_CATEGORIES.items()}
    try:
        data = json.loads(CATEGORIES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {name: list(prompts) for name, prompts in DEFAULT_CATEGORIES.items()}
    return {str(k): list(v) for k, v in data.items() if v}


def save_categories(categories: dict[str, list[str]]) -> None:
    with contextlib.suppress(OSError):
        CATEGORIES_PATH.write_text(
            json.dumps(categories, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- Вычисления ----------

def _preprocess(path: Path):
    """Готовит изображение так, как ожидает CLIP: 224×224 по центру."""
    import numpy as np
    from PIL import Image

    with Image.open(path) as raw:
        image = raw.convert("RGB")
        width, height = image.size
        scale = IMAGE_SIZE / min(width, height)
        image = image.resize((round(width * scale), round(height * scale)), Image.BICUBIC)
        width, height = image.size
        left = (width - IMAGE_SIZE) // 2
        top = (height - IMAGE_SIZE) // 2
        image = image.crop((left, top, left + IMAGE_SIZE, top + IMAGE_SIZE))
        array = np.asarray(image, dtype=np.float32) / 255.0

    array = (array - np.array(_MEAN, dtype=np.float32)) / np.array(_STD, dtype=np.float32)
    return array.transpose(2, 0, 1)[None]


def _normalize(vectors):
    import numpy as np

    return vectors / np.linalg.norm(vectors, axis=-1, keepdims=True)


class SceneClassifier:
    """Классификатор сюжета: текстовые описания считаются один раз."""

    def __init__(self, categories: dict[str, list[str]] | None = None,
                 threshold: float = DEFAULT_THRESHOLD):
        self.categories = categories or load_categories()
        self.threshold = threshold
        self._names: list[str] = []
        self._owner = None          # к какой категории относится каждое описание
        self._text_embeddings = None

    def prepare(self) -> None:
        """Считает эмбеддинги описаний. Вызывается автоматически при первом разборе."""
        import numpy as np

        _, text_session, tokenizer = _load()
        self._names = list(self.categories)
        prompts: list[str] = []
        owner: list[int] = []
        for i, name in enumerate(self._names):
            for prompt in self.categories[name]:
                prompts.append(prompt)
                owner.append(i)

        ids = np.zeros((len(prompts), _CONTEXT_LENGTH), dtype=np.int64)
        for i, prompt in enumerate(prompts):
            sequence = tokenizer.encode(prompt).ids[:_CONTEXT_LENGTH]
            ids[i, :len(sequence)] = sequence

        embeddings = text_session.run(None, {"input_ids": ids})[0]
        self._text_embeddings = _normalize(embeddings)
        self._owner = np.array(owner)

    def classify(self, path: Path) -> SceneResult | None:
        """Определяет сюжет снимка. None — если файл не читается."""
        import numpy as np

        if self._text_embeddings is None:
            self.prepare()

        vision_session, _, _ = _load()
        try:
            pixels = _preprocess(path)
        except Exception:  # noqa: BLE001 — битый файл не должен ронять разбор
            return None

        image_embedding = _normalize(vision_session.run(None, {"pixel_values": pixels})[0])
        similarity = (self._text_embeddings @ image_embedding.T).flatten() * _LOGIT_SCALE

        # Для каждой категории берём её самое удачное описание
        scores = np.array([similarity[self._owner == i].max()
                           for i in range(len(self._names))])
        exponent = np.exp(scores - scores.max())
        probabilities = exponent / exponent.sum()

        order = probabilities.argsort()[::-1]
        best, second = order[0], order[1] if len(order) > 1 else order[0]
        confidence = float(probabilities[best])

        if confidence < self.threshold:
            return SceneResult(category=UNSURE_FOLDER, confidence=confidence,
                               runner_up=self._names[best])
        return SceneResult(category=self._names[best], confidence=confidence,
                           runner_up=self._names[second])
