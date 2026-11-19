"""Регресс: циклический импорт core.resilience (волна 36, KNOWN-01).

Локализация: eager-``__init__`` пакета ``core.resilience`` создавал цикл

    core.resilience.__init__ → core.resilience.rate_limiter
      → infrastructure.resilience.unified_rate_limiter → infrastructure.resilience.__init__
        → coordinator → ``from src.backend.core.resilience import DegradationManager``

Цикл разрывался только ПОРЯДКОМ блоков в ``__init__`` — хрупкая
договорённость. На Python 3.14 (per-module импорт-лок) прямой импорт
подмодуля (``from src.backend.core.resilience.retry import retry_async`` —
так делает clickhouse-аудит) приводил к
``_DeadlockError: deadlock detected by _ModuleLock(...)``. Ошибка глушилась
``emit_audit_safe`` → события аудита терялись, а пакет оставался удалённым
из ``sys.modules`` → следующий импорт падал с
``KeyError: 'src.backend.core.resilience'``.

Фикс: пакет переведён на ленивый re-export (PEP 562) — ``__init__`` не
импортирует подмодули на старте, поэтому ре-ентрантность невозможна.
"""

from __future__ import annotations

import importlib
import sys

import pytest


@pytest.mark.unit
class TestCoreResilienceLazyExports:
    """Публичный API пакета доступен, но подмодули не импортируются заранее."""

    def test_public_api_is_importable(self) -> None:
        """``from core.resilience import X`` работает для всех имён API."""
        from src.backend.core.resilience import (
            CircuitBreaker,
            RetryPolicy,
            degradation_manager,
            retry_async,
            with_retry,
        )

        assert RetryPolicy is not None
        assert with_retry is not None
        assert retry_async is not None
        assert CircuitBreaker is not None
        assert degradation_manager is not None

    def test_all_names_resolve(self) -> None:
        """Каждое имя из ``__all__`` реально резолвится."""
        import src.backend.core.resilience as pkg

        for name in pkg.__all__:
            assert getattr(pkg, name) is not None, name

    def test_unknown_attribute_raises(self) -> None:
        """Неизвестное имя → AttributeError (не тихая заглушка)."""
        import src.backend.core.resilience as pkg

        with pytest.raises(AttributeError):
            pkg.definitely_not_exported  # noqa: B018

    def test_dir_lists_public_api(self) -> None:
        """``dir()`` содержит публичные имена (автодополнение)."""
        import src.backend.core.resilience as pkg

        assert "CircuitBreaker" in dir(pkg)
        assert "retry_async" in dir(pkg)

    def test_bulkhead_not_in_core_api(self) -> None:
        """``Bulkhead`` не входит в API core (канон — infrastructure).

        Раньше имя было в ``__all__`` пакета, но не импортировалось →
        ``from src.backend.core.resilience import Bulkhead`` падал с
        ImportError. Core не импортирует infrastructure (правило слоёв).
        """
        import src.backend.core.resilience as pkg

        assert "Bulkhead" not in pkg.__all__
        assert "get_bulkhead" not in pkg.__all__


@pytest.mark.unit
class TestDirectSubmoduleImport:
    """Прямой импорт подмодуля не ломает пакет и не блокирует импорты."""

    def test_direct_submodule_import_leaves_package_importable(self) -> None:
        """``core.resilience.retry`` можно импортировать напрямую.

        До фикса такой импорт в контексте аудита приводил к
        ``_DeadlockError`` и последующему ``KeyError`` по родительскому
        пакету.
        """
        module = importlib.import_module("src.backend.core.resilience.retry")

        assert module.retry_async is not None
        assert "src.backend.core.resilience" in sys.modules

        # Повторный импорт пакета после прямого импорта подмодуля — ок.
        pkg = importlib.import_module("src.backend.core.resilience")
        assert pkg.RetryPolicy is not None

    def test_package_reimport_after_submodule_is_stable(self) -> None:
        """Повторный импорт пакета не приводит к KeyError по родителю."""
        importlib.import_module("src.backend.core.resilience.retry_budget")
        pkg = importlib.import_module("src.backend.core.resilience")

        assert pkg.get_retry_budget is not None
