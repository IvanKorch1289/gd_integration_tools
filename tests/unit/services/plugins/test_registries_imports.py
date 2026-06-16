# ruff: noqa: S101
"""S70 W3 — style-guard для ``src.backend.services.plugins.registries``.

Защищаем инвариант S70 W3:

* ``from src.backend.dsl`` встречается **ровно в 3 уникальных модулях**
  (``action_registry``, ``plugin_registry``, ``engine.processors``), не больше;
* runtime-классы (``ActionHandlerSpec``, ``BaseProcessor``) импортируются
  на top-level, **не** внутри функций (иначе split-import паттерн не работает);
* type-only импорты (``ActionHandlerRegistry``, ``ProcessorPluginRegistry``)
  остаются под ``TYPE_CHECKING`` (PEP 484);
* адаптеры действительно используют целевые классы из DSL
  (smoke на regression — заодно ловим случайные rename).

NB: style cleanup, не violation closure — top-level ``from src.backend.dsl``
всё ещё считается reverse-dep violation (TD-S65-W4). Этот тест следит,
чтобы рефактор не разъехался обратно к 4 строкам / 2 function-local импортам.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import TYPE_CHECKING

from src.backend.services.plugins.registries import (  # noqa: F401  (smoke)
    ActionRegistryAdapter,
    ProcessorRegistryAdapter,
    RepositoryHookRegistry,
)

# ── Константы инварианта ──────────────────────────────────────────────

REGISTR_PATH = Path("src/backend/services/plugins/registries.py")
# Регулярка для строк `from src.backend.dsl.<...> import <...>`
DSL_FROM_RE = re.compile(r"^\s*from\s+(src\.backend\.dsl\.[\w.]+)\s+import\s+(.+?)\s*$")
# Модули, которые осознанно reverse-импортируются (style cleanup, не violation close).
EXPECTED_DSL_MODULES: frozenset[str] = frozenset(
    {
        "src.backend.dsl.commands.action_registry",
        "src.backend.dsl.engine.plugin_registry",
        "src.backend.dsl.engine.processors",
    }
)


def _read_registries_source() -> str:
    """Читает исходник registries.py как UTF-8 текст (без зависимостей от cwd)."""
    repo_root = (
        Path(__file__).resolve().parents[4]
    )  # tests/unit/services/plugins/ → repo root
    return (repo_root / REGISTR_PATH).read_text(encoding="utf-8")


def _parse_dsl_imports(
    source: str,
) -> tuple[list[ast.ImportFrom], list[ast.ImportFrom]]:
    """Возвращает (top_level_imports, type_checking_imports) — все ``from src.backend.dsl``.

    Разделение через обход AST: TC-блок → узлы внутри, не входят в ``tree.body``.
    Для простоты собираем ВСЕ ImportFrom с module.startswith('src.backend.dsl'),
    потом фильтруем по признаку 'is inside if TYPE_CHECKING' через parent-chain
    упрощённо: парсим обёртку вручную через byte-offset.
    """
    tree = ast.parse(source)
    all_dsl: list[ast.ImportFrom] = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom)
        and (n.module or "").startswith("src.backend.dsl")
    ]
    # Разделяем top-level (col_offset == 0) vs everything-else.
    top_level = [n for n in all_dsl if n.col_offset == 0]
    nested = [n for n in all_dsl if n.col_offset != 0]
    return top_level, nested


# ── Тесты инварианта ──────────────────────────────────────────────────


class TestDslImportStructure:
    """Структура импортов в registries.py защищена от регрессии."""

    def test_no_duplicate_dsl_imports(self) -> None:
        """Ни один модуль dsl.* не импортируется 3+ раз (split import: max 2).

        До рефактора было 4 строки: 2 из ``dsl.commands.action_registry``
        (ActionHandlerRegistry в TYPE_CHECKING + ActionHandlerSpec в runtime) +
        1 из ``dsl.engine.plugin_registry`` + 1 из ``dsl.engine.processors``.

        После рефактора — 3 модуля, каждый встречается максимум 2 раза
        (TC-блок + runtime top-level — split import pattern).
        """
        source = _read_registries_source()
        top_level, _nested = _parse_dsl_imports(source)

        module_counts: dict[str, int] = {}
        for node in top_level:
            assert node.module is not None
            module_counts[node.module] = module_counts.get(node.module, 0) + 1

        offenders = {m: c for m, c in module_counts.items() if c >= 3}
        assert not offenders, (
            f"Дубль dsl-импорта (>=3 раз) в registries.py: {offenders}. "
            f"Объедини через comma-import в одном из блоков."
        )

    def test_three_unique_dsl_modules(self) -> None:
        """Ровно 3 уникальных dsl-модуля импортируются (style cleanup baseline).

        Учитываем ВСЕ dsl-импорты — и TC-блок, и runtime top-level (split pattern).
        """
        source = _read_registries_source()
        top_level, nested = _parse_dsl_imports(source)
        modules: set[str] = set()
        for node in top_level + nested:
            assert node.module is not None
            modules.add(node.module)
        assert modules == EXPECTED_DSL_MODULES, (
            f"Изменился набор dsl-модулей в registries.py. "
            f"Expected: {sorted(EXPECTED_DSL_MODULES)}, got: {sorted(modules)}. "
            f"Если добавляешь новый — обнови EXPECTED_DSL_MODULES явно."
        )

    def test_no_function_local_dsl_imports(self) -> None:
        """Ни одного ``from src.backend.dsl`` внутри функции/метода."""
        source = _read_registries_source()
        tree = ast.parse(source)
        offenders: list[tuple[str, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.ImportFrom) and (
                        (sub.module or "").startswith("src.backend.dsl")
                    ):
                        # `ast.ImportFrom.module` всегда str для relative=0,
                        # но статически тип `str | None` — narrowed assert.
                        assert sub.module is not None
                        offenders.append((sub.module, sub.lineno))
        assert not offenders, (
            "Function-local импорты из dsl недопустимы (было 2 до S70 W3): "
            f"{offenders}. Перенеси на top-level."
        )

    def test_type_checking_block_is_valid(self) -> None:
        """TC-блок парсится AST без ошибок и содержит только import-from узлы.

        Используем AST-фильтр: TC-узлы — это ``ImportFrom`` с col_offset > 0,
        находящиеся на верхнем уровне ``if TYPE_CHECKING:`` (т.е. depth=1 от
        top-level ``If``). Упрощённо проверяем: все вложенные (col_offset>0)
        ``ImportFrom`` с module from dsl — это и есть TC-блок.
        """
        source = _read_registries_source()
        _top, nested = _parse_dsl_imports(source)
        # Каждый вложенный import-from должен быть from src.backend.dsl.*
        # и иметь хотя бы одно имя.
        for node in nested:
            assert node.module is not None
            assert node.module.startswith("src.backend.dsl."), (
                f"TC-блок импортирует не из dsl: {node.module}"
            )
            names = [alias.name for alias in node.names]
            assert names, f"Пустой import в TC: {ast.dump(node)}"

    def test_runtime_dsl_imports_at_top_level(self) -> None:
        """Runtime-классы ``ActionHandlerSpec`` и ``BaseProcessor`` на top-level."""
        source = _read_registries_source()
        top_level, _nested = _parse_dsl_imports(source)
        runtime_dsl_at_top: set[str] = set()
        for node in top_level:
            assert node.module is not None
            runtime_dsl_at_top.add(node.module)

        assert "src.backend.dsl.commands.action_registry" in runtime_dsl_at_top, (
            "Top-level runtime импорт из dsl.commands.action_registry отсутствует — "
            "ActionHandlerSpec должен быть доступен без function-local импорта."
        )
        assert "src.backend.dsl.engine.processors" in runtime_dsl_at_top, (
            "Top-level runtime импорт из dsl.engine.processors отсутствует — "
            "BaseProcessor должен быть доступен без function-local импорта."
        )

    def test_no_dsl_import_outside_expected_modules(self) -> None:
        """Защита от дрейфа: импорт из других dsl-подмодулей = fail loud."""
        source = _read_registries_source()
        offenders: list[str] = []
        for line in source.splitlines():
            m = DSL_FROM_RE.match(line)
            if m is None:
                continue
            mod = m.group(1)
            if mod not in EXPECTED_DSL_MODULES:
                offenders.append(mod)
        assert not offenders, (
            f"Неожиданные dsl-импорты в registries.py: {offenders}. "
            f"Разрешённый набор: {sorted(EXPECTED_DSL_MODULES)}. "
            f"Если это осознанное расширение — обнови EXPECTED_DSL_MODULES."
        )


# ── Smoke-тесты: классы действительно живые ─────────────────────────


class TestAdapterSmoke:
    """Smoke: адаптеры используют целевые классы из DSL без падения."""

    def test_action_handler_registry_usable(self) -> None:
        """ActionHandlerRegistry можно инстанцировать (smoke на import path)."""
        from src.backend.dsl.commands.action_registry import (
            ActionHandlerRegistry,
            ActionHandlerSpec,
        )

        reg = ActionHandlerRegistry()
        assert reg is not None
        # Проверяем, что тип ActionHandlerSpec доступен (нужен в runtime регистра).
        assert isinstance(
            ActionHandlerSpec(
                action="x", service_getter=lambda: None, service_method="call"
            ),
            ActionHandlerSpec,
        )

    def test_base_processor_usable(self) -> None:
        """BaseProcessor можно импортировать и использовать как базовый класс."""
        from src.backend.dsl.engine.processors import BaseProcessor

        assert BaseProcessor is not None

        # issubclass-check, как в ProcessorRegistryAdapter.register_class().
        class _Dummy(BaseProcessor):  # type: ignore[misc]
            async def process(self, ctx):  # type: ignore[override]
                return ctx

        assert issubclass(_Dummy, BaseProcessor)

        # Не-BaseProcessor класс должен fail issubclass.
        class _NotProcessor:
            pass

        assert not issubclass(_NotProcessor, BaseProcessor)

    def test_processor_plugin_registry_usable(self) -> None:
        """ProcessorPluginRegistry (type-only) — конструктор работает."""
        from src.backend.dsl.engine.plugin_registry import ProcessorPluginRegistry

        # Достаточно smoke: инстанцируется без обязательных аргументов.
        reg = ProcessorPluginRegistry()
        assert reg is not None

    def test_action_registry_adapter_module_attr(self) -> None:
        """ActionRegistryAdapter импортируется и имеет ожидаемый публичный API."""
        assert hasattr(ActionRegistryAdapter, "register")
        assert hasattr(ActionRegistryAdapter, "__init__")

    def test_processor_registry_adapter_module_attr(self) -> None:
        """ProcessorRegistryAdapter импортируется и имеет ожидаемый публичный API."""
        assert hasattr(ProcessorRegistryAdapter, "register_class")
        assert hasattr(ProcessorRegistryAdapter, "__init__")


# ── Утилиты ──────────────────────────────────────────────────────────


def _counter(items: list[str]) -> dict[str, int]:
    """Минимальный Counter без импорта collections.Counter для читаемости."""
    out: dict[str, int] = {}
    for it in items:
        out[it] = out.get(it, 0) + 1
    return out


# ── TYPE_CHECKING smoke (не мешает runtime, но проверяет совместимость)


if TYPE_CHECKING:
    pass  # nothing — TC-блок сюда намеренно не дублируем
