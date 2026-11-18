"""Вспомогательные функции для reference-workflow-шаблонов.

Шаблоны в этом каталоге — исполняемые примеры: их шаги реально собираются
в Temporal-workflow, а линтер ``tools/check_workflow_specs.py`` проверяет
их при каждом прогоне.

Контракт шага ``call_function`` (ADR-0395)
-----------------------------------------
``compile_call_function_step`` / ``bridge_call_function`` вызывают
module-level функцию по сигнатуре ``fn(payload: dict) -> Any``: payload шага
передаётся **одним** позиционным аргументом
(:func:`src.backend.dsl.workflow.compiler.activity_bridge.bridge_call_function`).

Функции с другой сигнатурой звать напрямую нельзя. Например,
:func:`src.backend.services.ai.usage_meter.estimate_usage` принимает
``messages`` (список) позиционно, поэтому движок передавал ей ``dict`` —
внутри ``for message in messages`` перебирались ключи dict'а, ``content``
не находился, и функция возвращала ``{"tokens": 1, "cost_usd": 0.0}``.
Guardrail шаблона ``guardrail_cost_budget`` с ``target: usage.tokens`` /
``usage.cost_usd`` на этих значениях **никогда не срабатывал** — стоимостный
лимит молча превращался в no-op (fail-OPEN на banking-контуре).

Хелперы ниже адаптируют такие функции под контракт шага: принимают payload
словарём и возвращают словарь с теми же числовыми полями.
"""

from __future__ import annotations

from typing import Any

__all__ = ("estimate_usage_payload",)


def estimate_usage_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Оценить usage LLM-запроса под контракт шага ``call_function``.

    Адаптер над :func:`src.backend.services.ai.usage_meter.estimate_usage`:
    принимает payload шага (словарь) и возвращает
    ``{"tokens": int, "cost_usd": float}``.

    Args:
        payload: Payload шага ``call_function``. Ожидаемые ключи:

            * ``messages`` — список сообщений
              (``{"role": ..., "content": ...}``); отсутствует → пустой список;
            * ``model`` — имя модели для выбора цены (default
              ``"gpt-4o-mini"``).

    Returns:
        Словарь ``{"tokens": int, "cost_usd": float}``.

    Raises:
        TypeError: ``messages`` задан, но не является списком.

    """
    from src.backend.services.ai.usage_meter import estimate_usage

    messages = payload.get("messages") or []
    if not isinstance(messages, list):
        raise TypeError(
            "estimate_usage_payload: 'messages' должен быть списком, "
            f"получено {type(messages).__name__}"
        )
    model = str(payload.get("model") or "gpt-4o-mini")
    return estimate_usage(messages, model=model)
