"""W14.4 — классификация side-effects процессоров и actions.

Цель: явно различать процессоры/actions по характеру их побочных
эффектов, чтобы:

* engine мог принимать решения по retry-стратегии (PURE → safe retry,
  SIDE_EFFECTING → требуется ``idempotency_key``);
* SagaProcessor строил correct compensation-цепочку (compensatable=False
  → compensate невозможен, нужно блокировать саму операцию);
* Streamlit Console / `make actions` показывал колонку effect_class.

Ортогональное измерение ``compensatable: bool`` отвечает на вопрос
«можно ли откатить?» — это не про класс, а про обратимость.
"""

from __future__ import annotations

from enum import Enum

__all__ = ("SideEffectKind",)


class SideEffectKind(str, Enum):
    """Класс побочных эффектов процессора/action.

    * ``PURE`` — детерминированная функция input → output, без чтения
      или мутации внешнего состояния. Всегда idempotent. Безопасный
      retry, кэширование, мемоизация.
    * ``STATEFUL`` — читает или мутирует **внутреннее** состояние
      процесса (cachetools, in-memory counter, locks). Idempotent
      только при сохранённом state. Retry допустим в одном процессе.
    * ``SIDE_EFFECTING`` — производит наблюдаемый внешний эффект
      (HTTP/SMTP/SMS/file/queue write). Retry без ``idempotency_key``
      риск дубликатов. Требует outbox-pattern в production.
    """

    PURE = "pure"
    STATEFUL = "stateful"
    SIDE_EFFECTING = "side_effecting"
