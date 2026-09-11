"""Canonical Module Map + Import-Linter Rules (Wave 1 P0 #61).

Проблема (EP-R1):
    Разработчики не знают, куда положить новый код:
    - Идемпотентность — в core/idempotency или в infrastructure?
    - Outbox verification — в core/ или infrastructure/messaging?
    - Routes — в routes/<name>/ или dsl/routes/?

    Без canonical map:
    - Код расползается по дублирующим путям.
    - Импорты пересекают слои.
    - Cognitive load растёт.

Решение:
    ``CanonicalMap`` + ``ImportRule`` + ``LayerRule``:

    1. ``CanonicalMap`` — registry: ``path → responsibility → public_api``.
    2. ``ImportRule`` — запрещённый import pattern:
       - ``extensions/*`` → НЕ импортирует ``infrastructure/*`` напрямую.
       - ``core/*`` → НЕ импортирует ``extensions/*`` или ``services/*``.
       - и т.п.
    3. ``LayerRule`` — описание архитектурного слоя с allowed/forbidden imports.

Использование::

    from src.backend.core.canonical_map import (
        CanonicalMap, ImportRule, LayerRule,
        get_canonical_map,
    )

    cmap = get_canonical_map()
    cmap.register_path(
        path="src/backend/core/idempotency",
        responsibility="Idempotency Service для retry-safe writes",
        public_api=["IdempotencyService", "InMemoryIdempotencyBackend"],
    )

    rule = ImportRule(
        pattern="extensions.*",
        forbidden_imports=["src.backend.infrastructure.*"],
    )
    cmap.add_rule(rule)

    violations = cmap.check_imports()
"""

from __future__ import annotations

from src.backend.core.canonical_map.map import (
    CanonicalMap,
    ImportRule,
    LayerRule,
    PathEntry,
    get_canonical_map,
)

__all__ = (
    "CanonicalMap",
    "ImportRule",
    "LayerRule",
    "PathEntry",
    "get_canonical_map",
)
