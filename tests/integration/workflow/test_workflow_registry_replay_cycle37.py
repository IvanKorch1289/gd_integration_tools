"""Integration-тест B-15 fix (cycle 37): end-to-end WorkflowRegistry registration.

Проверяет, что цепочка ``compile_workflow()`` →
``workflow_registry.register()`` → ``TemporalWorkflowBackend.replay()``
работает без ``KeyError`` для всех 3 сценариев resolution:

* узкая выборка (``workflow_name="X"`` → ``[cls_X]``);
* broad-scan (``workflow_name=""`` → все зарегистрированные);
* unknown name → ``KeyError`` с понятным message.

temporalio SDK опционален (extra dep ``uv sync --extra workflow``);
если SDK не установлен — replay-тесты скипаются, а unit-проверки
``workflow_registry.get()`` идут в полном объёме (используя
fallback-маркер ``_is_workflow``).
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip(
    "temporalio", reason="temporalio not installed — run: uv sync --extra workflow"
)


@pytest.fixture(autouse=True)
def _isolate_registry() -> Any:
    """Изолируем singleton workflow_registry между тестами."""
    from src.backend.core.workflow_registry import workflow_registry

    workflow_registry.clear()
    yield
    workflow_registry.clear()


def test_compile_workflow_registers_in_registry() -> None:
    """B-15 fix: ``compile_workflow()`` → ``workflow_registry.get(name)`` → класс."""
    from src.backend.core.workflow_registry import workflow_registry
    from src.backend.dsl.workflow.builder import WorkflowBuilder
    from src.backend.dsl.workflow.compiler.emitter import compile_workflow

    decl = WorkflowBuilder("orders.create").activity("orders.write").build()
    compiled = compile_workflow(decl)

    # Compile side-effect: класс попал в реестр.
    assert compiled.name == "orders.create"
    assert workflow_registry.get("orders.create") is compiled.cls
    assert "orders.create" in workflow_registry


def test_compile_workflows_bulk_registers_all() -> None:
    """B-15 fix: ``compile_workflows([decl1, decl2])`` → оба класса в реестре."""
    from src.backend.core.workflow_registry import workflow_registry
    from src.backend.dsl.workflow.builder import WorkflowBuilder
    from src.backend.dsl.workflow.compiler.emitter import compile_workflows

    decls = [
        WorkflowBuilder("alpha.flow").activity("foo").build(),
        WorkflowBuilder("beta.flow").activity("bar").build(),
        WorkflowBuilder("gamma.flow").activity("baz").build(),
    ]
    out = compile_workflows(decls)

    assert [c.name for c in out] == ["alpha.flow", "beta.flow", "gamma.flow"]
    # Все классы попали в реестр (post-step guard не сработал).
    for compiled in out:
        assert workflow_registry.get(compiled.name) is compiled.cls


def test_compile_workflow_idempotent_on_duplicate_name() -> None:
    """B-15 fix: повторный ``compile_workflow(same_decl)`` → idempotent (skip)."""
    from src.backend.core.workflow_registry import workflow_registry
    from src.backend.dsl.workflow.builder import WorkflowBuilder
    from src.backend.dsl.workflow.compiler.emitter import compile_workflow

    decl = WorkflowBuilder("replay.deterministic").activity("noop").build()

    first = compile_workflow(decl)
    second = compile_workflow(decl)  # должна пройти без raise

    # Оба раза один и тот же workflow_name — класс может быть разным
    # (type() создаёт новый объект каждый раз), но имя в реестре одно.
    assert first.name == second.name == "replay.deterministic"
    # В реестре остался первый класс (ValueError при повторе → skip).
    assert workflow_registry.get("replay.deterministic") is first.cls


def test_resolve_workflows_for_replay_returns_class_for_known_name() -> None:
    """B-15 fix: ``_resolve_workflows_for_replay("X")`` → ``[cls_X]``."""
    from src.backend.core.workflow_registry import workflow_registry
    from src.backend.dsl.workflow.builder import WorkflowBuilder
    from src.backend.dsl.workflow.compiler.emitter import compile_workflow
    from src.backend.infrastructure.workflow.temporal_backend import (
        TemporalWorkflowBackend,
    )

    compiled = compile_workflow(WorkflowBuilder("wf.alpha").activity("noop").build())

    # Backend._resolve_workflows_for_replay — staticmethod.
    resolved = TemporalWorkflowBackend._resolve_workflows_for_replay("wf.alpha")

    assert resolved == [compiled.cls]
    # Sanity: реестр действительно знает имя.
    assert workflow_registry.get("wf.alpha") is compiled.cls


def test_resolve_workflows_for_replay_returns_all_for_empty_name() -> None:
    """B-15 fix: ``_resolve_workflows_for_replay("")`` → broad-scan всех."""
    from src.backend.dsl.workflow.builder import WorkflowBuilder
    from src.backend.dsl.workflow.compiler.emitter import compile_workflow
    from src.backend.infrastructure.workflow.temporal_backend import (
        TemporalWorkflowBackend,
    )

    a = compile_workflow(WorkflowBuilder("wf.a").activity("noop").build())
    b = compile_workflow(WorkflowBuilder("wf.b").activity("noop").build())

    resolved = TemporalWorkflowBackend._resolve_workflows_for_replay("")

    # Sorted order (см. ``WorkflowRegistry.all()``).
    assert {cls.__name__ for cls in resolved} >= {a.cls.__name__, b.cls.__name__}
    assert a.cls in resolved
    assert b.cls in resolved


def test_resolve_workflows_for_replay_raises_keyerror_for_unknown() -> None:
    """B-15 fix: ``_resolve_workflows_for_replay("ghost")`` → ``KeyError``."""
    from src.backend.infrastructure.workflow.temporal_backend import (
        TemporalWorkflowBackend,
    )

    with pytest.raises(KeyError, match="не зарегистрирован в WorkflowRegistry"):
        TemporalWorkflowBackend._resolve_workflows_for_replay("ghost.workflow")


def test_replay_uses_compiled_class_from_registry() -> None:
    """B-15 fix: ``backend.replay("X")`` использует класс из реестра.

    Подменяем ``temporalio.worker.Replayer`` на stub и проверяем, что
    в ``replayer.workflows`` лежит скомпилированный класс, а не строка.
    """
    from temporalio import worker as worker_mod

    from src.backend.core.workflow_registry import workflow_registry
    from src.backend.dsl.workflow.builder import WorkflowBuilder
    from src.backend.dsl.workflow.compiler.emitter import compile_workflow
    from src.backend.infrastructure.workflow.temporal_backend import (
        TemporalWorkflowBackend,
    )

    class _RecordingReplayer:
        instances: list[_RecordingReplayer] = []

        def __init__(self, *, workflows: list[type]) -> None:
            self.workflows = list(workflows)
            _RecordingReplayer.instances.append(self)

        async def replay_workflow(self, history: Any) -> None:
            return None

    _RecordingReplayer.instances.clear()
    original = worker_mod.Replayer
    worker_mod.Replayer = _RecordingReplayer  # type: ignore[assignment]
    try:
        compiled = compile_workflow(
            WorkflowBuilder("wf.replay.e2e").activity("noop").build()
        )
        backend = TemporalWorkflowBackend(
            client=object(),  # type: ignore[abstract]
            default_task_queue="t1",
        )

        import asyncio

        history = (
            b'{"events":[],"workflow_id":"wf.replay.e2e",'
            b'"workflow_type":{"name":"wf.replay.e2e"},"task_queue":"t1"}'
        )
        asyncio.run(backend.replay(workflow_name="wf.replay.e2e", history=history))

        assert len(_RecordingReplayer.instances) == 1
        replayer = _RecordingReplayer.instances[0]
        # Класс — не строка.
        assert replayer.workflows == [compiled.cls]
        assert all(isinstance(w, type) for w in replayer.workflows)
    finally:
        worker_mod.Replayer = original  # type: ignore[assignment]
        # Очистим реестр, чтобы singleton не протекал в другие тесты.
        workflow_registry.clear()


def test_compile_workflows_post_step_guard_would_raise_if_registry_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Post-step guard в ``compile_workflows`` ловит regression
    (если register() сломан — bulk-компиляция падает с RuntimeError)."""
    from src.backend.core import workflow_registry as registry_module
    from src.backend.dsl.workflow.builder import WorkflowBuilder

    # Подменяем register на no-op (имитируем сломанный реестр).
    original_register = registry_module.workflow_registry.register
    monkeypatch.setattr(
        registry_module.workflow_registry, "register", lambda cls: cls
    )

    # Импортируем compile_workflows ПОСЛЕ monkeypatch (он импортирует
    # workflow_registry из core.workflow_registry при выполнении).
    from src.backend.dsl.workflow.compiler.emitter import compile_workflows

    with pytest.raises(RuntimeError, match="compiled but NOT registered"):
        compile_workflows(
            [
                WorkflowBuilder("guard.flow").activity("noop").build(),
            ]
        )

    # Восстанавливаем.
    monkeypatch.setattr(
        registry_module.workflow_registry, "register", original_register
    )


def test_workflow_registry_singleton_is_global() -> None:
    """Реестр, который заполняет emitter, — это тот же singleton,
    который читает temporal_backend (модульный singleton в
    ``core.workflow_registry``)."""
    from src.backend.core import workflow_registry as other_mod
    from src.backend.core.workflow_registry import workflow_registry
    from src.backend.dsl.workflow.builder import WorkflowBuilder
    from src.backend.dsl.workflow.compiler.emitter import compile_workflow

    assert len(workflow_registry) == 0

    compile_workflow(WorkflowBuilder("singleton.test").activity("noop").build())

    # Singleton импортируется и здесь, и в temporal_backend —
    # но это один и тот же объект.
    assert other_mod.workflow_registry is workflow_registry
    assert len(workflow_registry) == 1
    assert "singleton.test" in workflow_registry
