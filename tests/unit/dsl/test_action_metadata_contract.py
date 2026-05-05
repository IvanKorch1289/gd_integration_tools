"""Wave 14.1 post-sprint-2 техдолг #6 — contract-test метаданных action.

Проверяет инварианты :class:`ActionMetadata` для всех action,
которые регистрируются ``ActionRouterBuilder.add_action()`` при импорте
маршрутов API v1 (``get_v1_routers``). Цель — гарантировать, что
переход с прямого пути на ``ActionGatewayDispatcher`` через флаг
``use_dispatcher`` не упадёт из-за невалидной декларации.

Инварианты:

* ``action`` — непустая строка;
* ``transports`` — непустой кортеж строк;
* ``side_effect ∈ {"none", "read", "write", "external"}``;
* ``idempotent`` — ``bool``;
* ``permissions`` — ``tuple[str, ...]``;
* ``rate_limit`` — ``None`` либо положительное ``int``;
* ``timeout_ms`` — ``None`` либо положительное ``int``;
* ``deprecated`` — ``bool``;
* ``tags`` — ``tuple[str, ...]``.

Дополнительно: REST-конвенция вывода ``side_effect``/``idempotent`` из
HTTP-метода для специально подобранных action'ов.
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.core.actions.spec_to_metadata import action_spec_to_metadata
from src.backend.core.interfaces.action_dispatcher import ActionMetadata
from src.backend.dsl.commands.action_registry import action_handler_registry
from src.backend.entrypoints.api.generator.specs import ActionSpec

_ALLOWED_SIDE_EFFECTS = frozenset({"none", "read", "write", "external"})


@pytest.fixture(scope="module")
def registered_metadata() -> tuple[ActionMetadata, ...]:
    """Импортирует все API v1 routers и возвращает накопленные метаданные.

    ``get_v1_routers()`` лениво импортирует endpoint-модули, каждый из
    которых через ``ActionRouterBuilder.add_action()`` регистрирует
    ``ActionMetadata`` в ``action_handler_registry``. Тест работает с
    реальным content реестра — это и есть «контракт по факту».
    """
    from src.backend.entrypoints.api.v1.routers import get_v1_routers

    get_v1_routers()
    return action_handler_registry.list_metadata()


class TestRegisteredActionMetadata:
    def test_registry_is_not_empty(
        self, registered_metadata: tuple[ActionMetadata, ...]
    ) -> None:
        # Sanity: должно быть хотя бы несколько десятков action.
        assert len(registered_metadata) >= 50, (
            f"Зарегистрировано подозрительно мало action: "
            f"{len(registered_metadata)}"
        )

    def test_action_name_is_non_empty_string(
        self, registered_metadata: tuple[ActionMetadata, ...]
    ) -> None:
        for meta in registered_metadata:
            assert isinstance(meta.action, str) and meta.action, meta

    def test_transports_is_non_empty_tuple_of_strings(
        self, registered_metadata: tuple[ActionMetadata, ...]
    ) -> None:
        for meta in registered_metadata:
            assert isinstance(meta.transports, tuple), meta.action
            assert meta.transports, f"{meta.action}: transports пуст"
            for t in meta.transports:
                assert isinstance(t, str) and t, meta.action

    def test_side_effect_in_allowed_set(
        self, registered_metadata: tuple[ActionMetadata, ...]
    ) -> None:
        for meta in registered_metadata:
            assert meta.side_effect in _ALLOWED_SIDE_EFFECTS, (
                f"{meta.action}: side_effect={meta.side_effect!r}"
            )

    def test_idempotent_is_bool(
        self, registered_metadata: tuple[ActionMetadata, ...]
    ) -> None:
        for meta in registered_metadata:
            assert isinstance(meta.idempotent, bool), meta.action

    def test_permissions_are_string_tuple(
        self, registered_metadata: tuple[ActionMetadata, ...]
    ) -> None:
        for meta in registered_metadata:
            assert isinstance(meta.permissions, tuple), meta.action
            for p in meta.permissions:
                assert isinstance(p, str) and p, meta.action

    def test_rate_limit_none_or_positive_int(
        self, registered_metadata: tuple[ActionMetadata, ...]
    ) -> None:
        for meta in registered_metadata:
            if meta.rate_limit is None:
                continue
            assert isinstance(meta.rate_limit, int) and meta.rate_limit > 0, meta

    def test_timeout_ms_none_or_positive_int(
        self, registered_metadata: tuple[ActionMetadata, ...]
    ) -> None:
        for meta in registered_metadata:
            if meta.timeout_ms is None:
                continue
            assert isinstance(meta.timeout_ms, int) and meta.timeout_ms > 0, meta

    def test_deprecated_is_bool(
        self, registered_metadata: tuple[ActionMetadata, ...]
    ) -> None:
        for meta in registered_metadata:
            assert isinstance(meta.deprecated, bool), meta.action

    def test_tags_are_string_tuple(
        self, registered_metadata: tuple[ActionMetadata, ...]
    ) -> None:
        for meta in registered_metadata:
            assert isinstance(meta.tags, tuple), meta.action
            for t in meta.tags:
                assert isinstance(t, str), meta.action


class TestSpecToMetadataInference:
    """REST-конвенция вывода side_effect/idempotent из HTTP method."""

    @pytest.mark.parametrize(
        ("method", "expected_effect", "expected_idempotent"),
        [
            ("GET", "read", True),
            ("POST", "write", False),
            ("PUT", "write", True),
            ("PATCH", "write", False),
            ("DELETE", "write", True),
        ],
    )
    def test_default_inference_from_method(
        self,
        method: str,
        expected_effect: str,
        expected_idempotent: bool,
    ) -> None:
        spec = ActionSpec(
            name=f"test.{method.lower()}",
            method=method,  # type: ignore[arg-type]
            path="/x",
            summary="s",
            service_getter=lambda: None,
            service_method="m",
        )
        meta = action_spec_to_metadata(spec)
        assert meta.side_effect == expected_effect
        assert meta.idempotent is expected_idempotent

    def test_explicit_side_effect_overrides_inference(self) -> None:
        spec = ActionSpec(
            name="ext.call",
            method="POST",
            path="/x",
            summary="s",
            service_getter=lambda: None,
            service_method="m",
            side_effect="external",
            idempotent=True,
        )
        meta = action_spec_to_metadata(spec)
        assert meta.side_effect == "external"
        assert meta.idempotent is True

    def test_use_dispatcher_not_in_metadata(self) -> None:
        # ``use_dispatcher`` — control-plane поле, в metadata не уезжает.
        spec = ActionSpec(
            name="t.t",
            method="GET",
            path="/x",
            summary="s",
            service_getter=lambda: None,
            service_method="m",
            use_dispatcher=True,
        )
        meta = action_spec_to_metadata(spec)
        assert not hasattr(meta, "use_dispatcher")

    def test_action_id_overrides_name_in_metadata(self) -> None:
        # action_id — явная связь HTTP-роута с handler-именем.
        spec = ActionSpec(
            name="healthcheck_database",
            method="GET",
            path="/healthcheck-database",
            summary="s",
            service_getter=lambda: None,
            service_method="m",
            action_id="tech.check_database",
        )
        meta = action_spec_to_metadata(spec)
        assert meta.action == "tech.check_database"

    def test_action_id_default_falls_back_to_name(self) -> None:
        spec = ActionSpec(
            name="orders.create",
            method="POST",
            path="/c",
            summary="s",
            service_getter=lambda: None,
            service_method="m",
        )
        meta = action_spec_to_metadata(spec)
        assert meta.action == "orders.create"

    def test_extended_fields_propagated(self) -> None:
        spec = ActionSpec(
            name="ext.full",
            method="POST",
            path="/x",
            summary="s",
            service_getter=lambda: None,
            service_method="m",
            permissions=("admin", "ops"),
            rate_limit=10,
            timeout_ms=30000,
            deprecated=True,
            since_version="1.2.0",
            transports=("http", "queue"),
        )
        meta = action_spec_to_metadata(spec)
        assert meta.permissions == ("admin", "ops")
        assert meta.rate_limit == 10
        assert meta.timeout_ms == 30000
        assert meta.deprecated is True
        assert meta.since_version == "1.2.0"
        assert meta.transports == ("http", "queue")
