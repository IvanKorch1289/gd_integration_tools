"""ABTestProcessor — A/B-эксперимент в DSL pipeline (S10 K3 W3, DSL-1.4).

Делит трафик между двумя ветками (variant A / variant B) по
configurable split (например 0.7 / 0.3) и трекает выбранную ветку
через :class:`Exchange.properties` (для дальнейшего разбора метрик).

Использование в Python (Camel-style)::

    .ab_test(
        experiment_id="checkout_v2",
        variant_a=lambda b: b.call_function("legacy:checkout"),
        variant_b=lambda b: b.call_function("new:checkout"),
        split=(0.7, 0.3),
        track_metric="conversion",
    )

Использование в YAML::

    - ab_test:
        experiment_id: checkout_v2
        split: [0.7, 0.3]
        variant_a:
          steps:
            - call_function: { ref: "legacy:checkout" }
        variant_b:
          steps:
            - call_function: { ref: "new:checkout" }
        track_metric: conversion

Стратегия allocation:
* hash(``correlation_id``) % 100 / 100.0 → детерминированно для
  одного user-session-id (стабильный bucket);
* при отсутствии correlation_id → random.random() (per-request).
"""

from __future__ import annotations

import hashlib
import logging
import random
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = ("ABTestProcessor", "select_variant")

_logger = logging.getLogger("dsl.ab_test")


def select_variant(*, correlation_id: str | None, split: tuple[float, float]) -> str:
    """Возвращает ``"A"`` или ``"B"`` на основе hash(correlation_id) и split.

    Args:
        correlation_id: ID запроса/сессии (для sticky-bucket).
        split: пара (a_weight, b_weight). Должна суммироваться в 1.0.

    Returns:
        Литерал "A" или "B".
    """
    a_weight, b_weight = split
    total = a_weight + b_weight
    if total <= 0:
        return "A"
    a_share = a_weight / total

    if correlation_id:
        h = hashlib.sha256(correlation_id.encode("utf-8")).digest()
        score = (int.from_bytes(h[:4], "big") % 10_000) / 10_000.0
    else:
        score = random.random()  # noqa: S311

    return "A" if score < a_share else "B"


class ABTestProcessor(BaseProcessor):
    """Выбирает variant A/B и пишет результат в exchange.

    Сам по себе НЕ запускает variant — он отмечает выбор;
    pipeline-runtime должен подобрать соответствующий sub-branch
    (см. :class:`ChoiceProcessor` для исполнения).

    Args:
        experiment_id: ID эксперимента (используется как metric label).
        split: пара (a_weight, b_weight). Default (0.5, 0.5).
        track_metric: name метрики для последующего разбора (write-only
            field — runtime смотрит exchange.properties[f"ab_test:{exp}"]).
        result_property: куда положить выбранный variant ("A"/"B").
    """

    def __init__(
        self,
        *,
        experiment_id: str,
        split: tuple[float, float] = (0.5, 0.5),
        track_metric: str | None = None,
        result_property: str | None = None,
        name: str | None = None,
    ) -> None:
        """Сохраняет параметры эксперимента."""
        super().__init__(name=name or f"ab_test:{experiment_id}")
        if not experiment_id:
            raise ValueError("ABTestProcessor: experiment_id обязателен")
        if not isinstance(split, tuple) or len(split) != 2:
            raise ValueError("ABTestProcessor: split должен быть (a, b)")
        if any(w < 0 for w in split):
            raise ValueError("ABTestProcessor: weights >= 0")
        self._experiment_id = experiment_id
        self._split = split
        self._track_metric = track_metric
        self._result_property = result_property or f"ab_test:{experiment_id}"

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выбирает A/B на основе correlation_id."""
        cid = getattr(exchange, "correlation_id", None) or exchange.get_property(
            "correlation_id"
        )
        variant = select_variant(correlation_id=cid, split=self._split)
        exchange.set_property(self._result_property, variant)
        exchange.set_property(f"{self._result_property}:metric", self._track_metric)
        _logger.debug(
            "ab_test selected variant=%s experiment=%s cid=%s",
            variant,
            self._experiment_id,
            cid,
        )

    def to_spec(self) -> dict:
        """YAML round-trip."""
        spec: dict[str, Any] = {
            "experiment_id": self._experiment_id,
            "split": list(self._split),
            "result_property": self._result_property,
        }
        if self._track_metric:
            spec["track_metric"] = self._track_metric
        return {"ab_test": spec}
