"""Regression-тесты B-10 fix (cycle 33): WorkflowRegistry ↔ temporal_backend.replay.

Проверяют:
* :class:`WorkflowRegistry` singleton — register/get/all/clear/``__contains__``;
* валидация ``@workflow.defn`` decorator marker'а + fallback ``_is_workflow``;
* двойная регистрация → ``ValueError``;
* ``TemporalWorkflowBackend.replay`` использует registry, а не ``cast(str → type)``;
  воспроизводит ``WorkflowNonDeterminismError`` если зарегистрированный
  workflow не совпадает с историей;
* unknown ``workflow_name`` → ``KeyError`` (раньше — silent cast);
* ``workflow_registry.all()`` используется для empty-name replay.

B-15 fix (cycle 37): тесты на ``_bootstrap_workflow_registry`` и
``_decorator_attr`` удалены вместе с самим AST-сканером —
``compile_workflow()`` теперь регистрирует класс в
``workflow_registry`` напрямую (см. emitter.py).

temporalio SDK опционален (extra dep ``uv sync --extra workflow``); если
не установлен — replay-тесты скипаются, registry-тесты идут в полном
объёме.
"""


from __future__ import annotations

import importlib
from typing import Any

import pytest

from src.backend.core import workflow_registry as registry_module
from src.backend.core.workflow_registry import workflow_registry

# --- WorkflowRegistry unit-тесты -----------------------------------------


class _DefnMarker:
    """Аналог ``temporalio.workflow._WorkflowDefinition``."""

    def __init__(self, *, name: str) -> None:
        self.name = name


class _RealWorkflowStub:
    """Имитация класса, задекорированного настоящим ``@workflow.defn``.

    temporalio.workflow.defn проставляет на класс marker
    ``__temporal_workflow_definition__`` (объект ``_WorkflowDefinition``).
    Мы проставляем минимальный stub с атрибутом ``name``.
    """

    __temporal_workflow_definition__ = _DefnMarker(name="RealWorkflowStub")


class _FallbackWorkflowStub:
    """Test-fixture, помеченная только fallback-флагом ``_is_workflow``."""

    _is_workflow = True


class _NotAWorkflow:
    """Класс, не помеченный ни одним из маркеров."""


@pytest.fixture(autouse=True)
def _isolate_registry() -> Any:
    """Каждый тест начинает с пустого workflow_registry."""
    workflow_registry.clear()
    yield
    workflow_registry.clear()


def test_register_accepts_real_workflow_marker() -> None:
    """Класс с ``__temporal_workflow_definition__`` принимается."""
    cls = _RealWorkflowStub
    registered = workflow_registry.register(cls)
    assert registered is cls
    assert workflow_registry.get("RealWorkflowStub") is cls
    assert "RealWorkflowStub" in workflow_registry
    assert len(workflow_registry) == 1


def test_register_accepts_fallback_marker() -> None:
    """Test-fixtures с ``_is_workflow=True`` принимаются."""
    cls = _FallbackWorkflowStub
    workflow_registry.register(cls)
    assert workflow_registry.get("_FallbackWorkflowStub") is cls


def test_register_rejects_plain_class() -> None:
    """Класс без маркера → ``TypeError``."""
    with pytest.raises(TypeError, match="не помечен @workflow.defn"):
        workflow_registry.register(_NotAWorkflow)


def test_register_rejects_instance() -> None:
    """Регистрация инстанса (не класса) → ``TypeError``."""
    with pytest.raises(TypeError, match="не помечен @workflow.defn"):
        workflow_registry.register(_RealWorkflowStub())  # type: ignore[arg-type]


def test_register_rejects_duplicate_name() -> None:
    """Двойная регистрация под тем же именем → ``ValueError``."""
    workflow_registry.register(_RealWorkflowStub)
    with pytest.raises(ValueError, match="уже зарегистрирован"):
        workflow_registry.register(_RealWorkflowStub)


def test_get_returns_none_for_unknown() -> None:
    assert workflow_registry.get("Unknown") is None
    assert "Unknown" not in workflow_registry


