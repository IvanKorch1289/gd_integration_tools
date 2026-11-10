"""ADR-0437 — эндпоинты версий промптов.

Проверяется здесь:

* реестр умеет перечислять версии, активировать и сравнивать их;
* HTTP-слой отдаёт список промптов/версий, активирует версию, сравнивает A/B
  и создаёт новую версию (auto-increment).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from src.backend.core.di.providers import prompts as prompts_provider

pytestmark = pytest.mark.unit


@pytest.fixture()
def registry(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Изолированный реестр промптов."""
    from src.backend.services.ai.prompt_registry import PromptRegistry

    instance = PromptRegistry()
    instance.register("demo", template="Q: {q}\nA:", version=1)
    instance.register("demo", template="Q: {q}\nA!", version=2)
    monkeypatch.setattr(
        prompts_provider, "get_prompt_registry_provider", lambda: instance
    )
    return instance


def test_registry_lists_versions_and_active(registry: Any) -> None:
    """Версии перечисляются, активна последняя зарегистрированная."""
    versions = registry.list_versions("demo")
    assert [item["version"] for item in versions] == [1, 2]
    assert registry.active_version("demo") == 2
    assert registry.list_prompts() == ["demo"]


def test_registry_activate_changes_active_version(registry: Any) -> None:
    """Активация переключает production-версию."""
    assert registry.activate("demo", 1) is True
    assert registry.active_version("demo") == 1
    assert registry.activate("demo", 99) is False


def test_registry_compare_reports_template_diff(registry: Any) -> None:
    """Сравнение возвращает diff шаблонов (метрики — при наличии Langfuse)."""
    result = registry.compare("demo", 1, 2)
    assert result["template_diff"]["changed"] is True
    assert result["metric_diffs"] == {}
    with pytest.raises(KeyError):
        registry.compare("demo", 1, 99)


@pytest.mark.asyncio
async def test_endpoint_lists_prompts(registry: Any) -> None:
    """GET /prompt-versions отдаёт промпты с версиями."""
    from src.backend.entrypoints.api.v1.endpoints.admin_prompts import (
        list_prompt_versions,
    )

    items = await list_prompt_versions()
    assert items[0]["name"] == "demo"
    assert items[0]["active_version"] == 2
    assert len(items[0]["versions"]) == 2


@pytest.mark.asyncio
async def test_endpoint_creates_version_with_auto_increment(registry: Any) -> None:
    """POST /prompt-versions без версии → следующий номер."""
    from src.backend.entrypoints.api.v1.endpoints.admin_prompts import (
        PromptVersionCreate,
        create_prompt_version,
    )

    result = await create_prompt_version(
        PromptVersionCreate(name="demo", body="Q: {q}\nA!!")
    )
    assert result["version"] == 3
    assert len(registry.list_versions("demo")) == 3


@pytest.mark.asyncio
async def test_endpoint_duplicate_version_conflicts(registry: Any) -> None:
    """Повторная регистрация той же версии → 409."""
    from src.backend.entrypoints.api.v1.endpoints.admin_prompts import (
        PromptVersionCreate,
        create_prompt_version,
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_prompt_version(
            PromptVersionCreate(name="demo", body="x", version=1)
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_endpoint_activates_version(registry: Any) -> None:
    """POST /prompt-versions/{name}/activate переключает активную версию."""
    from src.backend.entrypoints.api.v1.endpoints.admin_prompts import (
        PromptActivate,
        activate_prompt_version,
    )

    result = await activate_prompt_version("demo", PromptActivate(version=1))
    assert result["active"] is True
    assert registry.active_version("demo") == 1


@pytest.mark.asyncio
async def test_endpoint_compare_missing_version_404(registry: Any) -> None:
    """Сравнение несуществующей версии → 404."""
    from src.backend.entrypoints.api.v1.endpoints.admin_prompts import (
        compare_prompt_versions,
    )

    with pytest.raises(HTTPException) as exc_info:
        await compare_prompt_versions("demo", a=1, b=99)
    assert exc_info.value.status_code == 404
