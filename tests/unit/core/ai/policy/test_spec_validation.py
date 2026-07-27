"""Unit-тесты валидации :class:`AIPolicySpec` (Sprint 25 W2, ADR-NEW-20).

Проверяют:

* Pydantic v2 валидация полей;
* defaults для :class:`BudgetSpec` / :class:`AuditSpec` / :class:`MemorySpec`;
* :class:`GuardRef.on_block` Literal restriction;
* :class:`SanitizerRef.on_error` Literal restriction;
* загрузка PoC из ``ai_policies/credit_check_strict.policy.yaml``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from src.backend.core.ai.policy import (
    AIPolicySpec,
    AuditSpec,
    BackendSpec,
    BudgetSpec,
    GuardRef,
    MemorySpec,
    ModelRouterSpec,
    SanitizerRef,
)


def test_minimal_policy_spec() -> None:
    """AIPolicySpec с минимальными required полями валиден."""
    policy = AIPolicySpec(
        name="minimal",
        workflow_pattern="*",
        model_router=ModelRouterSpec(primary="openai/gpt-4o-mini"),
    )
    assert policy.name == "minimal"
    assert policy.version == 1
    assert policy.tenant_pattern == "*"
    assert policy.model_router.fallback == []
    assert policy.budget.max_tokens_prompt == 8000
    assert policy.audit.schema_version == 1
    assert policy.required is True


def test_budget_spec_defaults() -> None:
    """BudgetSpec defaults соответствуют ADR-NEW-20."""
    budget = BudgetSpec()
    assert budget.max_tokens_prompt == 8000
    assert budget.max_tokens_completion == 2000
    assert budget.max_cost_usd == 0.50
    assert budget.ttl_s == 3600


def test_audit_spec_extra_attrs() -> None:
    """AuditSpec позволяет произвольные extra_attrs."""
    audit = AuditSpec(extra_attrs={"compliance": "152-FZ", "domain": "banking"})
    assert audit.extra_attrs["compliance"] == "152-FZ"
    assert audit.schema_version == 1


def test_sanitizer_ref_on_error_literal() -> None:
    """SanitizerRef.on_error ограничен Literal значениями."""
    SanitizerRef(name="presidio:ru", on_error="fail")
    SanitizerRef(name="presidio:ru", on_error="warn")
    SanitizerRef(name="presidio:ru", on_error="skip")
    with pytest.raises(ValidationError):
        SanitizerRef(name="presidio:ru", on_error="invalid")  # type: ignore[arg-type]


def test_guard_ref_on_block_literal() -> None:
    """GuardRef.on_block ограничен Literal значениями."""
    GuardRef(name="nemo:colang", on_block="fail")
    GuardRef(name="nemo:colang", on_block="warn")
    GuardRef(name="nemo:colang", on_block="dlq")
    with pytest.raises(ValidationError):
        GuardRef(name="nemo:colang", on_block="reject")  # type: ignore[arg-type]


def test_memory_spec_optional_backends() -> None:
    """MemorySpec — все backends опциональны."""
    memory = MemorySpec()
    assert memory.short_term is None
    assert memory.long_term is None
    assert memory.episodic is None
    assert memory.checkpointer is None
    assert memory.tenant_isolation is True
    assert memory.encryption is True


def test_memory_spec_with_backends() -> None:
    """MemorySpec с конкретными backends."""
    memory = MemorySpec(
        short_term=BackendSpec(
            backend="redis", namespace="credit:short:{tenant_id}", ttl=3600
        ),
        long_term=BackendSpec(
            backend="mem0+pgvector", namespace="credit:long:{tenant_id}"
        ),
    )
    assert memory.short_term is not None
    assert memory.short_term.backend == "redis"
    assert memory.short_term.ttl == 3600
    assert memory.long_term is not None
    assert memory.long_term.ttl is None


def test_full_policy_spec_with_guards_and_sanitizers() -> None:
    """Полный AIPolicySpec с input/output санитайзерами + guards."""
    policy = AIPolicySpec(
        name="credit_check_strict",
        workflow_pattern="credit_check*",
        model_router=ModelRouterSpec(
            primary="openrouter/anthropic/claude-3.5-sonnet",
            fallback=["openrouter/openai/gpt-4o-mini"],
        ),
        input_sanitizers=[SanitizerRef(name="pii_tokenizer:reversible:ru_strict")],
        input_guards=[
            GuardRef(name="nemo:colang:topics"),
            GuardRef(name="nemo:colang:sensitive"),
        ],
        output_guards=[GuardRef(name="llama_guard:safe_v3", on_block="dlq")],
        output_sanitizers=[SanitizerRef(name="presidio:ru_anonymize", on_error="warn")],
    )
    assert len(policy.input_guards) == 2
    assert policy.output_guards[0].on_block == "dlq"
    assert policy.output_sanitizers[0].on_error == "warn"


def test_poc_yaml_loads_into_spec() -> None:
    """PoC ``ai_policies/credit_check_strict.policy.yaml`` валиден (M8 v2)."""
    repo_root = Path(__file__).resolve().parents[5]
    yaml_path = repo_root / "ai_policies" / "credit_check_strict.policy.yaml"
    if not yaml_path.exists():
        pytest.skip(f"PoC YAML not found at {yaml_path}")
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    policy = AIPolicySpec.model_validate(data)
    assert policy.name == "credit_check_strict"
    assert policy.required is True
    assert policy.workflow_pattern == "credit_check*"
    # M8: version bumped to 2 (removed orphan rebuff/llama_guard refs).
    assert policy.version == 2
    assert policy.budget.max_cost_usd == 0.25
    assert policy.audit.extra_attrs["compliance"] == "152-FZ"
    # M8: input_guards = 1 (was 2 — rebuff:default удалён в S172).
    assert len(policy.input_guards) == 1
    assert policy.input_guards[0].name == "nemo:colang:topics"
    # M8: output_guards = 1 (was 1 — заменён на lakera:default).
    assert len(policy.output_guards) == 1
    assert policy.output_guards[0].name == "lakera:default"
    assert policy.memory is not None
    assert policy.memory.tenant_isolation is True
    # M8: mem0+pgvector → qdrant.
    assert policy.memory.long_term.backend == "qdrant"


# ─── S172 M7.1 (ARC-010) typed-policy DSL hardening tests ─────────────


class TestStrictExtraForbid:
    """``extra="forbid"`` отклоняет typos в YAML policy."""

    def test_unknown_field_in_aipolicyspec_rejected(self) -> None:
        """``unknown_typo_field`` → ValidationError."""
        from src.backend.core.ai.policy.spec import AIPolicySpec

        spec_kwargs = {
            "name": "test",
            "version": 1,
            "workflow_pattern": "wf_*",
            "tenant_pattern": "*",
            "model_router": {"primary": "gpt-4o-mini"},
            "budget": {},
            "audit": {},
            "tools": {"whitelist": [], "blacklist": []},
        }
        with pytest.raises(ValidationError):
            AIPolicySpec.model_validate(
                {**spec_kwargs, "unknown_typo_field": "oops"},
            )

    def test_unknown_field_in_budgetspec_rejected(self) -> None:
        """``BudgetSpec.cost`` (typo для ``max_cost_usd``) → reject."""
        from src.backend.core.ai.policy.spec import BudgetSpec

        with pytest.raises(ValidationError):
            BudgetSpec.model_validate({"cost": 0.10})

    def test_unknown_field_in_toolspec_rejected(self) -> None:
        """``ToolsSpec.foo`` (typo) → reject."""
        from src.backend.core.ai.policy.spec import ToolsSpec

        with pytest.raises(ValidationError):
            ToolsSpec.model_validate({"foo": "bar"})


class TestCrossFieldConsistency:
    """Cross-field валидация (ARC-010 M7.1) — internal invariants."""

    def test_tools_whitelist_blacklist_intersection_rejected(self) -> None:
        """Один tool в whitelist И blacklist → reject."""
        from src.backend.core.ai.policy.spec import AIPolicySpec

        spec_kwargs = {
            "name": "test",
            "version": 1,
            "workflow_pattern": "wf_*",
            "tenant_pattern": "*",
            "model_router": {"primary": "gpt-4o-mini"},
            "budget": {},
            "audit": {},
        }
        with pytest.raises(ValidationError, match="tools.conflict"):
            AIPolicySpec.model_validate(
                {
                    **spec_kwargs,
                    "tools": {
                        "whitelist": ["allowed_a", "shared"],
                        "blacklist": ["denied", "shared"],
                    },
                },
            )

    def test_tools_no_intersection_accepted(self) -> None:
        """whitelist и blacklist disjoint → accept."""
        from src.backend.core.ai.policy.spec import AIPolicySpec

        spec = AIPolicySpec.model_validate(
            {
                "name": "test",
                "version": 1,
                "workflow_pattern": "wf_*",
                "tenant_pattern": "*",
                "model_router": {"primary": "gpt-4o-mini"},
                "budget": {},
                "audit": {},
                "tools": {
                    "whitelist": ["a", "b"],
                    "blacklist": ["c", "d"],
                },
            },
        )
        assert spec.tools.whitelist == ["a", "b"]

    def test_empty_primary_rejected(self) -> None:
        """``model_router.primary = ""`` → reject (no empty model)."""
        from src.backend.core.ai.policy.spec import AIPolicySpec

        spec_kwargs = {
            "name": "test",
            "version": 1,
            "workflow_pattern": "wf_*",
            "tenant_pattern": "*",
            "model_router": {"primary": ""},
            "budget": {},
            "audit": {},
            "tools": {},
        }
        with pytest.raises(ValidationError, match="model_router.primary"):
            AIPolicySpec.model_validate(spec_kwargs)

    def test_budget_prompt_less_than_completion_rejected(self) -> None:
        """``max_tokens_prompt < max_tokens_completion`` → reject."""
        from src.backend.core.ai.policy.spec import AIPolicySpec

        with pytest.raises(
            ValidationError, match="budget.inconsistent_tokens"
        ):
            AIPolicySpec.model_validate(
                {
                    "name": "test",
                    "version": 1,
                    "workflow_pattern": "wf_*",
                    "tenant_pattern": "*",
                    "model_router": {"primary": "gpt-4o-mini"},
                    "budget": {
                        "max_tokens_prompt": 1000,
                        "max_tokens_completion": 2000,
                    },
                    "audit": {},
                    "tools": {},
                },
            )