def test_all_returns_sorted_copy() -> None:
    """``all()`` возвращает детерминированно отсортированную копию."""
    a = type("A", (), {"_is_workflow": True})
    b = type("B", (), {"_is_workflow": True})
    c = type("C", (), {"_is_workflow": True})

    workflow_registry.register(b)
    workflow_registry.register(c)
    workflow_registry.register(a)

    result = workflow_registry.all()
    assert [cls.__name__ for cls in result] == ["A", "B", "C"]
    assert workflow_registry.names() == ["A", "B", "C"]

    # Модификация копии не должна влиять на реестр.
    result.clear()
    assert len(workflow_registry) == 3


def test_clear_resets_registry() -> None:
    workflow_registry.register(_RealWorkflowStub)
    assert len(workflow_registry) == 1
    workflow_registry.clear()
    assert len(workflow_registry) == 0
    assert workflow_registry.get("RealWorkflowStub") is None


def test_workflow_registry_singleton_is_module_level() -> None:
    """Singleton ``workflow_registry`` живёт на уровне модуля.

    Импортируется одинаковый объект в любом месте проекта. После
    ``importlib.reload`` модуль пересоздаёт singleton — это ожидаемо
    (stateful module global), проверяем что pre-reload ссылка остаётся
    живой (не заменяется неявно).
    """
    import src.backend.core.workflow_registry as other_import

    # До reload — один и тот же объект.
    pre_reload_id = id(workflow_registry)
    assert other_import.workflow_registry is workflow_registry

    # После reload — модуль пересоздаёт singleton (новый id).
    importlib.reload(registry_module)
    assert id(registry_module.workflow_registry) != pre_reload_id


def test_register_uses_decorator_name_when_present() -> None:
    """Если marker ``__temporal_workflow_definition__`` имеет ``name`` —
    registry использует его, а не ``cls.__name__``.
    """

    class _Renamed:
        __temporal_workflow_definition__ = _DefnMarker(name="ExplicitName")

    workflow_registry.register(_Renamed)
    assert workflow_registry.get("ExplicitName") is _Renamed
    assert workflow_registry.get("_Renamed") is None


# --- TemporalWorkflowBackend.replay() ↔ WorkflowRegistry --------------------


def _has_temporalio() -> bool:
    try:
        import temporalio

        return True
    except ImportError:
        return False


_temporalio_required = pytest.mark.skipif(
    not _has_temporalio(),
    reason="temporalio SDK not installed (install via `uv sync --extra workflow`)",
)


class _RecordingReplayer:
    """Stand-in для :class:`temporalio.worker.Replayer`, записывает вызовы.

    Используется через ``monkeypatch.setattr`` — подменяем модуль-импорт
    в ``temporal_backend`` так, чтобы ``from temporalio.worker import Replayer``
    вернул нашу заглушку. Это network-boundary mock: подменяем SDK-класс,
    а не сам метод ``replay()`` под тестом.
    """

    instances: list[_RecordingReplayer] = []

    def __init__(self, *, workflows: list[type]) -> None:
        self.workflows = list(workflows)
        self.replay_calls: list[bytes] = []
        _RecordingReplayer.instances.append(self)

    async def replay_workflow(self, history: Any) -> None:
        # Имитируем temporalio поведение: если в history указан workflow
        # type-name, которого нет в ``workflows``, temporalio бросит
        # ``WorkflowNonDeterminismError``. Симулируем это явно.
        from temporalio.client import WorkflowHistory

        if isinstance(history, WorkflowHistory):
            wf_name = getattr(history, "workflow_id", None)
            registered = {cls.__name__ for cls in self.workflows}
            if wf_name and wf_name not in registered:
                from temporalio.exceptions import WorkflowNonDeterminismError

                raise WorkflowNonDeterminismError(
                    f"simulated: workflow '{wf_name}' not in {sorted(registered)}",
                )
        self.replay_calls.append(b"ok")


@pytest.fixture
def patch_replayer(monkeypatch: pytest.MonkeyPatch) -> type[_RecordingReplayer]:
    """Подменить ``temporalio.worker.Replayer`` на ``_RecordingReplayer``."""
    from temporalio import worker as worker_mod

    _RecordingReplayer.instances.clear()
    monkeypatch.setattr(worker_mod, "Replayer", _RecordingReplayer)
    return _RecordingReplayer


