"""Unit-тесты :class:`PolicyResolver` YAML-loader (Sprint 25 W2, ADR-NEW-20).

Покрывает:

* Загрузка YAML-файла из root → :class:`AIPolicySpec`.
* Glob-match по ``workflow_pattern`` + ``tenant_pattern``.
* Per-tenant priority (extensions/ override > global ai_policies/).
* RAM-cache + ``reload()`` invalidation.
* :class:`PolicyLoadError` при невалидном YAML / Pydantic.
* Tenant-specific tenant_pattern имеет приоритет над wildcard.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from src.backend.core.ai.policy import (
    AIPolicySpec,
    PolicyLoadError,
    PolicyNotResolvedError,
    PolicyResolver,
)

GLOBAL_POLICY_YAML = dedent(
    """\
    name: credit_check_strict
    version: 1
    workflow_pattern: "credit_check*"
    tenant_pattern: "*"
    model_router:
      primary: "openrouter/anthropic/claude-3.5-sonnet"
    input_sanitizers:
      - { name: "pii_tokenizer:reversible:ru_strict", on_error: "fail" }
    required: true
    """
)

OVERRIDE_POLICY_YAML = dedent(
    """\
    name: credit_check_premium
    version: 2
    workflow_pattern: "credit_check*"
    tenant_pattern: "premium_*"
    model_router:
      primary: "openrouter/openai/gpt-4o"
      fallback: ["openrouter/anthropic/claude-3.5-sonnet"]
    required: true
    """
)

INVALID_POLICY_YAML = dedent(
    """\
    name: broken
    workflow_pattern: "*"
    # missing required `model_router`
    """
)

DOC_SUMMARIZE_POLICY_YAML = dedent(
    """\
    name: doc_summarize_lite
    workflow_pattern: "doc_*"
    tenant_pattern: "*"
    model_router:
      primary: "huggingface/local-llama-3-instruct"
    required: false
    """
)


def _write_policy(root: Path, filename: str, content: str) -> Path:
    """Записать YAML-policy в указанный каталог и вернуть путь."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / filename
    path.write_text(content, encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_resolver_loads_yaml_from_single_root(tmp_path: Path) -> None:
    """PolicyResolver загружает YAML из root и резолвит по workflow_pattern."""
    _write_policy(tmp_path, "credit_check_strict.policy.yaml", GLOBAL_POLICY_YAML)
    resolver = PolicyResolver(roots=[tmp_path])
    policy = await resolver.resolve("credit_check", "t-1")
    assert policy is not None
    assert isinstance(policy, AIPolicySpec)
    assert policy.name == "credit_check_strict"
    assert policy.required is True


@pytest.mark.asyncio
async def test_resolver_returns_none_when_no_match(tmp_path: Path) -> None:
    """Если ни одна policy не matched → None."""
    _write_policy(tmp_path, "credit_check_strict.policy.yaml", GLOBAL_POLICY_YAML)
    resolver = PolicyResolver(roots=[tmp_path])
    policy = await resolver.resolve("kyc_check", "t-1")
    assert policy is None


@pytest.mark.asyncio
async def test_resolver_workflow_pattern_glob(tmp_path: Path) -> None:
    """workflow_pattern='credit_check*' matches credit_check_v2."""
    _write_policy(tmp_path, "credit_check_strict.policy.yaml", GLOBAL_POLICY_YAML)
    resolver = PolicyResolver(roots=[tmp_path])
    policy = await resolver.resolve("credit_check_v2", "t-1")
    assert policy is not None
    assert policy.name == "credit_check_strict"


@pytest.mark.asyncio
async def test_resolver_tenant_specific_priority(tmp_path: Path) -> None:
    """Per-tenant override побеждает над wildcard глобальной policy.

    roots=[overrides_dir, global_dir] — первый match побеждает.
    Tenant 'premium_acme' попадает в override, остальные — в global.
    """
    global_dir = tmp_path / "ai_policies"
    overrides_dir = tmp_path / "extensions" / "credit" / "ai_policies"
    _write_policy(global_dir, "credit_check_strict.policy.yaml", GLOBAL_POLICY_YAML)
    _write_policy(
        overrides_dir, "credit_check_premium.policy.yaml", OVERRIDE_POLICY_YAML
    )

    resolver = PolicyResolver(roots=[overrides_dir, global_dir])
    premium_policy = await resolver.resolve("credit_check", "premium_acme")
    assert premium_policy is not None
    assert premium_policy.name == "credit_check_premium"
    assert premium_policy.model_router.primary == "openrouter/openai/gpt-4o"

    basic_policy = await resolver.resolve("credit_check", "basic_user")
    assert basic_policy is not None
    assert basic_policy.name == "credit_check_strict"


@pytest.mark.asyncio
async def test_resolver_caches_resolved_policies(tmp_path: Path) -> None:
    """Повторный resolve по тому же ключу — попадает в RAM cache."""
    yaml_path = _write_policy(
        tmp_path, "credit_check_strict.policy.yaml", GLOBAL_POLICY_YAML
    )
    resolver = PolicyResolver(roots=[tmp_path])
    first = await resolver.resolve("credit_check", "t-1")
    yaml_path.unlink()
    second = await resolver.resolve("credit_check", "t-1")
    assert second is first


@pytest.mark.asyncio
async def test_resolver_reload_clears_cache(tmp_path: Path) -> None:
    """reload() инвалидирует cache и заставляет повторно сканировать roots."""
    _write_policy(tmp_path, "credit_check_strict.policy.yaml", GLOBAL_POLICY_YAML)
    resolver = PolicyResolver(roots=[tmp_path])
    await resolver.resolve("credit_check", "t-1")
    assert resolver._cache  # type: ignore[attr-defined]
    resolver.reload()
    assert not resolver._cache  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_resolver_skips_missing_roots(tmp_path: Path) -> None:
    """Несуществующие корни игнорируются без ошибок."""
    missing = tmp_path / "does-not-exist"
    real = tmp_path / "real"
    _write_policy(real, "credit_check_strict.policy.yaml", GLOBAL_POLICY_YAML)
    resolver = PolicyResolver(roots=[missing, real])
    policy = await resolver.resolve("credit_check", "t-1")
    assert policy is not None
    assert policy.name == "credit_check_strict"


def test_resolver_raises_on_invalid_yaml(tmp_path: Path) -> None:
    """Невалидный YAML / Pydantic — PolicyLoadError."""
    _write_policy(tmp_path, "broken.policy.yaml", INVALID_POLICY_YAML)
    resolver = PolicyResolver(roots=[tmp_path])
    with pytest.raises(PolicyLoadError) as exc_info:
        resolver.list_policies()
    assert exc_info.value.path.name == "broken.policy.yaml"
    assert "validation" in exc_info.value.reason.lower()


@pytest.mark.asyncio
async def test_resolver_multiple_policies_first_match_wins(tmp_path: Path) -> None:
    """Несколько policies в одном root — первый match по workflow_pattern побеждает."""
    _write_policy(tmp_path, "credit_check_strict.policy.yaml", GLOBAL_POLICY_YAML)
    _write_policy(tmp_path, "doc_summarize_lite.policy.yaml", DOC_SUMMARIZE_POLICY_YAML)
    resolver = PolicyResolver(roots=[tmp_path])

    credit = await resolver.resolve("credit_check", "t-1")
    assert credit is not None and credit.name == "credit_check_strict"

    doc = await resolver.resolve("doc_summarize_pdf", "t-1")
    assert doc is not None and doc.name == "doc_summarize_lite"


def test_resolver_list_policies_returns_loaded(tmp_path: Path) -> None:
    """list_policies() возвращает snapshot загруженных AIPolicySpec."""
    _write_policy(tmp_path, "credit_check_strict.policy.yaml", GLOBAL_POLICY_YAML)
    _write_policy(tmp_path, "doc_summarize_lite.policy.yaml", DOC_SUMMARIZE_POLICY_YAML)
    resolver = PolicyResolver(roots=[tmp_path])
    policies = resolver.list_policies()
    assert len(policies) == 2
    names = {p.name for p in policies}
    assert names == {"credit_check_strict", "doc_summarize_lite"}


def test_policy_not_resolved_error_preserves_context() -> None:
    """PolicyNotResolvedError содержит workflow_id + tenant_id в сообщении."""
    err = PolicyNotResolvedError(workflow_id="credit_check", tenant_id="t-1")
    assert err.workflow_id == "credit_check"
    assert err.tenant_id == "t-1"
    assert "credit_check" in str(err)
    assert "t-1" in str(err)
