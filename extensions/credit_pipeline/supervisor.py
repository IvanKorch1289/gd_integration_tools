"""Диспетчеризация кредитной заявки между агентами расширения (ADR-0409).

Закрывает «supervisor-диспетчеризацию» из workflow
``multi_agent_supervisor``: шаг подменял диспетчеризацию на LLM-вызов
``ai.run_agent``, который ничего не распределял. Здесь — честная
реализация поверх core-супервизора
:class:`src.backend.core.ai.multi_agent.MultiAgentSupervisor` с **реальными**
агентами расширения (``scoring_agent`` / ``document_parser_agent`` из
``extensions/credit_pipeline/agents``), а не со stub-агентами ядра.

Поведение супервизора (core, ADR-0207):

* LangGraph доступен → LLM-супервизор распределяет задачи между
  агентами (handoff);
* LangGraph недоступен → детерминированный роутер вызывает каждого
  агента ровно один раз, передавая результат предыдущего следующему.

Расширение импортирует только ``src.backend.core.*`` — слой-правило
``extensions → core`` (ADR-042).

Связанные ADR: ADR-0409 (волна 22), ADR-0207 (multi-agent facade),
ADR-0403 (activity-имена workflow).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger

__all__ = ("supervise",)

logger = get_logger("extensions.credit_pipeline.supervisor")

#: Имя супервизора в логах и отчёте.
SUPERVISOR_NAME = "credit_orchestrator"


async def supervise(payload: dict[str, Any]) -> dict[str, Any]:
    """Раздать кредитную заявку специализированным агентам расширения.

    Args:
        payload: Данные заявки (``applicant_id``, ``amount``,
            ``duration_months``, ``monthly_income``, ``purpose``) и
            опциональный ``prompt`` (контекст для LLM-супервизора).

    Returns:
        Плоский словарь:

        * ``supervisor`` — имя супервизора;
        * ``agents_invoked`` — список вызванных агентов;
        * ``credit_score`` / ``risk_class`` — результат risk-скоринга;
        * ``scoring`` — полный вывод ``scoring_agent``;
        * ``document`` — полный вывод ``document_parser_agent``;
        * ``final_response`` — сводка супервизора.

    Raises:
        RuntimeError: Супервизор недоступен (feature-flag выключен или
            супервизор вернул ошибку) — fail-closed, без «пустого» отчёта.

    """
    from extensions.credit_pipeline.agents import document_parser_agent, scoring_agent
    from src.backend.core.ai.multi_agent import AgentSpec, MultiAgentSupervisor

    supervisor = MultiAgentSupervisor(
        name=SUPERVISOR_NAME,
        agents=[
            AgentSpec(
                name="scoring_agent",
                description="Считает кредитный score и риск-класс заявки",
                invoke=scoring_agent,
            ),
            AgentSpec(
                name="document_parser_agent",
                description="Разбирает документы заявителя и считает полноту",
                invoke=document_parser_agent,
            ),
        ],
    )

    prompt = str(payload.get("prompt") or "Оценить кредитную заявку")
    result = await supervisor.run(prompt=prompt, payload=dict(payload))

    outputs = list(result.get("outputs") or [])
    error = result.get("error")
    if error and not outputs:
        raise RuntimeError(f"supervise: супервизор недоступен — {error}")
    if error:
        # Degraded-режим: LangGraph/LLM недоступны, но детерминированный
        # роутер отработал — результат валиден, потеря только в выборе
        # агента. Сообщаем, но не роняем поток.
        logger.warning("supervise: супервизор отработал в degraded-режиме: %s", error)

    by_agent: dict[str, dict[str, Any]] = {}
    for output in outputs:
        agent_name = output.get("agent")
        if isinstance(agent_name, str):
            by_agent[agent_name] = output

    scoring = by_agent.get("scoring_agent", {})
    document = by_agent.get("document_parser_agent", {})

    logger.info(
        "supervise: супервизор %s вызвал агентов %s",
        SUPERVISOR_NAME,
        result.get("agents_invoked"),
    )

    return {
        "supervisor": result.get("supervisor", SUPERVISOR_NAME),
        "agents_invoked": list(result.get("agents_invoked") or []),
        "credit_score": int(scoring.get("credit_score", 0) or 0),
        "risk_class": str(scoring.get("risk_class", "HIGH")),
        "scoring": scoring,
        "document": document,
        "final_response": str(result.get("final_response") or ""),
    }
