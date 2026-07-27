"""Клиент для локальной модели Ollama (общение по HTTP).

Ничего не отправляет в интернет — работает только с локальным сервером Ollama
(по умолчанию http://localhost:11434). Использует режим format=json, чтобы
модель гарантированно возвращала корректный JSON.
"""
from __future__ import annotations

import json

import requests


class OllamaError(Exception):
    """Проблема связи с Ollama (сервер не запущен, нет модели и т. п.)."""


class OllamaClient:
    def __init__(self, host: str, model: str, timeout: int = 120):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout

    def check_connection(self) -> tuple[bool, str]:
        """Проверяет доступность сервера и наличие нужной модели.

        Возвращает (успех, человекочитаемое сообщение).
        """
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=5)
            resp.raise_for_status()
        except requests.exceptions.ConnectionError:
            return False, (
                "Ollama не запущен. Запусти сервер командой `ollama serve` "
                "или открой приложение Ollama."
            )
        except requests.exceptions.RequestException as exc:
            return False, f"Ошибка обращения к Ollama: {exc}"

        models = [m.get("name", "") for m in resp.json().get("models", [])]
        # Имя модели может быть с тегом (qwen2.5:3b) — сравниваем по префиксу
        installed = any(
            name == self.model or name.startswith(self.model.split(":")[0])
            for name in models
        )
        if not installed:
            return False, (
                f"Модель '{self.model}' не установлена. "
                f"Скачай её командой:  ollama pull {self.model}"
            )
        return True, f"Ollama на связи, модель '{self.model}' готова."

    def generate_json(self, prompt: str, system: str = "") -> dict:
        """Запрашивает у модели ответ в формате JSON и парсит его в dict."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "format": "json",
            "stream": False,
            # Низкая температура — стабильная классификация без фантазий
            "options": {"temperature": 0.1},
        }
        try:
            resp = requests.post(
                f"{self.host}/api/generate",
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.exceptions.ConnectionError as exc:
            raise OllamaError("Ollama не запущен или недоступен.") from exc
        except requests.exceptions.RequestException as exc:
            raise OllamaError(f"Ошибка запроса к модели: {exc}") from exc

        raw = resp.json().get("response", "").strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OllamaError(
                f"Модель вернула не-JSON ответ: {raw[:200]}"
            ) from exc
