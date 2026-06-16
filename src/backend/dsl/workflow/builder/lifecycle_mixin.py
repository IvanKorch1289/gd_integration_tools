from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self

from src.backend.dsl.workflow.builder._protocol import _WorkflowBuilderProtocol
from src.backend.dsl.workflow.spec import PauseDeclaration, ResumeDeclaration

if TYPE_CHECKING:
    pass


class LifecycleMixin(_WorkflowBuilderProtocol):
    """reflect + checkpoint + guardrail + pause + resume + escalate для WorkflowBuilder. S58 W4 extraction."""

    __slots__ = ()

    def reflect(
        self,
        *,
        trigger: str | None = None,
        source_step: str | None = None,
        memory_writes: list[str] | None = None,
        consolidation_policy: str = "reflect",
        async_mode: bool = True,
        output_key: str | None = None,
    ) -> Self:
        """Добавить reflect-шаг для procedural memory update (S28 W3).

        Обновляет semantic/procedural memory на основе output предыдущего
        шага (``source_step``) или глобального workflow state (``trigger``).

        Args:
            trigger: Опц. dot-path condition для запуска reflect.
            source_step: WorkflowStep.id, чей output анализировать.
            memory_writes: Список memory resource names для записи.
            consolidation_policy: ``summarize`` | ``dedup`` | ``reflect`` | ``none``.
            async_mode: Выполнять в background (default True).
            output_key: Опц. имя property для сохранения результата reflect.

        Returns:
            Self для chain.
        """
        from src.backend.dsl.workflow.spec import ReflectDeclaration

        self._steps.append(
            ReflectDeclaration(
                trigger=trigger,
                source_step=source_step,
                memory_writes=memory_writes or [],
                consolidation_policy=consolidation_policy,
                async_mode=async_mode,
                output_key=output_key,
            )
        )
        return self

    def checkpoint(
        self,
        *,
        checkpoint_id: str | None = None,
        include_steps: tuple[str, ...] = (),
        metadata: dict[str, Any] | None = None,
        output_key: str | None = None,
    ) -> Self:
        """Добавить checkpoint-шаг для workflow state persistence (S28 W3).

        Сохраняет snapshot workflow state (outputs указанных шагов)
        для возможности resume/replay.

        Args:
            checkpoint_id: Опц. явный id checkpoint'а (default — auto-gen).
            include_steps: Кортеж step-id, output которых сохранить.
                Пустой — сохранить весь workflow state.
            metadata: Произвольные metadata для checkpoint.
            output_key: Опц. имя property для сохранения checkpoint_id.

        Returns:
            Self для chain.
        """
        from src.backend.dsl.workflow.spec import CheckpointDeclaration

        self._steps.append(
            CheckpointDeclaration(
                checkpoint_id=checkpoint_id,
                include_steps=include_steps,
                metadata=metadata or {},
                output_key=output_key,
            )
        )
        return self

    def guardrail(
        self,
        rule: str,
        threshold: float,
        *,
        on_exceed: str = "fail",
        target: str | None = None,
        output_key: str | None = None,
    ) -> Self:
        """Добавить guardrail-шаг для лимитов доступа (S28 W3).

        Проверяет что значение ``rule`` не превышает ``threshold``.
        При превышении — выполняется ``on_exceed`` действие.

        Args:
            rule: Тип правила: ``max_cost_usd``, ``max_tokens``,
                ``max_turns``, ``output_size_bytes``.
            threshold: Пороговое значение.
            on_exceed: ``escalate`` | ``fail`` | ``warn`` | ``dlq``.
            target: Опц. dot-path до значения для проверки (default — текущий шаг).
            output_key: Опц. имя property для сохранения результата проверки.

        Returns:
            Self для chain.
        """
        from src.backend.dsl.workflow.spec import GuardrailDeclaration

        self._steps.append(
            GuardrailDeclaration(
                rule=rule,
                threshold=threshold,
                on_exceed=on_exceed,
                target=target,
                output_key=output_key,
            )
        )
        return self

    def pause(self, output_key: str | None = None) -> Self:
        """Добавить pause-шаг для приостановки workflow (S35 GAP-DSL-2).

        Вызывает ``workflow.pause()`` из Temporal SDK.

        Args:
            output_key: Опц. имя property для сохранения timestamp паузы.

        Returns:
            Self для chain.
        """
        self._steps.append(PauseDeclaration(output_key=output_key))
        return self

    def resume(self, checkpoint_id: str | None = None) -> Self:
        """Добавить resume-шаг для возобновления paused workflow (S35 GAP-DSL-2).

        Вызывает ``workflow.resume()`` из Temporal SDK.

        Args:
            checkpoint_id: Опц. checkpoint_id для восстановления состояния.

        Returns:
            Self для chain.
        """
        self._steps.append(ResumeDeclaration(checkpoint_id=checkpoint_id))
        return self

    def escalate(
        self,
        *,
        to_agent: str | None = None,
        to_model: str | None = None,
        reason: str | None = None,
        output_key: str | None = None,
    ) -> Self:
        """Добавить escalate-шаг для переключения на другого агента/модель (S28 W3).

        Применяется при достижении лимитов (guardrail ``on_exceed=escalate``)
        или при явном решении supervisor'а.

        Args:
            to_agent: target agent_id для escalation.
            to_model: target model (``provider:model``) для escalation.
            reason: Причина escalation (логируется).
            output_key: Опц. имя property для сохранения результата.

        Returns:
            Self для chain.
        """
        from src.backend.dsl.workflow.spec import EscalateDeclaration

        self._steps.append(
            EscalateDeclaration(
                to_agent=to_agent,
                to_model=to_model,
                reason=reason,
                output_key=output_key,
            )
        )
        return self
