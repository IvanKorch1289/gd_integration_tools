"""ADR-0404 — банк xfail для тестов, ограниченных ОКРУЖЕНИЕМ.

Зачем банк, а не skip
---------------------
``pytest.skip`` прячет тест: в отчёте он выглядит как «проверен и
пропущен», сигнал о проблеме теряется, а регрессия (тест начал падать
по новой причине) остаётся незамеченной. ``xfail`` наоборот:

* тест выполняется, его падение видно в отчёте как XFAIL;
* ``strict=True`` — если тест unexpectedly прошёл, CI падает и запись
  обязана быть удалена из банка;
* причина и owner-задача зафиксированы явно, а не «где-то в консоли».

Правило роста банка
-------------------
1. Банк может только УМЕНЬШАТЬСЯ. Новая запись — только вместе с
   ревизией ADR-0404 (owner + причина + ссылка на задачу).
2. Запись добавляется ТОЛЬКО если причина объективно внешняя:
   отсутствующая optional-зависимость, нужен живой внешний сервис
   (Temporal-кластер), недетерминированный по природе benchmark.
3. Порядок-зависимые (order-dependent) падения банком НЕ покрываются —
   они чинятся фикстурой/восстановлением состояния (см. ADR-0404).
4. Гейт ``tests/unit/test_order_dependent_pollution_gate.py`` проверяет,
   что каждая запись банка соответствует реально существующему тесту и
   что размер банка не превышает ``MAX_BANK_ENTRIES``.

Формат записи
--------------
``"<node-id>": (reason, owner, strict)``

``strict=True`` — только для детерминированных ограничений (где падение
воспроизводится всегда). Для недетерминированных (perf-бенчмарк)
используется ``strict=False``: XPASS там — не регрессия, а шум CI.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pytest

__all__ = (
    "MAX_BANK_ENTRIES",
    "XFAIL_ENVIRONMENT",
    "apply_xfail_environment_bank",
)

#: Максимально допустимое число записей в банке (только уменьшаемо).
MAX_BANK_ENTRIES = 8

#: Банк: node-id теста → (причина ограничения окружения, owner-задача, strict).
XFAIL_ENVIRONMENT: dict[str, tuple[str, str, bool]] = {
    # ── Недетерминированный по природе benchmark ────────────────────────────
    "tests/unit/dsl/engine/test_exchange_snapshot.py::"
    "TestRealWorldBenchmarks::test_msgspec_speedup_large_payload": (
        "performance-бенчмарк: результат зависит от загрузки CPU на "
        "shared-runner (msgspec 407ms vs orjson 336ms на 1MB payload) — "
        "недетерминирован по природе, в изоляции проходит",
        "OWNER-TASK: PROD-READINESS gaps — perf-бенчмарки в отдельный "
        "профиль CI (docs/roadmap/PROD_READINESS_GAPS.md)",
        False,
    ),
}


def _node_ids(items: Iterable[Any]) -> dict[str, Any]:
    """Сопоставление node-id → item (для точного попадания по id)."""
    return {item.nodeid: item for item in items}


def apply_xfail_environment_bank(items: list[pytest.Item]) -> None:
    """Помечает тесты из банка как ``xfail``.

    Args:
        items: Собранные pytest-тесты (из ``pytest_collection_modifyitems``).

    """
    by_id = _node_ids(items)
    for node_id, (reason, owner, strict) in XFAIL_ENVIRONMENT.items():
        item = by_id.get(node_id)
        if item is None:
            continue
        item.add_marker(
            pytest.mark.xfail(
                reason=f"{reason} | {owner}",
                strict=strict,
            ),
        )
