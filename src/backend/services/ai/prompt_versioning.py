"""Prompt versioning service (Sprint 9 K4 W4 — GAP-AI-3.2).

Контракт для Prompt Lab UI:

* :class:`PromptVersion` — версия prompt'а (name, version, body, model,
  parameters, metrics).
* :class:`PromptVersionStore` — backend Protocol (LangFuse / SQLite / in-memory).
* :class:`InMemoryPromptVersionStore` — для unit-тестов и dev_light.
* :class:`PromptVersionService` — high-level orchestrator: create, list,
  set_active, A/B compare, rollback.

LangFuse 3.x adapter — отдельный модуль (S10 staging).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

__all__ = (
    "InMemoryPromptVersionStore",
    "PromptComparison",
    "PromptVersion",
    "PromptVersionService",
    "PromptVersionStore",
)


@dataclass(slots=True)
class PromptVersion:
    """Версия prompt'а.

    Attributes:
        name: имя prompt'а (``credit_decision_v2``).
        version: монотонный int (1, 2, 3, ...).
        body: текст prompt'а.
        model: целевой LLM-model (``gpt-4o-mini``).
        parameters: temperature, top_p, max_tokens, и т.п.
        is_active: текущая активная версия для production.
        metrics: ``{accuracy, p95_latency, cost_usd, ...}`` накопленные.
        created_at: timestamp создания.
        created_by: автор (для audit).
    """

    name: str
    version: int
    body: str
    model: str = "gpt-4o-mini"
    parameters: dict[str, Any] = field(default_factory=dict)
    is_active: bool = False
    metrics: dict[str, float] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "body": self.body,
            "model": self.model,
            "parameters": self.parameters,
            "is_active": self.is_active,
            "metrics": self.metrics,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
        }


@dataclass(slots=True)
class PromptComparison:
    """A/B comparison двух версий prompt'а."""

    name: str
    a: PromptVersion
    b: PromptVersion
    metric_diffs: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "a": self.a.to_dict(),
            "b": self.b.to_dict(),
            "metric_diffs": self.metric_diffs,
        }


@runtime_checkable
class PromptVersionStore(Protocol):
    """Backend для хранения prompt versions."""

    async def create(self, version: PromptVersion) -> PromptVersion:
        ...

    async def get(self, name: str, version: int) -> PromptVersion | None:
        ...

    async def list_versions(self, name: str) -> list[PromptVersion]:
        ...

    async def list_names(self) -> list[str]:
        ...

    async def set_active(self, name: str, version: int) -> PromptVersion:
        ...

    async def update_metrics(
        self, name: str, version: int, metrics: dict[str, float]
    ) -> PromptVersion:
        ...


class InMemoryPromptVersionStore:
    """In-memory store для unit-тестов и dev_light."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, int], PromptVersion] = {}
        self._lock = asyncio.Lock()

    async def create(self, version: PromptVersion) -> PromptVersion:
        async with self._lock:
            key = (version.name, version.version)
            if key in self._store:
                raise ValueError(
                    f"Prompt version {version.name}:v{version.version} already exists"
                )
            self._store[key] = version
            return version

    async def get(self, name: str, version: int) -> PromptVersion | None:
        async with self._lock:
            return self._store.get((name, version))

    async def list_versions(self, name: str) -> list[PromptVersion]:
        async with self._lock:
            items = [
                v for (n, _), v in self._store.items() if n == name
            ]
        return sorted(items, key=lambda v: v.version)

    async def list_names(self) -> list[str]:
        async with self._lock:
            return sorted({name for name, _ in self._store.keys()})

    async def set_active(self, name: str, version: int) -> PromptVersion:
        async with self._lock:
            key = (name, version)
            if key not in self._store:
                raise KeyError(f"Prompt {name}:v{version} not found")
            # Deactivate other versions
            for (n, _), pv in self._store.items():
                if n == name:
                    pv.is_active = False
            self._store[key].is_active = True
            return self._store[key]

    async def update_metrics(
        self, name: str, version: int, metrics: dict[str, float]
    ) -> PromptVersion:
        async with self._lock:
            key = (name, version)
            if key not in self._store:
                raise KeyError(f"Prompt {name}:v{version} not found")
            self._store[key].metrics.update(metrics)
            return self._store[key]


class PromptVersionService:
    """High-level orchestrator над :class:`PromptVersionStore`.

    Args:
        store: backend store.
    """

    def __init__(self, *, store: PromptVersionStore) -> None:
        self._store = store

    async def create_version(
        self,
        *,
        name: str,
        body: str,
        model: str = "gpt-4o-mini",
        parameters: dict[str, Any] | None = None,
        created_by: str | None = None,
    ) -> PromptVersion:
        """Создать новую версию (auto-bump version number)."""
        existing = await self._store.list_versions(name)
        next_version = max((v.version for v in existing), default=0) + 1
        return await self._store.create(
            PromptVersion(
                name=name,
                version=next_version,
                body=body,
                model=model,
                parameters=parameters or {},
                created_by=created_by,
            )
        )

    async def list_versions(self, name: str) -> list[PromptVersion]:
        return await self._store.list_versions(name)

    async def list_names(self) -> list[str]:
        return await self._store.list_names()

    async def get_active(self, name: str) -> PromptVersion | None:
        versions = await self._store.list_versions(name)
        active = [v for v in versions if v.is_active]
        return active[0] if active else None

    async def set_active(self, name: str, version: int) -> PromptVersion:
        return await self._store.set_active(name, version)

    async def rollback(self, name: str) -> PromptVersion | None:
        """Откатиться к предыдущей версии."""
        versions = await self._store.list_versions(name)
        if len(versions) < 2:
            return None
        active = next((v for v in versions if v.is_active), versions[-1])
        prev = [v for v in versions if v.version < active.version]
        if not prev:
            return None
        target = prev[-1]
        return await self._store.set_active(name, target.version)

    async def compare(
        self, *, name: str, version_a: int, version_b: int
    ) -> PromptComparison:
        """A/B сравнение метрик."""
        a = await self._store.get(name, version_a)
        b = await self._store.get(name, version_b)
        if a is None or b is None:
            raise KeyError(
                f"Prompt {name}:v{version_a} or v{version_b} not found"
            )
        keys = set(a.metrics.keys()) | set(b.metrics.keys())
        diffs = {
            k: b.metrics.get(k, 0.0) - a.metrics.get(k, 0.0) for k in keys
        }
        return PromptComparison(name=name, a=a, b=b, metric_diffs=diffs)

    async def update_metrics(
        self, *, name: str, version: int, metrics: dict[str, float]
    ) -> PromptVersion:
        return await self._store.update_metrics(name, version, metrics)
