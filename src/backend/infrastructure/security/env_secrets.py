"""``EnvSecretsBackend`` — fallback на основе ``os.environ``.

Wave 21.3c. Используется в dev_light, где Vault недоступен. ``set_secret`` /
``delete_secret`` модифицируют только in-process state (``os.environ``) —
для durability отдельно поддерживается опциональный JSON-файл.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from src.backend.core.interfaces.secrets import SecretsBackend

__all__ = ("EnvSecretsBackend",)


class EnvSecretsBackend(SecretsBackend):
    """Read-write fallback на ``os.environ`` с опциональной JSON-персистентностью.

    ``persistence_path`` — путь к JSON-файлу с дополнительными секретами,
    который накладывается поверх ``os.environ`` при чтении и обновляется
    при ``set_secret``/``delete_secret``. Отсутствие файла трактуется как
    «секретов нет, файл будет создан при первой записи».
    """

    def __init__(self, persistence_path: str | Path | None = None) -> None:
        self._path = Path(persistence_path) if persistence_path else None
        self._cache: dict[str, str] = {}
        if self._path is not None and self._path.is_file():
            try:
                self._cache = json.loads(self._path.read_text(encoding="utf-8"))
            except json.JSONDecodeError, OSError:
                # Повреждённый файл — стартуем с пустого кеша, не падаем.
                self._cache = {}

    async def get_secret(self, key: str) -> str | None:
        if key in self._cache:
            return self._cache[key]
        return os.environ.get(key)

    async def set_secret(self, key: str, value: str) -> None:
        self._cache[key] = value
        os.environ[key] = value
        self._flush()

    async def delete_secret(self, key: str) -> bool:
        existed = key in self._cache or key in os.environ
        self._cache.pop(key, None)
        os.environ.pop(key, None)
        self._flush()
        return existed

    async def list_keys(self, prefix: str | None = None) -> list[str]:
        keys = set(self._cache) | set(os.environ)
        if prefix is not None:
            keys = {k for k in keys if k.startswith(prefix)}
        return sorted(keys)

    def _flush(self) -> None:
        """Сохраняет cache в JSON, если задан ``persistence_path``."""
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._cache, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            # Запись на диск best-effort: in-memory state остаётся валидным.
            pass
