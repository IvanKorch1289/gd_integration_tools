# ruff: noqa: S101
"""Регресс-тесты контрактов reference-workflow-шаблонов (волна 34).

Шаблоны ``src/backend/dsl/workflow/templates/*.workflow.yaml`` — исполняемые
примеры: их шаги реально собираются в Temporal-workflow. Регрессы ниже
фиксируют контракт шага ``call_function`` / ``sensor``, который шаблоны
нарушали (тихо, без ошибки при сборке).

Контракт ``call_function`` (ADR-0395)
------------------------------------
``bridge_call_function`` вызывает module-level функцию как
``fn(payload: dict) -> Any`` — payload шага передаётся ОДНИМ позиционным
аргументом. Функция с другой сигнатурой (например ``messages`` — список)
получает вместо списка dict и молча считает неверные значения.

Контракт ``sensor``
-------------------
``compile_sensor_step`` вызывает предикат как activity с ПУСТЫМ payload
(``execute_activity(predicate, {})``) — предикат не должен зависеть от
входных данных, иначе он никогда не станет истинным и workflow упадёт по
таймауту.
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from typing import Any

import pytest
import yaml

from src.backend.dsl.workflow.compiler.activity_bridge import is_call_function_ref

_TEMPLATE_DIR = (
    Path(__file__).resolve().parents[4] / "src/backend/dsl/workflow/templates"
)


def _load_template(name: str) -> dict[str, Any]:
    """Загрузить workflow-шаблон по имени."""
    path = _TEMPLATE_DIR / f"{name}.workflow.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _steps(name: str) -> list[dict[str, Any]]:
    """Список шагов workflow-шаблона."""
    steps = _load_template(name).get("steps") or []
    return [step for step in steps if isinstance(step, dict)]


def _call_function_refs(name: str) -> list[str]:
    """Ссылки ``module:fn`` из всех шагов ``call_function`` шаблона.

    Workflow-DSL описывает шаг плоско: ``- type: call_function`` + ``ref``.
    """
    refs: list[str] = []
    for step in _steps(name):
        if step.get("type") == "call_function" and step.get("ref"):
            refs.append(str(step["ref"]))
    return refs


def _accepts_dict_payload(func: Any) -> bool:
    """Принимает ли функция payload-словарь первым позиционным аргументом."""
    try:
        signature = inspect.signature(func)
    except TypeError, ValueError:  # pragma: no cover — builtins без сигнатуры
        return True
    positional = [
        param
        for param in signature.parameters.values()
        if param.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if not positional:
        return False
    annotation = positional[0].annotation
    if annotation is inspect.Parameter.empty:
        return True
    text = (
        annotation
        if isinstance(annotation, str)
        else getattr(annotation, "__name__", str(annotation))
    )
    # ``from __future__ import annotations`` даёт строковую аннотацию,
    # поэтому сравниваем по префиксу имениgeneric-типа.
    return text.startswith(("Any", "dict", "object", "Mapping", "MutableMapping"))


@pytest.mark.parametrize(
    ("template", "ref"),
    [
        (
            "guardrail_cost_budget",
            "src.backend.dsl.workflow.templates.template_helpers:estimate_usage_payload",
        ),
        ("call_function_ingest", "src.backend.core.utils.json_utils:dumps_str"),
    ],
)
def test_call_function_ref_matches_step_payload_contract(
    template: str, ref: str
) -> None:
    """``call_function``-шаги вызывают функции с контрактом ``fn(dict)``.

    Регресс: ``guardrail_cost_budget`` звал
    ``src.backend.services.ai.usage_meter:estimate_usage(messages, *, model)``
    — движок передавал ей dict, функция считала 0 символов и возвращала
    ``{"tokens": 1, "cost_usd": 0.0}`` → guardrail стоимости не срабатывал
    никогда (молчаливый fail-OPEN).
    """
    assert ref in _call_function_refs(template), (
        f"{template}: ожидается call_function-ref {ref!r}, "
        f"получено {_call_function_refs(template)}"
    )
    module_name, fn_name = ref.split(":", 1)
    func = getattr(importlib.import_module(module_name), fn_name)
    assert callable(func)
    assert _accepts_dict_payload(func), (
        f"{ref}: функция не принимает payload-словарь первым позиционным "
        f"аргументом — шаг call_function передаёт args как единственный "
        f"позиционный аргумент"
    )


def test_guardrail_cost_budget_source_returns_real_numbers() -> None:
    """Числовой источник guardrail'а отдаёт реальные (не нулевые) числа.

    Регресс: при несовместимой сигнатуре ``estimate_usage`` возвращала
    ``{"tokens": 1, "cost_usd": 0.0}`` — лимит ``max_tokens``/``max_cost_usd``
    не мог сработать никогда.
    """
    from src.backend.dsl.workflow.templates.template_helpers import (
        estimate_usage_payload,
    )

    usage = estimate_usage_payload(
        {
            "messages": [{"role": "user", "content": "summarize the cost report"}],
            "model": "gpt-4o-mini",
        }
    )
    assert usage["tokens"] > 1, usage
    assert usage["cost_usd"] > 0.0, usage


def test_sensor_predicate_is_payload_independent() -> None:
    """Предикат sensor'а не зависит от payload (движок передаёт ``{}``).

    Регресс: ``validate_inn(inn: str)`` получал ``{}`` → всегда ``False`` →
    sensor всегда доходил до таймаута (900 c) и workflow падал вместо
    опроса готовности.
    """
    sensors = [
        step for step in _steps("sensor_polling") if step.get("type") == "sensor"
    ]
    assert sensors, "в шаблоне sensor_polling должен быть шаг sensor"
    for spec in sensors:
        predicate = str(spec.get("predicate") or "")
        assert predicate, "sensor без предиката"
        if is_call_function_ref(predicate):
            module_name, fn_name = predicate.split(":", 1)
            func = getattr(importlib.import_module(module_name), fn_name)
            assert _accepts_dict_payload(func), (
                f"{predicate}: предикат принимает не-dict — движок вызывает "
                f"его с пустым payload, такой предикат всегда вернёт False"
            )
        else:
            # action_id — резолвится через action-реестр ядра.
            from src.backend.dsl.commands.action_registry import action_handler_registry
            from src.backend.dsl.commands.setup.registers_domains import _register_tech

            _register_tech()
            assert action_handler_registry.is_registered(predicate), (
                f"{predicate}: action не зарегистрирован в action-реестре — "
                f"sensor не сможет вызвать предикат"
            )


def test_call_function_ingest_does_not_double_wrap_payload() -> None:
    """``args`` шаблона — это payload функции, а не обёртка вокруг него.

    Регресс: ``args: {payload: {}}`` заставлял ``dumps_str`` сериализовать
    обёртку (``'{"payload":{}}'``) вместо самих данных.
    """
    refs = _call_function_refs("call_function_ingest")
    assert refs == ["src.backend.core.utils.json_utils:dumps_str"]
    spec = next(
        step
        for step in _steps("call_function_ingest")
        if step.get("type") == "call_function"
    )
    args = spec.get("args") or {}
    assert "payload" not in args, (
        "args шага call_function — это payload функции; обёртка 'payload' "
        "приводит к сериализации обёртки вместо данных"
    )
