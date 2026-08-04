"""Sprint 1.3 — composition root и resolver для AIGateway (L5 Security Chain).

Проверяет, что ``AIGateway`` строится через composition root
(``app.state.ai_gateway``) с обязательными DI, а все указанные callsite
используют :func:`get_ai_gateway` вместо прямого ``AIGateway()``.

Сценарии:
1. ``get_ai_gateway()`` возвращает instance с policy_resolver / capability_gate
   / token_budget (composition root wired).
2. Composition root (``register_app_state``) регистрирует ``app.state.ai_gateway``.
3. Call-сайты ``build_and_run_agent``, ``LLMCallProcessor``,
   ``AIToolDispatchProcessor`` и ``_agent_invoke_activity`` используют
   ``get_ai_gateway()`` (AST-анализ — регрессия на возврат к ``AIGateway()``).
4. На production ``AIGateway()`` без DI → AIGatewayProductionWiringError.
5. На development ``AIGateway()`` без DI → guard пропускает.
6. ``get_ai_gateway()`` в production-конфиге возвращает gateway с полным DI.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.unit


_REPO_ROOT = Path(__file__).resolve().parents[4]


def _read_ast(path: Path) -> ast.Module:
    """Парсит исходник в AST (только Python 3.10+ синтаксис)."""
    return ast.parse(path.read_text(encoding="utf-8"))


def _find_bare_aigateway_calls(tree: ast.Module) -> list[tuple[int, int, str]]:
    """Ищет вызовы ``AIGateway()`` без аргументов.

    Возвращает список ``(line, col, snippet)`` — узлы ``ast.Call`` с
    ``func.id == "AIGateway"`` (или ``func.attr == "AIGateway"``) и пустым
    ``args`` / ``keywords``.

    Сопоставление идёт по ``func`` id, не по тексту — комментарии и
    docstring'и с упоминанием ``AIGateway`` НЕ считаются.
    """
    bare: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name: str | None = None
        if isinstance(func, ast.Name) and func.id == "AIGateway":
            name = "AIGateway"
        elif isinstance(func, ast.Attribute) and func.attr == "AIGateway":
            name = "AIGateway"
        if name is None:
            continue
        if not node.args and not node.keywords:
            bare.append((node.lineno, node.col_offset, name))
    return bare


def _uses_get_ai_gateway(tree: ast.Module) -> bool:
    """Проверяет, что в модуле есть ``get_ai_gateway`` (Name или Attribute)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "get_ai_gateway":
            return True
        if isinstance(node, ast.Attribute) and node.attr == "get_ai_gateway":
            return True
    return False