@pytest.fixture
def backend() -> Any:
    """TemporalWorkflowBackend с фейковым client (нам нужен только
    метод ``replay``, client игнорируется).
    """
    from src.backend.infrastructure.workflow.temporal_backend import (
        TemporalWorkflowBackend,
    )

    fake_client = object()
    return TemporalWorkflowBackend(
        client=fake_client, default_task_queue="t1",  # type: ignore[abstract]
    )


@_temporalio_required
@pytest.mark.asyncio
async def test_replay_uses_registry_for_named_workflow(
    backend: Any,
    patch_replayer: type[_RecordingReplayer],
) -> None:
    """B-10 fix: replay(workflow_name="X") → Replayer([registry.get("X")])."""
    workflow_registry.register(_RealWorkflowStub)

    history = (
        b'{"events":[],"workflow_id":"RealWorkflowStub",'
        b'"workflow_type":{"name":"RealWorkflowStub"},"task_queue":"t1"}'
    )
    await backend.replay(workflow_name="RealWorkflowStub", history=history)

    assert len(patch_replayer.instances) == 1
    replayer = patch_replayer.instances[0]
    assert replayer.workflows == [_RealWorkflowStub]
    # Нет silent cast: Replayer получил класс, а не строку.
    assert all(isinstance(w, type) for w in replayer.workflows)


@_temporalio_required
@pytest.mark.asyncio
async def test_replay_unknown_name_raises_keyerror(
    backend: Any,
    patch_replayer: type[_RecordingReplayer],
) -> None:
    """B-10 fix: unknown workflow_name → ``KeyError`` (раньше — silent cast)."""
    history = b"{}"
    with pytest.raises(KeyError, match="не зарегистрирован в WorkflowRegistry"):
        await backend.replay(workflow_name="GhostWorkflow", history=history)
    # Replayer не должен был создаваться.
    assert patch_replayer.instances == []


@_temporalio_required
@pytest.mark.asyncio
async def test_replay_empty_name_uses_all_registered(
    backend: Any,
    patch_replayer: type[_RecordingReplayer],
) -> None:
    """``workflow_name=""`` → broadcast на все зарегистрированные классы."""
    workflow_registry.register(_RealWorkflowStub)
    workflow_registry.register(_FallbackWorkflowStub)

    history = b"{}"
    await backend.replay(workflow_name="", history=history)

    assert len(patch_replayer.instances) == 1
    replayer = patch_replayer.instances[0]
    assert set(replayer.workflows) == {_RealWorkflowStub, _FallbackWorkflowStub}


@_temporalio_required
@pytest.mark.asyncio
async def test_replay_detects_workflow_non_determinism(
    backend: Any,
    patch_replayer: type[_RecordingReplayer],
) -> None:
    """Если workflow в history не совпадает с зарегистрированным —
    Replayer бросает ``WorkflowNonDeterminismError`` (наш stub это эмулирует).
    """
    workflow_registry.register(_RealWorkflowStub)
    history = (
        b'{"events":[],"workflow_id":"OtherWorkflow",'
        b'"workflow_type":{"name":"OtherWorkflow"},"task_queue":"t1"}'
    )
    from temporalio.exceptions import WorkflowNonDeterminismError

    with pytest.raises(WorkflowNonDeterminismError, match="OtherWorkflow"):
        await backend.replay(workflow_name="RealWorkflowStub", history=history)


@_temporalio_required
@pytest.mark.asyncio
async def test_replay_does_not_use_str_cast(
    backend: Any,
    patch_replayer: type[_RecordingReplayer],
) -> None:
    """B-10 fix: явно проверяем что ``workflows=[<str>]`` НЕ передаётся в Replayer.

    Старый код делал ``cast("type", workflow_name)`` и передавал строку.
    Если бы старый код остался — ``replayer.workflows == ["X"]`` (строка).
    Сейчас — ``replayer.workflows == [<class>]``.
    """
    workflow_registry.register(_RealWorkflowStub)

    history = (
        b'{"events":[],"workflow_id":"RealWorkflowStub",'
        b'"workflow_type":{"name":"RealWorkflowStub"},"task_queue":"t1"}'
    )
    await backend.replay(workflow_name="RealWorkflowStub", history=history)

    replayer = patch_replayer.instances[0]
    # Если бы остался cast — workflows был бы ["RealWorkflowStub"].
    assert replayer.workflows != ["RealWorkflowStub"]
    assert all(isinstance(w, type) for w in replayer.workflows)
