"""Prometheus-экспортёр метрик для k8s HPA (уровень 3 auto-scaler, V15 R-V15-10).

Назначение:
    Реализует container-level auto-scaling через экспорт произвольных метрик
    в формате Prometheus text. Данные метрики потребляются k8s HPA через
    custom metrics API (prometheus-adapter или KEDA).

Архитектура:
    - ``HPAMetricSample`` — неизменяемый dataclass для одного замера.
    - ``K8sHPAMetricsExporter`` — реестр метрик + сериализатор в Prometheus-text.
    - ``get_hpa_exporter()`` — singleton-фабрика; безопасна для многопоточного доступа.

Активация:
    Контролируется feature-flag ``feature_flags.k8s_hpa_exporter`` (default-OFF).
    При выключенном флаге ``get_handler()`` возвращает заглушку с кодом 503.

Использование::

    from src.backend.core.scaling.k8s_hpa_metrics import get_hpa_exporter

    exporter = get_hpa_exporter()
    exporter.record_metric("active_connections", 42.0, labels={"pool": "db"})
    text = exporter.to_prometheus_text()
    # → 'active_connections{pool="db"} 42.0\\n'

Prometheus-text формат (упрощённый):
    ``metric_name{label1="v1",label2="v2"} value timestamp_ms\\n``

    Если labels пустые — ``metric_name value timestamp_ms\\n``.
    Timestamp — Unix millis (соответствует OpenMetrics).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

__all__ = (
    "HPAMetricSample",
    "K8sHPAMetricsExporter",
    "get_hpa_exporter",
    "reset_hpa_exporter",
)

# Тип для ASGI/aiohttp-style handler-функции
# (принимает scope/receive/send или request — в зависимости от фреймворка).
# Здесь используется простой callable, не требующий импорта HTTP-фреймворка.
HandlerFn = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class HPAMetricSample:
    """Один замер HPA-метрики.

    Attributes:
        name: Имя метрики в snake_case (пример: ``active_db_connections``).
        value: Числовое значение метрики.
        labels: Произвольный набор Prometheus-меток; может быть пустым.
        timestamp: Unix-время фиксации замера в секундах (float).
            Если не указано явно — устанавливается в момент создания.
    """

    name: str
    value: float
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class K8sHPAMetricsExporter:
    """Экспортёр метрик для k8s HPA в формате Prometheus text.

    Хранит последний замер для каждой метрики (по составному ключу
    ``name + sorted(labels.items())``). Потокобезопасен: все мутации
    защищены ``threading.Lock``.

    Примеры использования::

        exporter = K8sHPAMetricsExporter()
        exporter.record_metric("queue_depth", 128.0, labels={"queue": "orders"})
        print(exporter.to_prometheus_text())
        # queue_depth{queue="orders"} 128.0 <timestamp_ms>

    Методы публичного API (≤10, соответствует правилу God Object):
        - ``record_metric``
        - ``to_prometheus_text``
        - ``get_handler``
        - ``clear``
        - ``snapshot``
    """

    def __init__(self) -> None:
        """Инициализирует пустой реестр метрик."""
        self._registry: dict[str, HPAMetricSample] = {}
        self._lock = threading.Lock()

    # ── Запись ─────────────────────────────────────────────────────────────

    def record_metric(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
        *,
        timestamp: float | None = None,
    ) -> None:
        """Записывает (или обновляет) замер метрики.

        Если метрика с тем же ``name`` и ``labels`` уже существует —
        перезаписывается. Ключ составной: ``name + sorted(labels.items())``.

        Args:
            name: Имя метрики в snake_case.
            value: Числовое значение.
            labels: Словарь Prometheus-меток. ``None`` равнозначно ``{}``.
            timestamp: Unix-время фиксации в секундах. По умолчанию ``time.time()``.
        """
        effective_labels: dict[str, str] = labels or {}
        effective_ts = timestamp if timestamp is not None else time.time()
        sample = HPAMetricSample(
            name=name, value=value, labels=effective_labels, timestamp=effective_ts
        )
        key = _make_key(name, effective_labels)
        with self._lock:
            self._registry[key] = sample

    # ── Сериализация ───────────────────────────────────────────────────────

    def to_prometheus_text(self) -> str:
        """Сериализует все накопленные метрики в Prometheus text format.

        Формат каждой строки::

            metric_name{label1="v1",label2="v2"} value timestamp_ms

        Метки сортируются по имени для детерминированного вывода.
        Временная метка приводится к целым миллисекундам (OpenMetrics-совместимо).

        Returns:
            Строка в формате Prometheus text exposition format.
            Пустая строка, если реестр пуст.
        """
        with self._lock:
            samples = list(self._registry.values())

        lines: list[str] = []
        for sample in samples:
            lines.append(_format_sample(sample))
        return "\n".join(lines) + ("\n" if lines else "")

    # ── HTTP handler ───────────────────────────────────────────────────────

    def get_handler(self) -> HandlerFn:
        """Возвращает HTTP-handler для ``GET /metrics/hpa``.

        Handler реализован как обычная функция без обязательного импорта
        HTTP-фреймворка (lazy-compatible). Интеграция с FastAPI/aiohttp
        выполняется на уровне entrypoint.

        Поведение:
            - Если ``feature_flags.k8s_hpa_exporter`` включён —
              возвращает функцию, отдающую Prometheus text (200).
            - Если флаг выключен — возвращает заглушку (503).

        Returns:
            Callable, принимающий произвольные аргументы и возвращающий
            ``dict`` с ключами ``status``, ``content``, ``content_type``.
        """
        exporter = self

        def _handler(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            """Обработчик GET /metrics/hpa.

            Returns:
                Словарь с полями ``status`` (int), ``content`` (str),
                ``content_type`` (str).
            """
            # Lazy import feature_flags, чтобы избежать циклических зависимостей
            # при инициализации модуля.
            try:
                from src.backend.core.config.features import (
                    feature_flags,  # noqa: PLC0415
                )

                enabled = feature_flags.k8s_hpa_exporter
            except Exception:  # noqa: BLE001
                enabled = False

            if not enabled:
                return {
                    "status": 503,
                    "content": "# k8s_hpa_exporter feature flag is OFF\n",
                    "content_type": "text/plain; version=0.0.4",
                }

            return {
                "status": 200,
                "content": exporter.to_prometheus_text(),
                "content_type": "text/plain; version=0.0.4",
            }

        return _handler

    # ── Вспомогательные методы ─────────────────────────────────────────────

    def clear(self) -> None:
        """Очищает реестр всех метрик.

        Используется в тестах или при сбросе состояния.
        """
        with self._lock:
            self._registry.clear()

    def snapshot(self) -> list[HPAMetricSample]:
        """Возвращает копию всех текущих замеров.

        Returns:
            Список ``HPAMetricSample`` в произвольном порядке.
        """
        with self._lock:
            return list(self._registry.values())


# ── Singleton ──────────────────────────────────────────────────────────────────

_singleton_lock = threading.Lock()
_singleton_instance: K8sHPAMetricsExporter | None = None


def get_hpa_exporter() -> K8sHPAMetricsExporter:
    """Возвращает singleton-экземпляр ``K8sHPAMetricsExporter``.

    Потокобезопасен через double-checked locking. Первый вызов создаёт
    экземпляр; последующие возвращают тот же объект.

    Returns:
        Единственный экземпляр ``K8sHPAMetricsExporter`` для процесса.

    Example::

        exporter = get_hpa_exporter()
        assert get_hpa_exporter() is exporter  # тот же объект
    """
    global _singleton_instance  # noqa: PLW0603
    if _singleton_instance is None:
        with _singleton_lock:
            if _singleton_instance is None:
                _singleton_instance = K8sHPAMetricsExporter()
    return _singleton_instance


def reset_hpa_exporter() -> None:
    """Сбрасывает singleton (только для тестов).

    После вызова следующий ``get_hpa_exporter()`` создаст новый экземпляр.
    """
    global _singleton_instance  # noqa: PLW0603
    with _singleton_lock:
        _singleton_instance = None


# ── Внутренние утилиты ────────────────────────────────────────────────────────


def _make_key(name: str, labels: dict[str, str]) -> str:
    """Строит уникальный ключ для записи в реестре.

    Args:
        name: Имя метрики.
        labels: Словарь меток.

    Returns:
        Строка вида ``"metric_name|key1=v1,key2=v2"`` с отсортированными метками.
    """
    label_part = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
    return f"{name}|{label_part}"


def _format_sample(sample: HPAMetricSample) -> str:
    """Форматирует ``HPAMetricSample`` в одну строку Prometheus text.

    Args:
        sample: Замер метрики.

    Returns:
        Строка вида ``metric_name{l1="v1"} 42.0 1715000000000``.
        Если метки отсутствуют — без фигурных скобок.
    """
    timestamp_ms = int(sample.timestamp * 1000)

    if sample.labels:
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(sample.labels.items()))
        return f"{sample.name}{{{label_str}}} {sample.value} {timestamp_ms}"

    return f"{sample.name} {sample.value} {timestamp_ms}"


if TYPE_CHECKING:
    # Проверка типов: убедимся, что HandlerFn совместим с Callable
    _: HandlerFn = lambda: None  # noqa: E731
