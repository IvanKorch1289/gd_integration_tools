"""Нормализация ответов credit-API (Sprint 7 Team T3).

Wave: ``[wave:s7/team-03-credit-1st-client]``. Бизнес-логика
для подключения через DSL ``call_function('extensions.credit_pipeline.
functions.normalize:apply_rules')`` (R-V15-6: 80/20 YAML/Python).

Контракт ``call_function``:

* функция принимает ``exchange`` (или ``body``);
* возвращает обновлённый body или мутирует in-place;
* без побочных эффектов снаружи (no DB, no HTTP — только pure-logic).

См. ADR на builders/integration.py::.call_function — точный сигнатур.
"""

from __future__ import annotations

from typing import Any


def apply_rules(body: dict[str, Any]) -> dict[str, Any]:
    """Применяет нормализующие правила к ответу credit-API.

    Минимальный reference-набор правил:

    * нормализует ``score`` к диапазону ``[0, 1000]``;
    * выставляет ``risk_class`` = ``LOW`` / ``MEDIUM`` / ``HIGH``;
    * приводит ``decision`` к строковой метке.

    Args:
        body: Словарь с полями ответа credit-API (``score``,
            ``decision``, любые дополнительные поля).

    Returns:
        Обновлённый словарь с добавленными нормализованными полями.
    """
    score = body.get("score")
    if isinstance(score, (int, float)):
        score = max(0, min(1000, int(score)))
        body["score"] = score
        if score >= 700:
            body["risk_class"] = "LOW"
        elif score >= 500:
            body["risk_class"] = "MEDIUM"
        else:
            body["risk_class"] = "HIGH"

    decision = body.get("decision")
    if decision is not None and not isinstance(decision, str):
        body["decision"] = str(decision)

    return body


def calculate_combined_score(
    skb_score: int | None, nbki_score: int | None
) -> int:
    """Объединяет SKB и НБКИ скоры по weighted-average.

    Args:
        skb_score: Score от SKB-Техно (0..1000).
        nbki_score: Score от НБКИ (0..1000).

    Returns:
        Объединённый score (целочисленный).
    """
    weights: list[tuple[int, float]] = []
    if isinstance(skb_score, int):
        weights.append((skb_score, 0.6))
    if isinstance(nbki_score, int):
        weights.append((nbki_score, 0.4))
    if not weights:
        return 0
    total_weight = sum(w for _, w in weights)
    return int(sum(s * w for s, w in weights) / total_weight)
