"""AdaptiveTimeoutPolicy — динамический таймаут per-endpoint (S11 K3 W1).

Хардкод-таймауты в :class:`BaseExternalAPIClient` не учитывают реальный
профиль latency удалённого сервиса: одни ручки отвечают за 50 мс, другие
за 5 с. Жёсткий timeout=10s либо «срезает» хвост (false-positive
deadline), либо избыточно ждёт (увеличивает p99 у клиента).

:class:`AdaptiveTimeoutPolicy` собирает rolling-window latency на каждую
пару ``(host, endpoint)``, вычисляет p99 и предлагает таймаут
``max(p99 * multiplier, min_timeout)``, ограничивая сверху
``max_timeout``. Сэмплы хранятся в :class:`collections.deque` ограниченной
длины — устаревшие выталкиваются автоматически.

Использование::

    policy = AdaptiveTimeoutPolicy()
    policy.record_latency("api.example.com", "/v1/users", 142.0)
    timeout = policy.get_timeout("api.example.com", "/v1/users")
    # ... затем httpx-вызов с этим timeout

Потокобезопасность:
    Объект НЕ thread-safe и не async-lock-safe. В рамках asyncio loop
    одного процесса операции с :class:`collections.deque` атомарны.
    Для multi-process — использовать per-process экземпляр.

Источники:
    Идея — Netflix "adaptive concurrency" + AWS "p99 timeout" guidance.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final

__all__ = (
    "AdaptiveTimeoutConfig",
    "AdaptiveTimeoutPolicy",
    "get_adaptive_timeout_policy",
    "reset_adaptive_timeout_policy",
)

# Минимальное число замеров до выдачи non-default таймаута.
_MIN_SAMPLES_FOR_P99: Final[int] = 10


@dataclass(frozen=True, slots=True)
class AdaptiveTimeoutConfig:
    """Параметры расчёта адаптивного таймаута.

    Attributes:
        multiplier: множитель к p99 latency (по умолчанию 1.5 — даёт
            запас в 50% сверх наблюдённого «long-tail»).
        min_timeout: нижняя граница таймаута в секундах (default 2.0).
        max_timeout: верхняя граница таймаута в секундах (default 60.0).
        window_size: размер rolling-window замеров (default 100).
    """

    multiplier: float = 1.5
    min_timeout: float = 2.0
    max_timeout: float = 60.0
    window_size: int = 100


@dataclass(slots=True)
class _Bucket:
    """Внутренний bucket для одной пары (host, endpoint).

    Сэмплы хранятся в :class:`deque` фиксированной длины.
    """

    samples: deque[float] = field(default_factory=lambda: deque(maxlen=100))


class AdaptiveTimeoutPolicy:
    """Per-endpoint адаптивный таймаут на основе rolling p99 latency.

    Args:
        config: параметры расчёта (multiplier/min/max/window). Если
            None — используются дефолты :class:`AdaptiveTimeoutConfig`.
    """

    def __init__(self, config: AdaptiveTimeoutConfig | None = None) -> None:
        """Инициализирует policy с пустыми статистиками."""
        self._config = config or AdaptiveTimeoutConfig()
        self._buckets: dict[tuple[str, str], _Bucket] = {}

    @property
    def config(self) -> AdaptiveTimeoutConfig:
        """Текущая конфигурация policy."""
        return self._config

    def record_latency(self, host: str, endpoint: str, latency_ms: float) -> None:
        """Запоминает наблюдённую latency в миллисекундах.

        Аргумент ``latency_ms`` округляется до неотрицательного значения;
        NaN/inf молча игнорируются (защита от noisy reading).

        Args:
            host: host удалённого сервиса (``api.example.com``).
            endpoint: путь или logical-name endpoint'а (``/v1/users`` или
                ``users.list``).
            latency_ms: измеренная latency в миллисекундах.
        """
        if not math.isfinite(latency_ms) or latency_ms < 0:
            return
        key = (host, endpoint)
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(samples=deque(maxlen=self._config.window_size))
            self._buckets[key] = bucket
        bucket.samples.append(float(latency_ms))

    def get_timeout(
        self, host: str, endpoint: str, default_seconds: float = 10.0
    ) -> float:
        """Возвращает рекомендуемый таймаут в секундах.

        Если для пары ``(host, endpoint)`` ещё нет достаточного числа
        замеров (см. :data:`_MIN_SAMPLES_FOR_P99`), возвращается
        ``default_seconds`` без выхода за границы ``[min_timeout, max_timeout]``.

        Args:
            host: host удалённого сервиса.
            endpoint: путь или logical-name endpoint'а.
            default_seconds: дефолтный таймаут, если статистики
                недостаточно.

        Returns:
            Таймаут в секундах в диапазоне ``[min_timeout, max_timeout]``.
        """
        bucket = self._buckets.get((host, endpoint))
        if bucket is None or len(bucket.samples) < _MIN_SAMPLES_FOR_P99:
            return self._clamp(default_seconds)

        p99_ms = _percentile(bucket.samples, percent=99.0)
        proposed = (p99_ms / 1000.0) * self._config.multiplier
        return self._clamp(proposed)

    def reset(self, host: str | None = None, endpoint: str | None = None) -> None:
        """Очищает статистику.

        Без аргументов — полный сброс. С указанием ``host`` и
        ``endpoint`` — точечный сброс одного bucket.

        Args:
            host: host для точечного сброса (требует ``endpoint``).
            endpoint: endpoint для точечного сброса (требует ``host``).
        """
        if host is not None and endpoint is not None:
            self._buckets.pop((host, endpoint), None)
            return
        self._buckets.clear()

    def sample_count(self, host: str, endpoint: str) -> int:
        """Возвращает текущее число замеров для (host, endpoint)."""
        bucket = self._buckets.get((host, endpoint))
        return 0 if bucket is None else len(bucket.samples)

    def _clamp(self, seconds: float) -> float:
        """Ограничивает значение интервалом ``[min_timeout, max_timeout]``."""
        return max(self._config.min_timeout, min(self._config.max_timeout, seconds))


# Module-level singleton policy. Сэмплы накапливаются между запросами,
# поэтому instance должен быть один на процесс. Сброс — только в unit-тестах
# через :func:`reset_adaptive_timeout_policy`.
_singleton: AdaptiveTimeoutPolicy | None = None


def get_adaptive_timeout_policy() -> AdaptiveTimeoutPolicy:
    """Возвращает singleton :class:`AdaptiveTimeoutPolicy` (lazy-init)."""
    global _singleton
    if _singleton is None:
        _singleton = AdaptiveTimeoutPolicy()
    return _singleton


def reset_adaptive_timeout_policy() -> None:
    """Сбрасывает singleton (для unit-тестов)."""
    global _singleton
    _singleton = None


def _percentile(samples: Iterable[float], *, percent: float) -> float:
    """Возвращает значение указанного перцентиля по выборке.

    Реализация без зависимости от numpy: сортируем копию и берём
    ближайший индекс (nearest-rank method, простой и предсказуемый).

    Args:
        samples: коллекция числовых сэмплов.
        percent: целевой перцентиль (0..100).

    Returns:
        Значение перцентиля или ``0.0`` для пустой выборки.
    """
    sorted_samples = sorted(samples)
    if not sorted_samples:
        return 0.0
    rank = max(0, math.ceil(percent / 100.0 * len(sorted_samples)) - 1)
    return sorted_samples[rank]
