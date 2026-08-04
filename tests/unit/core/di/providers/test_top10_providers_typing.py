"""S3.5: regression-тесты на ``Any``-leak cleanup в top-10 most-used providers.

Цель: убедиться, что narrowed return types (1) присутствуют в исходниках
на статическом уровне (TYPE_CHECKING / runtime annotations), и (2) runtime
поведение ``__getattr__`` и getter-функций не сломано.

Подробнее:
* ``session_manager.py:213`` — ``__getattr__`` narrowed ``Any`` → ``DatabaseSessionManager``.
* ``infrastructure_facade.py:31`` — ``__getattr__`` оставлен ``Any`` (justified by
  design: generic re-export shim для 90+ символов).
* ``infrastructure_locator.py:62-107`` — TYPE_CHECKING блок сужен для 8 из
  top-10 most-used (registry-driven providers, runtime ``-> Any`` сохраняется).
* ``infrastructure_locator.get_event_bus_facade_provider`` — runtime ``-> EventBusFacade``.
* ``observability_bridge.get_correlation_id`` — runtime ``-> str``.

Тесты проверяют:
1. ``inspect.get_annotations(eval_str=False)`` для runtime-narrowed функций.
2. ``ast``-парсинг TYPE_CHECKING блока в ``infrastructure_locator.py``.
3. Реальное runtime-поведение: ``main_session_manager`` = ``DatabaseSessionManager``;
   ``get_correlation_id()`` = ``str``; ``get_event_bus_facade_provider()`` = ``EventBusFacade``.
"""

from __future__ import annotations

import ast
import inspect
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
INFRA_LOCATOR_PATH = (
    REPO_ROOT
    / "src"
    / "backend"
    / "core"
    / "di"
    / "providers"
    / "infrastructure_locator.py"
)

# Top-10 most-used providers, замеренный usage-grep по src/ + tests/.
TOP10_PROVIDERS: tuple[str, ...] = (
    "get_redis_client_factory",  # 7 usages
    "get_event_bus_facade_provider",  # 7 usages
    "get_redis_client_class",  # 5 usages
    "get_correlation_id",  # 5 usages
    "get_unified_rate_limiter_attr",  # 4 usages
    "get_dsl_variables_attr",  # 4 usages
    "get_clickhouse_client_class",  # 3 usages
    "get_mongodb_client_class",  # 3 usages
    "get_elasticsearch_client_class",  # 3 usages
    "get_object_storage_class",  # 3 usages
)

# Static-only narrowed types из TYPE_CHECKING блока. Runtime-функции
# registry-driven providers сохраняют ``-> Any`` (justified by design).
EXPECTED_STATIC_TYPES: dict[str, str] = {
    "get_redis_client_factory": "Callable[[], Callable[[], RedisClient]]",
    "get_event_bus_facade_provider": "Callable[[], EventBusFacade]",
    "get_redis_client_class": "Callable[[], type[RedisClient]]",
    "get_correlation_id": "Callable[[], str]",
    # Динамические by design (lookup по имени атрибута модуля).
    "get_unified_rate_limiter_attr": "Callable[[str], Any]",
    "get_dsl_variables_attr": "Callable[[str], Any]",
    "get_clickhouse_client_class": "Callable[[], type[ClickHouseClient]]",
    "get_mongodb_client_class": "Callable[[], type[MongoDBClient]]",
    "get_elasticsearch_client_class": "Callable[[], type[ElasticSearchClient]]",
    "get_object_storage_class": "Callable[[], type[ObjectStorage]]",
}


def _parse_type_checking_block(source: str) -> dict[str, str]:
    """Возвращает ``{name: annotation_string}`` из ``if TYPE_CHECKING:`` блока.

    Используется для верификации narrowed types, которые mypy видит, но
    runtime ``inspect.get_annotations`` не видит (``TYPE_CHECKING`` — ``False``
    в runtime, аннотации из него не попадают в module ``__dict__``).
    """
    tree = ast.parse(source)
    type_checking: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        # Сопоставляем ``if TYPE_CHECKING:``
        test = node.test
        is_tc = (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
            isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
        )
        if not is_tc:
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                # ``name: Callable[[], Any]`` → annotation
                type_checking[stmt.target.id] = ast.unparse(stmt.annotation)
    return type_checking


