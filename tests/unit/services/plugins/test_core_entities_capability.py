"""Smoke-тест для 4 in-tree core_entities плагинов (Sprint 8 Extensions 3).

Проверяет для ``extensions/core_entities/{orders,users,files,orderkinds}``:

1. ``extensions/core_entities/<entity>/plugin.py`` импортируется без
   побочных эффектов;
2. Класс плагина инстанцируется (``plugin_class()``);
3. Все capabilities, задекларированные в ``plugin.toml`` через секцию
   ``[[capabilities]]``, проходят ``CapabilityGate.declare`` — то есть
   имена зарегистрированы в default-vocabulary и для ``scope_required``
   capabilities указан явный scope.

Назначение: гарантировать, что ``PluginLoader._load_one`` (он вызывает
``gate.declare(manifest.name, manifest.capabilities)`` на старте — см.
``src/backend/services/plugins/loader/loading/loader_mixin.py:148``)
не получит ``CapabilityNotFoundError`` / ``ValueError`` для core entities.

NB: ``BasePlugin`` сам НЕ вызывает ``CapabilityGate.declare`` — это
by design (ADR-042 / ADR-044: манифест = декларативный inventory;
класс = lifecycle-wiring). Loader читает ``manifest.capabilities``
и декларирует их в gate ДО ``import_module(entry_class)``.
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Final

import pytest

from src.backend.core.interfaces.plugin import BasePlugin
from src.backend.core.plugin_runtime.manifest import load_plugin_manifest
from src.backend.core.security.capabilities import (
    CapabilityGate,
    build_default_vocabulary,
)

# Корень ``extensions/core_entities/`` относительно этого файла:
# tests/unit/services/plugins/test_core_entities_capability.py
#   → tests (4 уровня вверх до корня репо)
#   → extensions/core_entities/
_EXT_ROOT: Final[Path] = (
    Path(__file__).resolve().parents[4] / "extensions" / "core_entities"
)

# Карта сущностей: (entity, dotted_module_path, класс_плагина).
_CORE_ENTITIES: Final[tuple[tuple[str, str, str], ...]] = (
    ("orders", "extensions.core_entities.orders.plugin", "OrdersPlugin"),
    ("users", "extensions.core_entities.users.plugin", "UsersPlugin"),
    ("files", "extensions.core_entities.files.plugin", "FilesPlugin"),
    ("orderkinds", "extensions.core_entities.orderkinds.plugin", "OrderKindsPlugin"),
)

# Cycle-17 (D-AUDIT-1701): pre-cycle-17 orders дублировал ``db.read`` —
# фикс убрал второй scope='orderkinds' (silently dropped gate'ом).
# _XFAIL_GATE_DECLARE оставлен как ``frozenset()`` для совместимости
# signature теста; новые сущности с дубликатами должны попадать сюда.
_XFAIL_GATE_DECLARE: Final[frozenset[str]] = frozenset()


# ── Plugin class instantiable ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("entity", "module_path", "class_name"),
    _CORE_ENTITIES,
    ids=[e for e, _, _ in _CORE_ENTITIES],
)
@pytest.mark.unit
def test_plugin_class_instantiable(
    entity: str, module_path: str, class_name: str,
) -> None:
    """``import_module → plugin_class()`` отрабатывает без ошибок."""
    module = import_module(module_path)
    cls = getattr(module, class_name)
    assert isinstance(cls, type), f"{class_name} must be a class"
    assert issubclass(cls, BasePlugin), (
        f"{class_name} must subclass BasePlugin (ADR-042)"
    )
    instance = cls()
    assert isinstance(instance, BasePlugin)
    assert instance.name == f"core_entities_{entity}"
    assert instance.version == "1.0.0"


# ── Manifest capabilities are in vocabulary ───────────────────────────


@pytest.mark.parametrize(
    ("entity", "module_path", "class_name"),
    _CORE_ENTITIES,
    ids=[e for e, _, _ in _CORE_ENTITIES],
)
@pytest.mark.unit
def test_manifest_capabilities_in_vocabulary(
    entity: str, module_path: str, class_name: str,
) -> None:
    """Каждое имя capability из manifest зарегистрировано в default vocabulary."""
    manifest = load_plugin_manifest(_EXT_ROOT / entity / "plugin.toml")
    vocab = build_default_vocabulary()
    declared_names: set[str] = set()
    for cap in manifest.capabilities:
        # Дубликаты имён в манифесте — отдельный concern (orders: db.read ×2);
        # здесь интересует только membership в vocabulary.
        if cap.name in declared_names:
            continue
        assert vocab.has(cap.name), (
            f"Plugin {manifest.name!r} declares capability "
            f"{cap.name!r} which is not in the default vocabulary"
        )
        declared_names.add(cap.name)


# ── gate.declare(manifest.name, manifest.capabilities) succeeds ────────


@pytest.mark.parametrize(
    ("entity", "module_path", "class_name"),
    _CORE_ENTITIES,
    ids=[e for e, _, _ in _CORE_ENTITIES],
)
@pytest.mark.unit
def test_plugin_capabilities_pass_gate_declare(
    entity: str, module_path: str, class_name: str,
) -> None:
    """``CapabilityGate.declare(manifest.name, manifest.capabilities)`` — ok.

    Воспроизводит логику ``PluginLoader._load_one`` (``loader_mixin.py:148``):
    свежий gate + declare на пустой bucket. Если хотя бы одно имя не в
    vocabulary или нарушен ``scope_required`` — упадёт ``ValueError``.
    """
    if entity in _XFAIL_GATE_DECLARE:
        pytest.xfail(
            reason=(
                f"{entity}: pre-existing known-issue — plugin.toml declares "
                "db.read twice (scope='orders' and scope='orderkinds'); "
                "CapabilityGate.declare rejects duplicate names per plugin "
                "(declaration_mixin.py:62-66). Second capability is silently "
                "dropped. Out of explicit sub-task scope (plugin.py only); "
                "fix the manifest in a follow-up sub-task."
            ),
        )
    manifest = load_plugin_manifest(_EXT_ROOT / entity / "plugin.toml")
    gate = CapabilityGate()
    gate.declare(manifest.name, manifest.capabilities)
    bucket = gate._declarations[manifest.name]  # type: ignore[attr-defined]
    # Уникальных имён == длине bucket (т.к. gate.declare требует
    # уникальности по name — см. test_gate.test_double_declare_rejected).
    unique_names = {c.name for c in manifest.capabilities}
    assert len(bucket) == len(unique_names), (
        f"Plugin {manifest.name!r}: bucket has {len(bucket)} entries, "
        f"expected {len(unique_names)} unique capability names"
    )
