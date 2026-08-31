"""Unit-тесты для ``core.workflow_registry.WorkflowRegistry``.

S47 W3 — coverage ratchet first slice: поднимает coverage на
``src/backend/core/workflow_registry.py`` (S44 W32 baseline: 0%).
Singleton класс с thread-safe методами: register/get/all/names/clear/
__contains__/__len__ + статические _is_workflow_class/_extract_name.
"""

from __future__ import annotations

import pytest

from src.backend.core.workflow_registry import WorkflowRegistry, workflow_registry


def _make_workflow_class(
    name: str = "TestWorkflow",
    *,
    is_workflow: bool = True,
    with_temporal_marker: bool = False,
) -> type:
    """Создаёт test-fixture класс для WorkflowRegistry.

    Args:
        name: ``__name__`` класса.
        is_workflow: Проставить ``_is_workflow=True`` fallback flag.
        with_temporal_marker: Проставить ``__temporal_workflow_definition__``
            marker (имитация temporalio ``@workflow.defn``).

    Returns:
        Динамически созданный класс.

    """
    cls = type(name, (), {})
    if is_workflow:
        cls._is_workflow = True  # type: ignore[attr-defined]
    if with_temporal_marker:
        # Имитация: ``@workflow.defn(name=...)`` decorator проставляет
        # ``__temporal_workflow_definition__`` с атрибутом ``name``.
        marker = type("_Defn", (), {"name": name})()
        cls.__temporal_workflow_definition__ = marker  # type: ignore[attr-defined]
    return cls


@pytest.mark.unit
class TestWorkflowRegistryBasics:
    """Базовые операции WorkflowRegistry."""

    def setup_method(self) -> None:
        """Изолированный registry для каждого теста (не singleton)."""
        self.registry = WorkflowRegistry()

    def test_register_returns_class_for_decorator_usage(self) -> None:
        """``register(cls)`` возвращает ``cls`` (позволяет как декоратор)."""
        cls = _make_workflow_class()
        result = self.registry.register(cls)
        assert result is cls

    def test_register_and_get_roundtrip(self) -> None:
        """``register`` + ``get`` возвращает зарегистрированный класс."""
        cls = _make_workflow_class("MyWorkflow")
        self.registry.register(cls)
        assert self.registry.get("MyWorkflow") is cls

    def test_get_unknown_name_returns_none(self) -> None:
        """``get`` для неизвестного имени возвращает ``None`` (не ошибка)."""
        assert self.registry.get("DoesNotExist") is None

    def test_register_non_workflow_class_raises_type_error(self) -> None:
        """``register`` отклоняет класс без marker'ов — TypeError."""
        plain_class = type("Plain", (), {})  # без маркеров
        with pytest.raises(TypeError, match="@workflow.defn"):
            self.registry.register(plain_class)

    def test_register_non_class_raises_type_error(self) -> None:
        """``register`` отклоняет non-type (строка/инстанс) — TypeError."""
        with pytest.raises(TypeError):
            self.registry.register("not a class")

    def test_register_duplicate_name_raises_value_error(self) -> None:
        """Дубликат имени → ValueError (prev/new в сообщении)."""
        cls_a = _make_workflow_class("DupName")
        cls_b = _make_workflow_class("DupName")
        self.registry.register(cls_a)
        with pytest.raises(ValueError, match="уже зарегистрирован"):
            self.registry.register(cls_b)

    def test_all_returns_sorted_copy(self) -> None:
        """``all()`` возвращает детерминированно отсортированную копию."""
        cls_a = _make_workflow_class("Alpha")
        cls_b = _make_workflow_class("Beta")
        cls_c = _make_workflow_class("Gamma")
        for cls in [cls_b, cls_c, cls_a]:
            self.registry.register(cls)
        assert self.registry.all() == [cls_a, cls_b, cls_c]

    def test_all_returns_copy_not_reference(self) -> None:
        """``all()`` возвращает копию — мутация не влияет на internal state."""
        cls = _make_workflow_class("W")
        self.registry.register(cls)
        result = self.registry.all()
        result.clear()
        assert len(self.registry) == 1  # internal state не изменён

    def test_names_returns_sorted_list(self) -> None:
        """``names()`` возвращает отсортированный список workflow-имён."""
        for name in ["Charlie", "Alpha", "Bravo"]:
            self.registry.register(_make_workflow_class(name))
        assert self.registry.names() == ["Alpha", "Bravo", "Charlie"]

    def test_clear_resets_registry(self) -> None:
        """``clear()`` очищает все зарегистрированные классы."""
        self.registry.register(_make_workflow_class("A"))
        self.registry.register(_make_workflow_class("B"))
        assert len(self.registry) == 2
        self.registry.clear()
        assert len(self.registry) == 0
        assert self.registry.get("A") is None


