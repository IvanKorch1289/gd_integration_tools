"""Unit tests for AIPolicySpec and nested Pydantic models.

Covers: construction, defaults, validation, nesting.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.backend.core.ai.policy.spec import (
    AIPolicySpec,
    AuditSpec,
    BackendSpec,
    BudgetSpec,
    GuardRef,
    MemorySpec,
    ModelRouterSpec,
    SanitizerRef,
)


class TestModelRouterSpec:
    """Tests for :class:`ModelRouterSpec`."""

    def test_minimal(self) -> None:
        spec = ModelRouterSpec(primary="openai/gpt-4")
        assert spec.primary == "openai/gpt-4"
        assert spec.fallback == []
        assert spec.timeout_s == 30.0
        assert spec.retry_attempts == 2

    def test_full(self) -> None:
        spec = ModelRouterSpec(
            primary="p",
            fallback=["f1", "f2"],
            timeout_s=10.0,
            retry_attempts=5,
        )
        assert spec.fallback == ["f1", "f2"]
        assert spec.timeout_s == 10.0
        assert spec.retry_attempts == 5


class TestSanitizerRef:
    """Tests for :class:`SanitizerRef`."""

    def test_defaults(self) -> None:
        ref = SanitizerRef(name="presidio:ru")
        assert ref.name == "presidio:ru"
        assert ref.config == {}
        assert ref.on_error == "fail"

    def test_custom(self) -> None:
        ref = SanitizerRef(name="x", config={"lang": "en"}, on_error="skip")
        assert ref.config == {"lang": "en"}
        assert ref.on_error == "skip"


class TestGuardRef:
    """Tests for :class:`GuardRef`."""

    def test_defaults(self) -> None:
        ref = GuardRef(name="nemo:colang")
        assert ref.name == "nemo:colang"
        assert ref.config == {}
        assert ref.on_block == "fail"

    def test_custom(self) -> None:
        ref = GuardRef(name="g", config={"t": 0.5}, on_block="warn")
        assert ref.on_block == "warn"


class TestBackendSpec:
    """Tests for :class:`BackendSpec`."""

    def test_minimal(self) -> None:
        spec = BackendSpec(backend="redis", namespace="ns")
        assert spec.backend == "redis"
        assert spec.namespace == "ns"
        assert spec.ttl is None

    def test_with_ttl(self) -> None:
        spec = BackendSpec(backend="pg", namespace="ns2", ttl=3600)
        assert spec.ttl == 3600


class TestMemorySpec:
    """Tests for :class:`MemorySpec`."""

    def test_defaults(self) -> None:
        spec = MemorySpec()
        assert spec.short_term is None
        assert spec.long_term is None
        assert spec.episodic is None
        assert spec.checkpointer is None
        assert spec.tenant_isolation is True
        assert spec.encryption is True

    def test_custom(self) -> None:
        st = BackendSpec(backend="redis", namespace="st")
        spec = MemorySpec(short_term=st, tenant_isolation=False, encryption=False)
        assert spec.short_term == st
        assert spec.tenant_isolation is False
        assert spec.encryption is False


class TestBudgetSpec:
    """Tests for :class:`BudgetSpec`."""

    def test_defaults(self) -> None:
        spec = BudgetSpec()
        assert spec.max_tokens_prompt == 8000
        assert spec.max_tokens_completion == 2000
        assert spec.max_cost_usd == 0.5
        assert spec.ttl_s == 3600
        assert spec.context_strategy == "rolling_window"

    def test_custom(self) -> None:
        spec = BudgetSpec(
            max_tokens_prompt=2048,
            max_tokens_completion=512,
            max_cost_usd=0.1,
            ttl_s=60,
            context_strategy="map_reduce",
        )
        assert spec.max_tokens_prompt == 2048
        assert spec.context_strategy == "map_reduce"

    def test_validation_fails_on_zero_tokens(self) -> None:
        with pytest.raises(ValidationError):
            BudgetSpec(max_tokens_prompt=0)


class TestAuditSpec:
    """Tests for :class:`AuditSpec`."""

    def test_defaults(self) -> None:
        spec = AuditSpec()
        assert spec.extra_attrs == {}
        assert spec.schema_version == 1

    def test_custom(self) -> None:
        spec = AuditSpec(extra_attrs={"k": "v"}, schema_version=2)
        assert spec.extra_attrs == {"k": "v"}
        assert spec.schema_version == 2


class TestAIPolicySpec:
    """Tests for top-level :class:`AIPolicySpec`."""

    def test_minimal(self) -> None:
        spec = AIPolicySpec(
            name="default",
            workflow_pattern="*",
            model_router=ModelRouterSpec(primary="openai/gpt-4"),
        )
        assert spec.name == "default"
        assert spec.version == 1
        assert spec.workflow_pattern == "*"
        assert spec.tenant_pattern == "*"
        assert spec.model_router.primary == "openai/gpt-4"
        assert spec.input_sanitizers == []
        assert spec.input_guards == []
        assert spec.output_guards == []
        assert spec.output_sanitizers == []
        assert spec.memory is None
        assert spec.budget is not None
        assert spec.audit is not None
        assert spec.required is True

    def test_model_property(self) -> None:
        spec = AIPolicySpec(
            name="x",
            workflow_pattern="wf*",
            model_router=ModelRouterSpec(primary="openai/gpt-4o"),
        )
        assert spec.model == "openai/gpt-4o"

    def test_full(self) -> None:
        spec = AIPolicySpec(
            name="credit",
            version=2,
            workflow_pattern="credit*",
            tenant_pattern="premium*",
            model_router=ModelRouterSpec(primary="openai/gpt-4"),
            input_sanitizers=[SanitizerRef(name="presidio:ru")],
            output_sanitizers=[SanitizerRef(name="jsonschema:Foo")],
            input_guards=[GuardRef(name="nemo:colang")],
            output_guards=[GuardRef(name="llama_guard:safe_v3")],
            budget=BudgetSpec(max_tokens_prompt=2048),
            memory=MemorySpec(backend="redis", namespace="ns"),
            audit=AuditSpec(extra_attrs={"compliance": "152-FZ"}),
            required=False,
        )
        assert spec.name == "credit"
        assert spec.version == 2
        assert spec.required is False

    def test_invalid_on_error_raises(self) -> None:
        """SanitizerRef.on_error must be one of the Literal values."""
        with pytest.raises(ValidationError):
            SanitizerRef(name="x", on_error="invalid")  # type: ignore[call-arg]

    def test_invalid_guard_on_block_raises(self) -> None:
        """GuardRef.on_block must be one of the Literal values."""
        with pytest.raises(ValidationError):
            GuardRef(name="x", on_block="invalid")  # type: ignore[call-arg]
