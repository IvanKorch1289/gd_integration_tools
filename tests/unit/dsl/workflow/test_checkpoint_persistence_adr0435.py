"""ADR-0435 — персистентность явных checkpoint'ов workflow.

Контекст
--------
Activity ``workflow.checkpoint.put`` была best-effort: без хранилища
возвращала ``persisted=False``, а компилятор — warning. Теперь checkpoint
сохраняется в снимок инстанса workflow'а
(:meth:`InstanceStore.update_snapshot`), а отсутствие workflow'а/ошибка БД
возвращаются явным ``persisted=False`` с причиной (ADR-0429: не «тихий
успех»).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.backend.dsl.workflow.compiler.activity_bridge import (
    WORKFLOW_CHECKPOINT_PUT_ACTIVITY,
)

pytestmark = pytest.mark.unit


class _FakeStore:
    """Заглушка state store."""

    def __init__(self, *, saved: bool = True) -> None:
        self.saved = saved
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    async def update_snapshot(self, workflow_id: Any, snapshot: dict[str, Any]) -> bool:
        """Сохранить снимок."""
        self.calls.append((workflow_id, snapshot))
        return self.saved


@pytest.mark.asyncio
async def test_checkpoint_persisted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Checkpoint сохраняется в снимок инстанса."""
    from src.backend.dsl.workflow.compiler import activity_bridge as bridge

    store = _FakeStore(saved=True)
    monkeypatch.setattr(
        bridge,
        "_workflow_checkpoint_put_activity",
        bridge._workflow_checkpoint_put_activity,
    )
    monkeypatch.setattr(
        "src.backend.core.di.providers.workflow.get_workflow_state_store_provider",
        lambda: store,
    )

    workflow_id = uuid4()
    result = await bridge._workflow_checkpoint_put_activity(
        {
            "checkpoint_id": "cp-1",
            "workflow_id": str(workflow_id),
            "snapshot": {"cursor": 3},
        }
    )

    assert result["persisted"] is True
    assert result["reason"] is None
    assert store.calls[0][0] == workflow_id
    assert store.calls[0][1] == {"cursor": 3}


@pytest.mark.asyncio
async def test_checkpoint_without_workflow_id() -> None:
    """Без workflow_id сохранять некуда → явный отказ."""
    from src.backend.dsl.workflow.compiler import activity_bridge as bridge

    result = await bridge._workflow_checkpoint_put_activity(
        {"checkpoint_id": "cp-1", "snapshot": {}}
    )

    assert result["persisted"] is False
    assert "workflow_id" in str(result["reason"])


@pytest.mark.asyncio
async def test_checkpoint_instance_not_found() -> None:
    """Инстанс не найден → persisted=False с причиной."""
    from src.backend.dsl.workflow.compiler import activity_bridge as bridge

    store = _FakeStore(saved=False)
    import src.backend.core.di.providers.workflow as workflow_provider

    original = workflow_provider.get_workflow_state_store_provider
    workflow_provider.get_workflow_state_store_provider = lambda: store  # type: ignore[assignment]
    try:
        result = await bridge._workflow_checkpoint_put_activity(
            {"checkpoint_id": "cp-1", "workflow_id": str(uuid4()), "snapshot": {}}
        )
    finally:
        workflow_provider.get_workflow_state_store_provider = original  # type: ignore[assignment]

    assert result["persisted"] is False
    assert "не найден" in str(result["reason"])


def test_checkpoint_activity_is_registered() -> None:
    """Activity зарегистрирована в мосте (иначе Worker её не знает)."""
    from src.backend.dsl.workflow.compiler.activity_bridge import (
        INTERNAL_ACTIVITY_NAMES,
    )

    assert WORKFLOW_CHECKPOINT_PUT_ACTIVITY in INTERNAL_ACTIVITY_NAMES