class TestSessionManagerGetattr:
    """S3.5: ``session_manager.py:213`` — ``__getattr__`` Any → DatabaseSessionManager."""

    @pytest.mark.unit
    def test_getattr_returns_database_session_manager_instance(self) -> None:
        """``session_manager.main_session_manager`` = ``DatabaseSessionManager`` instance."""
        from src.backend.infrastructure.database.session_manager import (
            DatabaseSessionManager,
            main_session_manager,
        )

        assert isinstance(main_session_manager, DatabaseSessionManager), (
            f"main_session_manager должен быть DatabaseSessionManager, "
            f"получили {type(main_session_manager).__name__}"
        )

    @pytest.mark.unit
    def test_getattr_raises_attribute_error_for_unknown(self) -> None:
        """``session_manager.unknown_attr`` → ``AttributeError``."""
        with pytest.raises(AttributeError, match="has no attribute 'unknown_attr'"):
            from src.backend.infrastructure.database import (
                session_manager,  # noqa: F401
            )

            _ = session_manager.unknown_attr

    @pytest.mark.unit
    def test_getattr_signature_narrowed(self) -> None:
        """Runtime-annotation ``__getattr__`` narrowed с ``Any`` до ``DatabaseSessionManager``.

        ``session_manager.py`` без ``from __future__ import annotations``,
        поэтому ``eval_str=True`` нужен для класса (eager evaluation).
        """
        from src.backend.infrastructure.database import session_manager

        hints = inspect.get_annotations(session_manager.__getattr__, eval_str=True)
        from src.backend.infrastructure.database.session_manager import (
            DatabaseSessionManager,
        )

        assert hints["return"] is DatabaseSessionManager, (
            f"Ожидалось narrowed DatabaseSessionManager, получили {hints['return']!r}"
        )

    @pytest.mark.unit
    def test_getattr_param_signature_unchanged(self) -> None:
        """Сигнатура ``__getattr__(name: str)`` не сломана (BC)."""
        from src.backend.infrastructure.database import session_manager

        sig = inspect.signature(session_manager.__getattr__)
        assert list(sig.parameters) == ["name"], sig.parameters
        # Без ``from __future__ import annotations`` в session_manager.py
        # параметры evaluated eagerly.
        assert sig.parameters["name"].annotation is str


class TestInfrastructureFacadeGetattr:
    """S3.5: ``infrastructure_facade.py:31`` — ``__getattr__`` оставлен ``Any``.

    Justified by design: модуль — generic re-export shim для 90+ символов
    ``infrastructure_locator``. Narrowing убрал бы саму суть ленивого
    re-export-шаблона.
    """

    @pytest.mark.unit
    def test_getattr_keeps_any_justified_by_design(self) -> None:
        """``__getattr__`` return type остаётся ``Any`` (proven justified)."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from src.backend.core.di.providers import infrastructure_facade

        hints = inspect.get_annotations(
            infrastructure_facade.__getattr__, eval_str=False
        )
        assert hints["return"] == "Any", (
            f"infrastructure_facade.__getattr__ — generic re-export shim, "
            f"Any обоснован (см. D102); получили {hints['return']!r}"
        )

    @pytest.mark.unit
    def test_getattr_raises_for_unknown_name(self) -> None:
        """``infrastructure_facade.no_such_attr`` → ``AttributeError``."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from src.backend.core.di.providers import infrastructure_facade

        with pytest.raises(AttributeError):
            _ = infrastructure_facade.no_such_attr

    @pytest.mark.unit
    def test_getattr_proxies_known_name(self) -> None:
        """``infrastructure_facade.get_correlation_id`` работает через proxy."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from src.backend.core.di.providers import infrastructure_facade

        # correlation_id default = ""
        result = infrastructure_facade.get_correlation_id()
        assert isinstance(result, str), (
            f"infrastructure_facade.get_correlation_id() должно вернуть str, "
            f"получили {type(result).__name__}"
        )


class TestTop10StaticAnnotations:
    """S3.5: top-10 most-used providers получают narrowed types в TYPE_CHECKING."""

    @pytest.fixture(scope="class")
    def type_checking_annotations(self) -> dict[str, str]:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from src.backend.core.di.providers import infrastructure_locator

        source = inspect.getsource(infrastructure_locator)
        return _parse_type_checking_block(source)

    @pytest.mark.unit
    @pytest.mark.parametrize("provider_name", list(TOP10_PROVIDERS))
    def test_provider_present_in_type_checking(
        self, type_checking_annotations: dict[str, str], provider_name: str
    ) -> None:
        """Каждый top-10 provider объявлен в ``if TYPE_CHECKING:`` блоке."""
        assert provider_name in type_checking_annotations, (
            f"{provider_name} отсутствует в TYPE_CHECKING блоке "
            f"infrastructure_locator.py — добавьте narrowed declaration"
        )

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("provider_name", "expected_type"), list(EXPECTED_STATIC_TYPES.items())
    )
    def test_provider_static_type_narrowed(
        self,
        type_checking_annotations: dict[str, str],
        provider_name: str,
        expected_type: str,
    ) -> None:
        """Static annotation совпадает с EXPECTED_STATIC_TYPES."""
        actual = type_checking_annotations.get(provider_name)
        assert actual == expected_type, (
            f"{provider_name}: ожидалось {expected_type!r}, получили {actual!r}"
        )

    @pytest.mark.unit
    def test_no_any_in_static_annotations_for_static_narrowable(
        self, type_checking_annotations: dict[str, str]
    ) -> None:
        """Static-narrowable top-10 не должны быть ``Callable[[], Any]``.

        Динамические (``get_*_attr`` с ``name: str``) исключены — для них
        ``Callable[[str], Any]`` обоснован.
        """
        dynamic = {"get_unified_rate_limiter_attr", "get_dsl_variables_attr"}
        for name in TOP10_PROVIDERS:
            if name in dynamic:
                continue
            ann = type_checking_annotations.get(name, "")
            assert "Callable[[], Any]" not in ann, (
                f"{name} всё ещё ``Callable[[], Any]`` в TYPE_CHECKING — "
                f"sprint 3.5 не доделал. Актуально: {ann!r}"
            )


class TestTop10RuntimeBehavior:
    """S3.5: runtime semantics top-10 не сломаны после narrowing."""

    @pytest.mark.unit
    def test_get_correlation_id_returns_str(self) -> None:
        """``get_correlation_id()`` возвращает ``str`` (narrowed в observability_bridge)."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from src.backend.core.di.providers.infrastructure_locator import (
                get_correlation_id,
            )

        result = get_correlation_id()
        assert isinstance(result, str), (
            f"get_correlation_id() должно вернуть str, получили {type(result).__name__}"
        )

    @pytest.mark.unit
    def test_get_event_bus_facade_provider_returns_facade(self) -> None:
        """``get_event_bus_facade_provider()`` возвращает ``EventBusFacade`` instance."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from src.backend.core.di.providers import infrastructure_locator

        result = infrastructure_locator.get_event_bus_facade_provider()
        from src.backend.core.messaging.eventbus.facade import EventBusFacade

        assert isinstance(result, EventBusFacade), (
            f"get_event_bus_facade_provider() должно вернуть EventBusFacade, "
            f"получили {type(result).__name__}"
        )

    @pytest.mark.unit
    def test_observability_bridge_correlation_id_annotation_narrowed(self) -> None:
        """``observability_bridge.get_correlation_id`` runtime annotation = ``str``."""
        from src.backend.core.di.providers import observability_bridge

        hints = inspect.get_annotations(
            observability_bridge.get_correlation_id, eval_str=False
        )
        assert hints["return"] == "str", (
            f"observability_bridge.get_correlation_id narrowed с Any; "
            f"получили {hints['return']!r}"
        )

    @pytest.mark.unit
    def test_locator_event_bus_facade_annotation_narrowed(self) -> None:
        """``infrastructure_locator.get_event_bus_facade_provider`` runtime annotation = ``EventBusFacade``."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from src.backend.core.di.providers import infrastructure_locator

        hints = inspect.get_annotations(
            infrastructure_locator.get_event_bus_facade_provider, eval_str=False
        )
        assert hints["return"] == "EventBusFacade", (
            f"get_event_bus_facade_provider narrowed с Any; "
            f"получили {hints['return']!r}"
        )


