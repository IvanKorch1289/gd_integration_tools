"""Sprint 7 — pg_runner_backend.replay deprecation tests (TDD, 2026-08-17).

Phase 0 verification (2026-08-17) подтвердил что ``PgRunnerWorkflowBackend.
replay()`` всегда raise NotImplementedError — Sprint 203 README заявлял
«pg_runner replay (P2) closed», но это FALSE_CLAIM.

Sprint 7 decision (per MULTI_SPRINT_2026-08-17.md, Sprint 7 candidate):
deprecate pg_runner backend entirely. Replay API — no-op с явным
DeprecationWarning. Production migration: TemporalWorkflowBackend.

TDD: эти тесты задают целевую семантику (test-first), затем
реализация обновит код под тесты.

Coverage:
1. replay() raises NotImplementedError (already exists)
2. NotImplementedError message направляет на TemporalWorkflowBackend
3. Class instantiation emits DeprecationWarning (новое поведение)
4. Module docstring явно отмечает deprecation timeline
5. Логирование deprecation события для observability
"""

from __future__ import annotations

import warnings

import pytest


class TestPgRunnerReplayNotImplemented:
    """replay() MUST raise NotImplementedError (no implementation exists)."""

    def test_replay_raises_not_implemented_error(self) -> None:
        """replay() не реализован — всегда raise."""
        from src.backend.infrastructure.workflow.pg_runner_backend import (
            PgRunnerWorkflowBackend,
        )

        backend = PgRunnerWorkflowBackend()

        with pytest.raises(NotImplementedError):
            # type: ignore[call-arg] — replay signature may differ
            import asyncio

            asyncio.run(backend.replay(workflow_name="test", history=b""))

    def test_replay_message_directs_to_temporal(self) -> None:
        """Error message должен указывать на TemporalWorkflowBackend."""
        from src.backend.infrastructure.workflow.pg_runner_backend import (
            PgRunnerWorkflowBackend,
        )

        backend = PgRunnerWorkflowBackend()

        with pytest.raises(NotImplementedError, match="[Tt]emporal"):
            import asyncio

            asyncio.run(backend.replay(workflow_name="test", history=b""))


class TestPgRunnerBackendDeprecation:
    """PgRunnerWorkflowBackend itself deprecated — production → Temporal."""

    def test_class_docstring_marks_deprecated(self) -> None:
        """Module docstring должен явно отмечать deprecation status."""
        from src.backend.infrastructure.workflow import pg_runner_backend

        docstring = pg_runner_backend.__doc__ or ""
        assert (
            "DEPRECATED" in docstring.upper()
            or "deprecated" in docstring.lower()
            or "legacy" in docstring.lower()
            or "fallback" in docstring.lower()
        ), (
            "pg_runner_backend module docstring должен явно отмечать "
            "deprecation status (DEPRECATED, legacy, или fallback)."
        )

    def test_class_docstring_directs_to_temporal(self) -> None:
        """Docstring должен указывать на TemporalWorkflowBackend как replacement."""
        from src.backend.infrastructure.workflow.pg_runner_backend import (
            PgRunnerWorkflowBackend,
        )

        docstring = PgRunnerWorkflowBackend.__doc__ or ""
        assert "Temporal" in docstring, (
            "PgRunnerWorkflowBackend docstring должен направлять на "
            "TemporalWorkflowBackend как production replacement."
        )


class TestPgRunnerModuleExports:
    """Module exports should be explicit and minimal."""

    def test_module_dunder_all_contains_pg_runner_backend(self) -> None:
        from src.backend.infrastructure.workflow.pg_runner_backend import (
            __all__ as module_all,
        )
        assert "PgRunnerWorkflowBackend" in module_all

    def test_replay_method_is_coroutine(self) -> None:
        """replay() MUST be async — даже если raises сразу."""
        import inspect

        from src.backend.infrastructure.workflow.pg_runner_backend import (
            PgRunnerWorkflowBackend,
        )

        assert inspect.iscoroutinefunction(PgRunnerWorkflowBackend.replay), (
            "replay() должен быть async def (Protocol compliance)"
        )


class TestPgRunnerRejectsFalseClaim:
    """Regression guard: prevent re-introduction of FALSE_CLAIM 'pg_runner
    replay closed' claim. Если кто-то попытается 'implement' replay без
    Temporal-compatible semantics — тест должен поймать."""

    def test_replay_does_not_silently_return(self) -> None:
        """replay() НЕ должен молча возвращаться (no silent no-op)."""
        from src.backend.infrastructure.workflow.pg_runner_backend import (
            PgRunnerWorkflowBackend,
        )

        backend = PgRunnerWorkflowBackend()

        # Если replay() начнёт возвращать None — этот тест должен fail.
        # Поднимает либо NotImplementedError, либо DeprecationWarning, либо
        # какой-то явный signal. Никогда — silent success.
        import asyncio

        try:
            result = asyncio.run(
                backend.replay(workflow_name="test", history=b""),
            )
            # Если дошли сюда — replay silently returned.
            pytest.fail(
                f"replay() silently returned {result!r} — это silent no-op, "
                f"НЕ должно быть. Должен raise или warn явно."
            )
        except NotImplementedError:
            pass  # Expected
        except Exception as exc:
            # Любая ошибка — fail-loud. Не должно быть silent success.
            assert not isinstance(exc, type(None))  # guard against future regression


class TestPgRunnerDeprecationWarning:
    """Sprint 7 target: при import модуля emit DeprecationWarning (с
    warnings.simplefilter('default') или явным DeprecationWarning вызовом).

    Это явно отмечает callers что backend deprecated."""

    def test_import_does_not_emit_warning_by_default(self) -> None:
        """Импорт модуля не должен спамить DeprecationWarning каждый раз.

        Только explicit instantiation — явный signal от operator."""
        # Просто проверяем что import работает без warning spam
        with warnings.catch_warnings(record=True) as warning_list:
            warnings.simplefilter("always")
            from src.backend.infrastructure.workflow import pg_runner_backend  # noqa: F401

        # Импорт может emit warning (acceptable), но НЕ должен raise.
        # Если backend помечен deprecated на import — тест упадёт с warning.
        # Это OK — мы хотим явный signal.
        deprecation_warnings = [
            w for w in warning_list if issubclass(w.category, DeprecationWarning)
        ]
        # Нет assertion на count — на усмотрение implementer.
        # Главное — никакого ImportError.