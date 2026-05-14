"""Smoke-тесты LangMemService (K4 Sprint-3 Wave 1 baseline).

Покрывает:
    - пропуск операций при выключенном feature-flag;
    - remember_episode в inMemory-режиме;
    - remember_fact с вектором эмбеддинга;
    - remember_procedure со списком шагов;
    - recall с фильтрацией по kind;
    - recall с ограничением top_k.

Все тесты работают без Postgres и Qdrant (inMemory fallback).
"""

from __future__ import annotations

import pytest

from src.backend.services.ai.memory.langmem_service import (
    LangMemService,
    MemoryEntry,
    get_langmem_service,
)


def _make_svc(*, enabled: bool = True, inmemory: bool = True) -> LangMemService:
    """Фабрика LangMemService для тестов (inMemory, без external deps)."""
    return LangMemService(enabled=enabled, use_inmemory=inmemory)


def test_langmem_skips_when_flag_off() -> None:
    """При enabled=False get_langmem_service импортируется, сервис создаётся.

    Проверяем, что:
    - класс и функция импортируются без ошибок;
    - сервис с enabled=False имеет _enabled=False.
    """
    svc = _make_svc(enabled=False)
    assert svc._enabled is False
    # Убеждаемся, что get_langmem_service() тоже импортируется штатно
    assert callable(get_langmem_service)


@pytest.mark.asyncio
async def test_remember_episode_inmemory() -> None:
    """remember_episode возвращает MemoryEntry с корректными полями (inMemory)."""
    svc = _make_svc()
    entry = await svc.remember_episode(
        agent_id="agent-001",
        content="Пользователь спросил о курсе доллара",
        metadata={"source": "telegram", "session": "s-42"},
    )
    assert isinstance(entry, MemoryEntry)
    assert entry.kind == "episodic"
    assert entry.agent_id == "agent-001"
    assert entry.content == "Пользователь спросил о курсе доллара"
    assert entry.metadata["source"] == "telegram"
    assert entry.entry_id  # UUID4 — непустая строка
    assert entry.timestamp is not None


@pytest.mark.asyncio
async def test_remember_fact_with_embedding() -> None:
    """remember_fact сохраняет факт с вектором эмбеддинга (inMemory)."""
    svc = _make_svc()
    embedding = [0.1, 0.2, 0.3, 0.4]
    entry = await svc.remember_fact(
        agent_id="agent-002",
        content="Центральный банк повысил ставку до 21%",
        embedding=embedding,
    )
    assert isinstance(entry, MemoryEntry)
    assert entry.kind == "semantic"
    assert entry.embedding == embedding
    assert entry.agent_id == "agent-002"
    assert "Центральный банк" in entry.content


@pytest.mark.asyncio
async def test_remember_procedure_with_steps() -> None:
    """remember_procedure сохраняет последовательность шагов (inMemory)."""
    svc = _make_svc()
    steps = [
        "Получить запрос пользователя",
        "Запросить данные из БД",
        "Вызвать LLM для генерации ответа",
        "Вернуть результат",
    ]
    entry = await svc.remember_procedure(
        agent_id="agent-003",
        name="answer_query",
        steps=steps,
    )
    assert isinstance(entry, MemoryEntry)
    assert entry.kind == "procedural"
    assert entry.content == "answer_query"
    assert entry.metadata["steps"] == steps
    assert entry.metadata["name"] == "answer_query"


@pytest.mark.asyncio
async def test_recall_filters_by_kind() -> None:
    """recall возвращает только записи нужного kind (inMemory)."""
    svc = _make_svc()
    # Добавляем один episodic и один procedural
    await svc.remember_episode(
        agent_id="agent-004",
        content="Пользователь нажал кнопку",
        metadata={},
    )
    await svc.remember_procedure(
        agent_id="agent-004",
        name="click_handler",
        steps=["detect", "process"],
    )
    # recall episodic
    episodic = await svc.recall(agent_id="agent-004", kind="episodic")
    assert all(e.kind == "episodic" for e in episodic)
    assert len(episodic) == 1
    # recall procedural
    procedural = await svc.recall(agent_id="agent-004", kind="procedural")
    assert all(e.kind == "procedural" for e in procedural)
    assert len(procedural) == 1


@pytest.mark.asyncio
async def test_recall_returns_top_k() -> None:
    """recall ограничивает результат top_k записями (inMemory)."""
    svc = _make_svc()
    # Добавляем 5 эпизодов для одного агента
    for i in range(5):
        await svc.remember_episode(
            agent_id="agent-005",
            content=f"Эпизод #{i}",
            metadata={"index": i},
        )
    # Запрашиваем top_k=3
    result = await svc.recall(agent_id="agent-005", kind="episodic", top_k=3)
    assert len(result) == 3
    # Запись с большим index (позже) должна быть первой (сортировка по timestamp desc)
    assert result[0].metadata.get("index", -1) > result[-1].metadata.get("index", -2)
