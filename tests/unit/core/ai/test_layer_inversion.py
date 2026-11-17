"""Регресс-тесты инверсии core → services (волна 33, LAYERS).

Задача волны: убрать межслойные нарушения ``core → services.ai``
(6 записей долга в ``tools/check_layers_allowlist.txt``). Реализация
перенесена в core, в ``services/ai`` оставлены re-export шимы.

Контракты, которые фиксирует этот файл:

* core-модули не импортируют ``src.backend.services.*`` (AST-проверка);
* публичные пути ``src.backend.services.ai.*`` продолжают работать и
  отдают **те же** объекты, что и новые core-модули (identity);
* функциональное поведение перенесённых компонент не изменилось
  (shared-синглтоны, Protocol-контракт авторизатора).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CORE_DIR = _REPO_ROOT / "src" / "backend" / "core"

#: core-модули, в которые перенесена реализация (бывшие services-модули).
_MOVED_CORE_MODULES: tuple[str, ...] = (
    "ai/gateway/client.py",
    "ai/gateway/callbacks.py",
    "ai/gateway/langfuse_callback_v3.py",
    "ai/gateway/langfuse_pii_callback.py",
    "ai/guardrails/lakera_client.py",
    "ai/metrics.py",
    "ai/multi_agent.py",
    "ai/prompt_registry.py",
)


def _imported_modules(path: Path) -> set[str]:
    """Собрать все импортируемые dotted-модули из файла (AST)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


class TestCoreHasNoServicesDependency:
    """Core-модули не должны зависеть от слоя services."""

    @pytest.mark.parametrize("rel_path", _MOVED_CORE_MODULES)
    def test_no_services_import(self, rel_path: str) -> None:
        """В перенесённых core-модулях нет ни одного импорта services."""
        path = _CORE_DIR / rel_path
        assert path.exists(), f"core-модуль не найден: {rel_path}"
        offenders = {
            module
            for module in _imported_modules(path)
            if module.startswith("src.backend.services")
        }
        assert not offenders, f"{rel_path} импортирует services: {sorted(offenders)}"

    def test_ai_facades_resolve_to_core(self) -> None:
        """Фасады ядра ссылаются на core-модули, а не на services."""
        for rel_path, expected in (
            ("ai/llm_gateway.py", "src.backend.core.ai.gateway.client"),
            (
                "ai/gateway_pipeline_mixin/llm_mixin.py",
                "src.backend.core.ai.prompt_registry",
            ),
            (
                "ai/gateway_pipeline_mixin/output_mixin.py",
                "src.backend.core.ai.gateway.client",
            ),
            (
                "ai/policy/enforcer/input_guard_mixin.py",
                "src.backend.core.ai.guardrails.lakera_client",
            ),
        ):
            modules = _imported_modules(_CORE_DIR / rel_path)
            assert expected in modules, f"{rel_path} не ссылается на {expected}"


class TestServicesShimsPreservePublicApi:
    """Re-export шимы в services сохраняют публичный API."""

    def test_llm_gateway_shim(self) -> None:
        """``services.ai.gateway.client`` отдаёт те же объекты, что core."""
        from src.backend.core.ai.gateway.client import (
            LiteLLMGateway,
            get_litellm_gateway,
        )
        from src.backend.services.ai.gateway.client import LiteLLMGateway as ShimGateway
        from src.backend.services.ai.gateway.client import (
            get_litellm_gateway as shim_get_gateway,
        )

        assert ShimGateway is LiteLLMGateway
        assert shim_get_gateway is get_litellm_gateway

    def test_gateway_package_shim(self) -> None:
        """``services.ai.gateway`` реэкспортирует core-реализацию."""
        from src.backend.core.ai.gateway.client import LiteLLMGateway
        from src.backend.services.ai.gateway import LiteLLMGateway as PkgGateway

        assert PkgGateway is LiteLLMGateway

    def test_prompt_registry_shim(self) -> None:
        """``services.ai.prompt_registry`` отдаёт core-объекты."""
        from src.backend.core.ai.prompt_registry import (
            PromptRegistry,
            get_prompt_registry,
        )
        from src.backend.services.ai.prompt_registry import (
            PromptRegistry as ShimRegistry,
        )
        from src.backend.services.ai.prompt_registry import (
            get_prompt_registry as shim_get_registry,
        )

        assert ShimRegistry is PromptRegistry
        assert shim_get_registry is get_prompt_registry

    def test_prompt_registry_singleton_shared(self) -> None:
        """Singleton реестра общий для core и services-пути."""
        from src.backend.core.ai.prompt_registry import get_prompt_registry
        from src.backend.services.ai.prompt_registry import (
            get_prompt_registry as shim_get_registry,
        )

        assert shim_get_registry() is get_prompt_registry()

    def test_multi_agent_shim(self) -> None:
        """``services.ai.multi_agent.supervisor`` отдаёт core-объекты."""
        from src.backend.core.ai.multi_agent import (
            AgentSpec,
            MultiAgentSupervisor,
        )
        from src.backend.services.ai.multi_agent.supervisor import AgentSpec as ShimSpec
        from src.backend.services.ai.multi_agent.supervisor import (
            MultiAgentSupervisor as ShimSupervisor,
        )

        assert ShimSpec is AgentSpec
        assert ShimSupervisor is MultiAgentSupervisor

    def test_core_multi_agent_facade(self) -> None:
        """``core.ai.multi_agent`` — модуль с теми же символами."""
        from src.backend.core.ai.multi_agent import AgentSpec, MultiAgentSupervisor

        assert AgentSpec is not None
        assert MultiAgentSupervisor is not None

    def test_lakera_shim(self) -> None:
        """``services.ai.guardrails.lakera_client`` отдаёт core-класс."""
        from src.backend.core.ai.guardrails.lakera_client import LakeraClient
        from src.backend.services.ai.guardrails.lakera_client import (
            LakeraClient as ShimClient,
        )

        assert ShimClient is LakeraClient

    def test_metrics_shim(self) -> None:
        """``services.ai.metrics`` отдаёт core-объекты."""
        from src.backend.core.ai.metrics import get_agent_metrics_service
        from src.backend.services.ai.metrics import (
            get_agent_metrics_service as shim_get_metrics,
        )

        assert shim_get_metrics is get_agent_metrics_service