def _patch_app_environment(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """Подменяет ``settings.app.environment`` на ``value``."""
    from src.backend.core.config import settings as settings_module

    monkeypatch.setattr(settings_module.settings.app, "environment", value)


def test_get_ai_gateway_returns_instance_with_di() -> None:
    """``get_ai_gateway()`` возвращает AIGateway с DI-инъекциями."""
    from src.backend.services.ai.gateway_adapter import get_ai_gateway

    gateway = get_ai_gateway()
    assert gateway is not None
    assert gateway._policy_resolver is not None
    assert gateway._capability_gate is not None
    assert gateway._token_budget is not None


def test_get_ai_gateway_is_idempotent() -> None:
    """Повторный вызов :func:`get_ai_gateway` возвращает тот же instance."""
    from src.backend.services.ai.gateway_adapter import get_ai_gateway

    a = get_ai_gateway()
    b = get_ai_gateway()
    assert a is b


def test_composition_root_registers_ai_gateway_in_app_state() -> None:
    """``register_app_state`` проставляет ``app.state.ai_gateway``."""
    from fastapi import FastAPI

    from src.backend.core.di.app_state import reset_app_state
    from src.backend.plugins.composition.di import register_app_state

    app = FastAPI()
    try:
        register_app_state(app)
        assert hasattr(app.state, "ai_gateway"), (
            "register_app_state должен зарегистрировать app.state.ai_gateway"
        )
        gateway = app.state.ai_gateway
        assert gateway is not None
        assert gateway._policy_resolver is not None
        assert gateway._capability_gate is not None
        assert gateway._token_budget is not None
    finally:
        reset_app_state()


# ────────────── Call-site regression: ни один не должен вызывать AIGateway() ──


_CALL_SITE_FILES: tuple[tuple[str, str], ...] = (
    ("ai_graph", "src/backend/services/ai/ai_graph.py"),
    ("llmcall_processor", "src/backend/dsl/engine/processors/ai/llmcall_processor.py"),
    (
        "ai_tool_dispatch",
        "src/backend/dsl/engine/processors/agent_dsl/ai_tool_dispatch.py",
    ),
    ("activity_bridge", "src/backend/dsl/workflow/compiler/activity_bridge.py"),
)


@pytest.mark.parametrize(("label", "relpath"), _CALL_SITE_FILES)
def test_call_site_uses_get_ai_gateway(label: str, relpath: str) -> None:
    """Каждый callsite импортирует ``get_ai_gateway`` и НЕ создаёт ``AIGateway()``."""
    src_path = _REPO_ROOT / relpath
    assert src_path.exists(), f"Не нашёл {src_path}"
    tree = _read_ast(src_path)

    bare = _find_bare_aigateway_calls(tree)
    assert not bare, (
        f"{relpath}: остался bare AIGateway() — замени на get_ai_gateway(). "
        f"Найдено {len(bare)} вызов(ов): {bare!r}"
    )
    assert _uses_get_ai_gateway(tree), (
        f"{relpath}: не использует get_ai_gateway() resolver"
    )


# ────────────── Production fail-closed / dev permissive ──────────────


@pytest.mark.asyncio
async def test_resolved_gateway_under_production_has_full_di(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production + get_ai_gateway() → gateway с полным DI проходит guard."""
    from src.backend.core.ai.gateway_models import AIRequest, AIResponse
    from src.backend.core.di.app_state import reset_app_state
    from src.backend.services.ai.gateway_adapter import get_ai_gateway

    _patch_app_environment(monkeypatch, "production")

    gateway = get_ai_gateway()
    assert gateway._policy_resolver is not None
    assert gateway._capability_gate is not None
    assert gateway._token_budget is not None

    sentinel = AIResponse(content="prod-ok")
    enforced_mock = AsyncMock(return_value=sentinel)
    monkeypatch.setattr(gateway, "_enforced_invoke", enforced_mock)

    request = AIRequest(
        workflow_id="wf", tenant_id="t-1", correlation_id="req-1", prompt_inline="p"
    )
    response = await gateway.invoke(request)
    assert response is sentinel
    reset_app_state()


@pytest.mark.asyncio
async def test_bare_aigateway_under_production_raises_wiring_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production + AIGateway() без DI → AIGatewayProductionWiringError."""
    from src.backend.core.ai.errors import AIGatewayProductionWiringError
    from src.backend.core.ai.gateway import AIGateway
    from src.backend.core.ai.gateway_models import AIRequest

    _patch_app_environment(monkeypatch, "production")

    gateway = AIGateway()
    request = AIRequest(
        workflow_id="wf", tenant_id="t-1", correlation_id="req-1", prompt_inline="p"
    )
    with pytest.raises(AIGatewayProductionWiringError) as exc_info:
        await gateway.invoke(request)
    msg = str(exc_info.value)
    for missing in ("policy_resolver", "capability_gate", "token_budget"):
        assert missing in msg


@pytest.mark.asyncio
async def test_bare_aigateway_under_development_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Development + AIGateway() без DI → guard пропускает (backward-compat)."""
    from src.backend.core.ai.gateway import AIGateway
    from src.backend.core.ai.gateway_models import AIRequest, AIResponse

    _patch_app_environment(monkeypatch, "development")

    gateway = AIGateway()
    sentinel = AIResponse(content="dev-ok")
    enforced_mock = AsyncMock(return_value=sentinel)
    monkeypatch.setattr(gateway, "_enforced_invoke", enforced_mock)

    request = AIRequest(
        workflow_id="wf", tenant_id="t-1", correlation_id="req-1", prompt_inline="p"
    )
    response = await gateway.invoke(request)
    assert response is sentinel


def test_activity_bridge_uses_get_ai_gateway_signature() -> None:
    """``_agent_invoke_activity`` — async-обёртка Temporal.

    Проверяем, что функция по сигнатуре соответствует Temporal activity
    (async def, returns coroutine) и в её AST нет ``AIGateway()``.
    """
    from src.backend.dsl.workflow.compiler import activity_bridge

    fn = activity_bridge._agent_invoke_activity
    assert inspect.iscoroutinefunction(fn)
    src = inspect.getsource(fn)
    tree = ast.parse(src)
    bare = _find_bare_aigateway_calls(tree)
    assert not bare, (
        f"_agent_invoke_activity всё ещё создаёт AIGateway() напрямую: {bare!r}"
    )
    assert _uses_get_ai_gateway(tree), (
        "_agent_invoke_activity не использует get_ai_gateway() resolver"
    )


def test_aigateway_provider_returns_instance_with_di() -> None:
    """``get_ai_gateway_provider`` — composition provider с обязательными DI."""
    from src.backend.core.di.providers.ai import (
        _build_ai_gateway_singleton,
        _overrides,
        get_ai_gateway_provider,
    )

    _overrides.pop("ai_gateway", None)
    _build_ai_gateway_singleton.cache_clear()
    try:
        gateway = get_ai_gateway_provider()
        assert gateway is not None
        assert gateway._policy_resolver is not None
        assert gateway._capability_gate is not None
        assert gateway._token_budget is not None
    finally:
        _overrides.pop("ai_gateway", None)
        _build_ai_gateway_singleton.cache_clear()


def test_aigateway_provider_is_singleton() -> None:
    """Provider использует ``lru_cache`` — повторный вызов возвращает тот же instance."""
    from src.backend.core.di.providers.ai import (
        _build_ai_gateway_singleton,
        _overrides,
        get_ai_gateway_provider,
    )

    _overrides.pop("ai_gateway", None)
    _build_ai_gateway_singleton.cache_clear()
    try:
        a = get_ai_gateway_provider()
        b = get_ai_gateway_provider()
        assert a is b
    finally:
        _overrides.pop("ai_gateway", None)
        _build_ai_gateway_singleton.cache_clear()


# ────────────── Sanity: AIGateway facade стабильна ──────────────


def test_aigateway_facade_import_path_stable() -> None:
    """AIGateway импортируется через ``core.ai`` (public API stable)."""
    from src.backend.core.ai import AIGateway as GatewayFromCore
    from src.backend.core.ai.gateway import AIGateway as GatewayFromSubpackage

    assert GatewayFromCore is GatewayFromSubpackage


@pytest.mark.asyncio
async def test_resolved_gateway_invoke_succeeds_with_full_di(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``get_ai_gateway().invoke`` доходит до ``_enforced_invoke`` без raise."""
    from src.backend.core.ai.gateway_models import AIRequest, AIResponse
    from src.backend.core.di.app_state import reset_app_state
    from src.backend.services.ai.gateway_adapter import get_ai_gateway

    gateway = get_ai_gateway()
    sentinel = AIResponse(content="ok")
    enforced_mock = AsyncMock(return_value=sentinel)
    monkeypatch.setattr(gateway, "_enforced_invoke", enforced_mock)

    request = AIRequest(
        workflow_id="credit_check",
        tenant_id="premium",
        correlation_id="req-1",
        prompt_inline="hi",
    )
    response = await gateway.invoke(request)
    assert response is sentinel
    enforced_mock.assert_awaited_once_with(request)
    reset_app_state()