class TestPublicApiUnchanged:
    """S3.5: public API не сломан — никаких новых kwarg, переименований."""

    @pytest.mark.unit
    def test_session_manager_exports_unchanged(self) -> None:
        """``__all__`` в session_manager.py не изменился."""
        from src.backend.infrastructure.database import session_manager

        expected = {
            "DatabaseSessionManager",
            "get_external_session_manager",
            "get_main_session_manager",
            "get_smart_read_session",
            "get_smart_write_session",
            "main_session_manager",
        }
        assert set(session_manager.__all__) == expected, (
            f"__all__ session_manager изменился: "
            f"было/стало = {expected ^ set(session_manager.__all__)}"
        )

    @pytest.mark.unit
    def test_facade_getattr_is_publicly_available(self) -> None:
        """``infrastructure_facade.get_X`` продолжает работать (back-compat)."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from src.backend.core.di.providers import infrastructure_facade

        # Back-compat: legacy import sites + monkeypatch paths.
        assert hasattr(infrastructure_facade, "get_correlation_id")
        assert hasattr(infrastructure_facade, "get_redis_client_factory")
        assert hasattr(infrastructure_facade, "get_elasticsearch_client_class")


class TestTypeAnnotationShape:
    """S3.5: structural smoke-test на форму narrowed annotations."""

    @pytest.mark.unit
    def test_any_not_used_in_narrowed_runtime_annotations(self) -> None:
        """S3.5 narrowed runtime-функции не возвращают ``Any``."""
        from src.backend.core.di.providers import observability_bridge

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from src.backend.core.di.providers import infrastructure_locator

        targets = [
            (observability_bridge.get_correlation_id, "str"),
            (infrastructure_locator.get_event_bus_facade_provider, "EventBusFacade"),
        ]
        for fn, expected in targets:
            hints = inspect.get_annotations(fn, eval_str=False)
            assert hints.get("return") != "Any", (
                f"{fn.__qualname__} всё ещё возвращает Any; ожидалось {expected!r}"
            )