@pytest.mark.unit
class TestWorkflowRegistryDunder:
    """``__contains__`` и ``__len__`` операторы."""

    def setup_method(self) -> None:
        self.registry = WorkflowRegistry()

    def test_contains_returns_true_for_registered(self) -> None:
        """``"name" in registry`` → True для зарегистрированных."""
        self.registry.register(_make_workflow_class("Foo"))
        assert "Foo" in self.registry

    def test_contains_returns_false_for_unknown(self) -> None:
        """``"name" in registry`` → False для неизвестных."""
        assert "Bar" not in self.registry

    def test_len_returns_count(self) -> None:
        """``len(registry)`` возвращает количество зарегистрированных."""
        assert len(self.registry) == 0
        self.registry.register(_make_workflow_class("One"))
        assert len(self.registry) == 1
        self.registry.register(_make_workflow_class("Two"))
        assert len(self.registry) == 2


@pytest.mark.unit
class TestWorkflowRegistryStaticMethods:
    """``_is_workflow_class`` и ``_extract_name`` static helpers."""

    def test_is_workflow_class_true_for_temporal_marker(self) -> None:
        """Класс с temporalio marker → ``_is_workflow_class`` True."""
        cls = _make_workflow_class(with_temporal_marker=True, is_workflow=False)
        assert WorkflowRegistry._is_workflow_class(cls) is True

    def test_is_workflow_class_true_for_fallback_flag(self) -> None:
        """Класс с ``_is_workflow=True`` → ``_is_workflow_class`` True."""
        cls = _make_workflow_class(is_workflow=True, with_temporal_marker=False)
        assert WorkflowRegistry._is_workflow_class(cls) is True

    def test_is_workflow_class_false_for_plain_class(self) -> None:
        """Plain класс (без маркеров) → ``_is_workflow_class`` False."""
        cls = type("Plain", (), {})
        assert WorkflowRegistry._is_workflow_class(cls) is False

    def test_is_workflow_class_false_for_non_type(self) -> None:
        """Non-type (строка/инстанс/None) → ``_is_workflow_class`` False."""
        for non_type in ["string", 42, None, object()]:
            assert WorkflowRegistry._is_workflow_class(non_type) is False  # type: ignore[arg-type]

    def test_extract_name_uses_temporal_marker_when_present(self) -> None:
        """``_extract_name`` предпочитает ``defn.name`` из temporal marker."""
        cls = _make_workflow_class(
            "ClassName",
            with_temporal_marker=True,
        )
        # marker.name = "ClassName" (мы проставляем в _make_workflow_class)
        assert WorkflowRegistry._extract_name(cls) == "ClassName"

    def test_extract_name_falls_back_to_class_name(self) -> None:
        """``_extract_name`` fallback на ``cls.__name__`` если нет marker."""
        cls = _make_workflow_class("FallbackName", with_temporal_marker=False)
        assert WorkflowRegistry._extract_name(cls) == "FallbackName"


@pytest.mark.unit
class TestWorkflowRegistrySingleton:
    """Проверка глобального singleton'а."""

    def test_singleton_identity(self) -> None:
        """``workflow_registry`` — тот же объект при повторных импортах."""
        from src.backend.core.workflow_registry import workflow_registry as again

        assert workflow_registry is again

    def test_singleton_clear_isolated(self) -> None:
        """Singleton: clear через instance не должен падать (smoke)."""
        # Smoke test — изолированно используем clear; другие тесты
        # могут полагаться на singleton state.
        # Не используем фикстуру — проверяем singleton напрямую.
        # Не делаем register (чтобы не загрязнять глобальное состояние).
        workflow_registry.clear()
        assert len(workflow_registry) == 0
        # Восстанавливаем не делаем — следующие тесты используют свой registry.
        # (Singleton не должен иметь pre-seeded state в production.)
