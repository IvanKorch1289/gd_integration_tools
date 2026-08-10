"""Cycle 1 DSL — unit-тесты для ``ActionHandlerRegistry``.

Покрывают исправления двух классов дефектов:

1. ``dispatch()``: payload-валидация через ``payload_model`` теперь
   срабатывает и для пустого ``{}`` (раньше условие ``and command.payload``
   тихо пропускало валидацию, скрывая нарушения required-полей).
2. ``register_with_metadata()``: атомарная проверка конфликта
   ``handler.payload_model`` ↔ ``metadata.input_model`` ДО записи —
   при конфликте выбрасывается :class:`ValueError` и реестр остаётся
   в неизменном состоянии (fail-closed). Explicit metadata-only
   семантика сохранена.
"""


from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from src.backend.core.interfaces.action_dispatcher import ActionMetadata
from src.backend.dsl.commands.action_registry import (
    ActionHandlerRegistry,
    ActionHandlerSpec,
)
from src.backend.schemas.invocation import ActionCommandSchema

# ----------------------------------------------------------------------
# Тестовые модели
# ----------------------------------------------------------------------


class _StrictPayload(BaseModel):
    """Payload с обязательным полем — для проверки пустого dict."""

    name: str


class _OptionalPayload(BaseModel):
    """Payload без обязательных полей — для проверки backward compat."""

    note: str | None = None


class _OtherPayload(BaseModel):
    """Другая модель — для проверки конфликта между handler и metadata."""

    value: int


# ----------------------------------------------------------------------
# Сервисы-стабы
# ----------------------------------------------------------------------


@dataclass(slots=True)
class _EchoService:
    """Сервис со sync-методом ``run``."""

    captured: dict[str, Any] | None = None

    def run(self, **kwargs: Any) -> dict[str, Any]:
        self.captured = dict(kwargs)
        return dict(kwargs)


@dataclass(slots=True)
class _AsyncEchoService:
    """Сервис с async-методом ``run``."""

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        return dict(kwargs)


# ----------------------------------------------------------------------
# Issue 1: payload-валидация для пустого dict
# ----------------------------------------------------------------------


class TestDispatchEmptyPayloadValidation:
    """``dispatch()`` обязан валидировать payload через ``payload_model``
    даже при ``command.payload == {}``.
    """

    async def test_empty_payload_with_required_field_raises_validation_error(
        self,
    ) -> None:
        """Пустой dict + required-поле → ValidationError (раньше тихо проскакивало)."""
        registry = ActionHandlerRegistry()
        registry.register(
            action="dsl.empty.strict",
            service_getter=lambda: _EchoService(),
            service_method="run",
            payload_model=_StrictPayload,
        )

        command = ActionCommandSchema(action="dsl.empty.strict", payload={})

        with pytest.raises(ValidationError):
            await registry.dispatch(command)

    async def test_empty_payload_passes_when_no_required_fields(self) -> None:
        """Пустой dict + модель без required-полей проходит валидацию."""
        registry = ActionHandlerRegistry()
        registry.register(
            action="dsl.empty.optional",
            service_getter=lambda: _EchoService(),
            service_method="run",
            payload_model=_OptionalPayload,
        )

        command = ActionCommandSchema(action="dsl.empty.optional", payload={})

        result = await registry.dispatch(command)

        assert result == {}

    async def test_non_empty_payload_still_validated(self) -> None:
        """Backward compat: непустой payload проходит через ту же ветку."""
        registry = ActionHandlerRegistry()
        registry.register(
            action="dsl.nonempty.strict",
            service_getter=lambda: _EchoService(),
            service_method="run",
            payload_model=_StrictPayload,
        )

        command = ActionCommandSchema(
            action="dsl.nonempty.strict", payload={"name": "alice"},
        )

        result = await registry.dispatch(command)

        assert result == {"name": "alice"}

    async def test_no_payload_model_uses_payload_directly(self) -> None:
        """Backward compat: без ``payload_model`` payload передаётся как есть."""
        registry = ActionHandlerRegistry()
        registry.register(
            action="dsl.nomodel",
            service_getter=lambda: _EchoService(),
            service_method="run",
            payload_model=None,
        )

        command = ActionCommandSchema(action="dsl.nomodel", payload={"x": 1})

        result = await registry.dispatch(command)

        assert result == {"x": 1}

    async def test_empty_payload_without_payload_model_uses_empty_dict(self) -> None:
        """Backward compat: ``{}`` без payload_model → ``method()`` без kwargs."""
        registry = ActionHandlerRegistry()
        registry.register(
            action="dsl.nomodel.empty",
            service_getter=lambda: _EchoService(),
            service_method="run",
            payload_model=None,
        )

        command = ActionCommandSchema(action="dsl.nomodel.empty", payload={})

        result = await registry.dispatch(command)

        assert result == {}

    async def test_async_method_dispatched_with_empty_payload(self) -> None:
        """Async-handler тоже получает пустой dict после валидации."""
        registry = ActionHandlerRegistry()
        registry.register(
            action="dsl.async.empty",
            service_getter=lambda: _AsyncEchoService(),
            service_method="run",
            payload_model=_OptionalPayload,
        )

        command = ActionCommandSchema(action="dsl.async.empty", payload={})

        result = await registry.dispatch(command)

        assert result == {}


