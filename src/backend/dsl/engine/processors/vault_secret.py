"""S83 W3 — VaultSecretProcessor: read Vault KV v2 secret into exchange.

DSL step ``vault_read``: при успехе кладёт ``SecretValue`` (или конкретный
``output_field`` со строкой) в ``exchange.properties``, при ошибке —
``exchange.fail()``. Помогает избежать дублирования
``async def _load_secret()`` в каждом route при работе с Vault.

Пример YAML DSL::

    steps:
      - vault_read:
          path: secret/data/db/password
          output_field: db_password
        output: { db_password: str }

Пример Python DSL::

    .vault_read(path="secret/data/db/password", output_field="db_password")
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_logger = get_logger("dsl.vault")


@dataclass
class VaultReadResult:
    """Результат чтения Vault secret (value + version).

    Plain dataclass (без slots=True) — используется как DTO,
    Pydantic-модели не нужны, наследование не предполагается.
    """

    path: str
    value: str
    version: int


class VaultSecretProcessor(BaseProcessor):
    """Читает KV v2 secret из Vault и кладёт в ``exchange.properties``.

    Args:
        path: Полный путь к секрету (например, ``secret/data/db/password``).
        output_field: Имя поля в ``exchange.properties`` для сохранения
            результата (``"value"`` по умолчанию — полный ``SecretValue``
            dict c ``path``/``value``/``version``).
        version: Конкретная версия секрета (0 = current).
        name: Опциональное имя процессора для трассировки.

    Body contract: не используется (input — это ``path``).
    Output: ``exchange.properties[output_field] = str | VaultReadResult``.
    """

    side_effect: ClassVar[Any] = "READ"
    compensatable: ClassVar[bool] = True

    def __init__(
        self,
        *,
        path: str,
        output_field: str = "value",
        version: int = 0,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"vault_read({path})")
        self._path = path
        self._output_field = output_field
        self._version = version

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Читает Vault secret асинхронно, пишет в exchange.properties."""
        try:
            from src.backend.infrastructure.secrets.vault_backend import VaultBackend
            from src.backend.infrastructure.secrets.vault_client import VaultConfig
        except ImportError as exc:
            exchange.fail(
                f"vault dependencies not installed: {exc}. Install [secrets] extra."
            )
            return

        try:
            backend = VaultBackend(config=VaultConfig.from_env())
            if self._version > 0:
                secret = await backend.get_versioned(self._path, self._version)
            else:
                # Синхронный get → оборачиваем в to_thread
                import asyncio

                secret = await asyncio.to_thread(backend.get, self._path)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "vault_read failed", extra={"path": self._path, "error": str(exc)}
            )
            exchange.fail(f"Vault read failed for {self._path!r}: {exc}")
            return

        # Помещаем результат: dict с path/value/version для гибкости downstream
        if self._output_field == "value":
            exchange.properties[self._output_field] = {
                "path": secret.name,
                "value": secret.value,
                "version": secret.version,
            }
        else:
            # Кастомное поле → только value-строка
            exchange.properties[self._output_field] = secret.value

        _logger.debug(
            "vault_read ok",
            extra={
                "path": self._path,
                "version": secret.version,
                "output_field": self._output_field,
            },
        )

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализация в DSL: ``{vault_read: {path, output_field, version}}``."""
        spec: dict[str, Any] = {"path": self._path}
        if self._output_field != "value":
            spec["output_field"] = self._output_field
        if self._version > 0:
            spec["version"] = self._version
        return {"vault_read": spec}
