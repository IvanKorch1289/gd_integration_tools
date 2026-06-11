"""Vault DSL mixin для RouteBuilder (S83 W3).

Добавляет chainable-метод ``vault_read()`` для чтения KV v2 secrets
из Vault в ``exchange.properties``. Обёртка над
:class:`dsl.engine.processors.vault_secret.VaultSecretProcessor`.

Контракт mixin: stateless, ``__slots__ = ()``, без instance-атрибутов.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.builder import RouteBuilder  # type: ignore[attr-defined]


class VaultSecretMixin:
    """Vault secret DSL для ``RouteBuilder``.

    Пример::

        rb = RouteBuilder.from_("secrets-loader")
        rb.vault_read(path="secret/data/db/password", output_field="db_password")
        rb.vault_read(path="secret/data/api/key", output_field="api_key", version=2)
    """

    __slots__ = ()

    def vault_read(
        self,
        path: str,
        *,
        output_field: str = "value",
        version: int = 0,
    ) -> RouteBuilder:
        """Прочитать Vault KV v2 secret и положить в ``exchange.properties``.

        Args:
            path: Полный путь к секрету (например, ``secret/data/db/password``).
            output_field: Имя поля для результата. Default ``"value"`` — dict
                с ключами ``{path, value, version}``. Кастомное имя →
                только строковое значение.
            version: Конкретная версия секрета (0 = current).

        Returns:
            ``RouteBuilder`` для chaining.
        """
        from src.backend.dsl.engine.processors.vault_secret import VaultSecretProcessor

        return self._add(  # type: ignore[attr-defined]
            VaultSecretProcessor(
                path=path,
                output_field=output_field,
                version=version,
            )
        )


__all__ = ("VaultSecretMixin",)