# ----------------------------------------------------------------------
# Issue 2: атомарные конфликтные повторные регистрации
# ----------------------------------------------------------------------


class TestAtomicConflictReregistration:
    """``register_with_metadata()`` обязан отказывать в записи при
    конфликте payload_model между handler и metadata, не мутируя
    состояние реестра.
    """

    def test_conflicting_handler_payload_and_metadata_input_raises(self) -> None:
        """handler.payload_model ≠ metadata.input_model → ValueError."""
        registry = ActionHandlerRegistry()
        spec = ActionHandlerSpec(
            action="dsl.conflict.handler",
            service_getter=lambda: _EchoService(),
            service_method="run",
            payload_model=_StrictPayload,
        )
        conflicting_metadata = ActionMetadata(
            action="dsl.conflict.handler", input_model=_OtherPayload,
        )

        with pytest.raises(ValueError, match="Atomic re-registration conflict"):
            registry.register_with_metadata(
                action="dsl.conflict.handler",
                handler=spec,
                metadata=conflicting_metadata,
            )

    def test_conflicting_metadata_only_reregistration_raises(self) -> None:
        """metadata-only re-registration (handler=None) с input_model,
        отличным от existing handler.payload_model, → ValueError.
        """
        registry = ActionHandlerRegistry()
        # Сначала регистрируем handler с payload_model=_StrictPayload.
        registry.register(
            action="dsl.conflict.metadata_only",
            service_getter=lambda: _EchoService(),
            service_method="run",
            payload_model=_StrictPayload,
        )
        # Затем пытаемся перезаписать метаданные с input_model=_OtherPayload.
        conflicting_metadata = ActionMetadata(
            action="dsl.conflict.metadata_only", input_model=_OtherPayload,
        )

        with pytest.raises(ValueError, match="Atomic re-registration conflict"):
            registry.register_with_metadata(
                action="dsl.conflict.metadata_only",
                handler=None,
                metadata=conflicting_metadata,
            )

    def test_conflict_does_not_mutate_registry(self) -> None:
        """При конфликте ни _handlers, ни _metadata не меняются."""
        registry = ActionHandlerRegistry()
        # Сначала регистрируем handler + согласованную metadata,
        # чтобы _handlers[action].payload_model был задан.
        spec = ActionHandlerSpec(
            action="dsl.conflict.no_mutation",
            service_getter=lambda: _EchoService(),
            service_method="run",
            payload_model=_StrictPayload,
        )
        original_metadata = ActionMetadata(
            action="dsl.conflict.no_mutation",
            input_model=_StrictPayload,
            description="original",
        )
        registry.register_with_metadata(
            action="dsl.conflict.no_mutation",
            handler=spec,
            metadata=original_metadata,
        )
        # Конфликтующая попытка metadata-only перезаписи.
        conflicting_metadata = ActionMetadata(
            action="dsl.conflict.no_mutation",
            input_model=_OtherPayload,
            description="new",
        )

        with pytest.raises(ValueError):
            registry.register_with_metadata(
                action="dsl.conflict.no_mutation",
                handler=None,
                metadata=conflicting_metadata,
            )

        # Состояние не изменилось.
        meta_after = registry.get_metadata("dsl.conflict.no_mutation")
        assert meta_after is original_metadata
        assert meta_after.description == "original"
        assert meta_after.input_model is _StrictPayload
        handler_after = registry._handlers["dsl.conflict.no_mutation"]
        assert handler_after is spec
        assert handler_after.payload_model is _StrictPayload

    def test_consistent_reregistration_succeeds(self) -> None:
        """Re-registration с согласованными моделями проходит штатно."""
        registry = ActionHandlerRegistry()
        first_metadata = ActionMetadata(
            action="dsl.consistent", input_model=_StrictPayload,
        )
        registry.register_with_metadata(
            action="dsl.consistent", handler=None, metadata=first_metadata,
        )
        # Та же модель — допустимая re-registration.
        second_metadata = ActionMetadata(
            action="dsl.consistent", input_model=_StrictPayload, description="enriched",
        )
        registry.register_with_metadata(
            action="dsl.consistent", handler=None, metadata=second_metadata,
        )

        meta = registry.get_metadata("dsl.consistent")
        assert meta is second_metadata
        assert meta.description == "enriched"

    def test_register_after_metadata_only_succeeds_with_matching_model(self) -> None:
        """Backward compat: ``register_with_metadata(handler=None)`` →
        ``register(payload_model=same)`` — рабочий паттерн (как в CRUD).
        """
        registry = ActionHandlerRegistry()
        metadata = ActionMetadata(
            action="dsl.crud.pattern", input_model=_StrictPayload, transports=("http",),
        )
        registry.register_with_metadata(
            action="dsl.crud.pattern", handler=None, metadata=metadata,
        )
        # Handler-attachment с тем же payload_model — допустимо.
        registry.register(
            action="dsl.crud.pattern",
            service_getter=lambda: _EchoService(),
            service_method="run",
            payload_model=_StrictPayload,
        )

        assert registry.is_registered("dsl.crud.pattern")
        assert registry.get_metadata("dsl.crud.pattern") is metadata

    def test_metadata_action_mismatch_still_raises(self) -> None:
        """Backward compat: pre-existing guard ``metadata.action != action`` сохранён."""
        registry = ActionHandlerRegistry()
        metadata = ActionMetadata(action="dsl.mismatch", input_model=_StrictPayload)

        with pytest.raises(ValueError, match="metadata.action"):
            registry.register_with_metadata(
                action="different.action", handler=None, metadata=metadata,
            )

    def test_callable_handler_still_rejected_with_type_error(self) -> None:
        """Backward compat: pre-existing TypeError для неподдерживаемого callable."""
        registry = ActionHandlerRegistry()
        metadata = ActionMetadata(action="dsl.bad.callable", input_model=_StrictPayload)

        def _bogus() -> None:
            return None

        with pytest.raises(TypeError, match="ActionHandlerSpec or None"):
            registry.register_with_metadata(
                action="dsl.bad.callable", handler=_bogus, metadata=metadata,
            )

    def test_no_conflict_when_handler_payload_model_is_none(self) -> None:
        """handler.payload_model=None + metadata.input_model=X — не конфликт
        (None означает «без валидации»).
        """
        registry = ActionHandlerRegistry()
        spec = ActionHandlerSpec(
            action="dsl.handler.optional",
            service_getter=lambda: _EchoService(),
            service_method="run",
            payload_model=None,
        )
        metadata = ActionMetadata(
            action="dsl.handler.optional", input_model=_StrictPayload,
        )

        registry.register_with_metadata(
            action="dsl.handler.optional", handler=spec, metadata=metadata,
        )

        assert registry.is_registered("dsl.handler.optional")
        assert registry.get_metadata("dsl.handler.optional") is metadata

    def test_no_conflict_when_metadata_input_model_is_none(self) -> None:
        """handler.payload_model=X + metadata.input_model=None — не конфликт."""
        registry = ActionHandlerRegistry()
        spec = ActionHandlerSpec(
            action="dsl.meta.optional",
            service_getter=lambda: _EchoService(),
            service_method="run",
            payload_model=_StrictPayload,
        )
        metadata = ActionMetadata(action="dsl.meta.optional", input_model=None)

        registry.register_with_metadata(
            action="dsl.meta.optional", handler=spec, metadata=metadata,
        )

        assert registry.is_registered("dsl.meta.optional")
        assert registry.get_metadata("dsl.meta.optional") is metadata

    def test_conflict_with_no_existing_handler_is_skipped(self) -> None:
        """handler=None + metadata.input_model=X, нет existing handler —
        конфликта нет, регистрация проходит.
        """
        registry = ActionHandlerRegistry()
        metadata = ActionMetadata(
            action="dsl.fresh.metadata_only", input_model=_StrictPayload,
        )

        registry.register_with_metadata(
            action="dsl.fresh.metadata_only", handler=None, metadata=metadata,
        )

        assert not registry.is_registered("dsl.fresh.metadata_only")
        assert registry.get_metadata("dsl.fresh.metadata_only") is metadata

    def test_metadata_only_reregistration_with_existing_handler_no_model(self) -> None:
        """metadata-only re-registration, existing handler без payload_model
        → не конфликт (existing не декларирует модель).
        """
        registry = ActionHandlerRegistry()
        # Существующий handler без payload_model.
        spec = ActionHandlerSpec(
            action="dsl.no.existing.model",
            service_getter=lambda: _EchoService(),
            service_method="run",
            payload_model=None,
        )
        registry.register_with_metadata(
            action="dsl.no.existing.model",
            handler=spec,
            metadata=ActionMetadata(action="dsl.no.existing.model"),
        )
        # Перезапись метаданных с input_model=X.
        new_metadata = ActionMetadata(
            action="dsl.no.existing.model", input_model=_StrictPayload,
        )

        registry.register_with_metadata(
            action="dsl.no.existing.model", handler=None, metadata=new_metadata,
        )

        assert registry.get_metadata("dsl.no.existing.model") is new_metadata
