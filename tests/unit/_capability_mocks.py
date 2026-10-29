"""Shared test helpers для capability-гейта DSL-БД-шагов (ADR-0393).

С 2026-10-29 (волна 18) DSL-процессоры доступа к БД объявляют
``required_capability`` (``db.read`` / ``db.write``) и вызывают
``auth_check``. Это меняет контракт юнит-тестов: прямой вызов
``processor.process(exchange, ctx)`` без namespace'а роута получал бы
fail-closed отказ (ADR-0366: нет декларации capability → DENY).

Тесты, которые проверяют **поведение БД** (SQL, tenant-скоуп, лимиты,
коммиты), не должны дублировать проверку capability — она проверяется
отдельными тестами (см. ``tests/unit/dsl/engine/capability/``). Поэтому
здесь — единая точка для «разрешить capability-гейт», по образцу
:mod:`tests.unit._auth_mocks` (``patched_auth_allow``).

Использование (autouse-фикстура в conftest каталога)::

    @pytest.fixture(autouse=True)
    def _allow_db_capability():
        with patched_db_capability_allow():
            yield
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

__all__ = ("patched_db_capability_allow",)


@contextmanager
def patched_db_capability_allow() -> Iterator[None]:
    """Разрешить capability-гейт для DSL-шагов БД в тестах (ADR-0393).

    Подменяет :meth:`BaseProcessor.auth_check` на «всегда разрешено» и
    проставляет tenant в exchange — иначе runtime-резолвер отклоняет
    запрос как ``tenant_missing``.

    Yields:
        ``None`` — внутри ``with`` блока capability-гейт разрешает всё.

    Example::

        with patched_db_capability_allow():
            await processor.process(exchange, ctx)

    """
    from src.backend.dsl.engine.processors.base import BaseProcessor

    async def _allow(
        self: object,
        exchange: object,
        *,
        action: str = "execute",
        principal: str | None = None,
    ) -> bool:
        meta = getattr(exchange, "meta", None)
        if meta is not None and not getattr(meta, "tenant_id", None):
            meta.tenant_id = "test-tenant"
        return True

    with patch.object(BaseProcessor, "auth_check", _allow):
        yield
