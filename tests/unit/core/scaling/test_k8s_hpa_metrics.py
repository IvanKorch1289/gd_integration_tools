"""Unit-тесты ``K8sHPAMetricsExporter`` (V15 R-V15-10, K2 Wave 4).

Проверяет:
    - запись метрики в реестр;
    - сериализацию в Prometheus text format;
    - поведение при выключенном feature-flag;
    - корректную обработку меток;
    - идемпотентность singleton-фабрики.
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.core.scaling.k8s_hpa_metrics import (
    K8sHPAMetricsExporter,
    get_hpa_exporter,
    reset_hpa_exporter,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Каждый тест начинается с чистого singleton."""
    reset_hpa_exporter()
    yield
    reset_hpa_exporter()


# ── Тест 1 ────────────────────────────────────────────────────────────────────


def test_exporter_records_metric() -> None:
    """``record_metric`` добавляет замер в реестр; ``snapshot`` его возвращает."""
    exporter = K8sHPAMetricsExporter()
    exporter.record_metric("active_connections", 42.0)

    samples = exporter.snapshot()
    assert len(samples) == 1
    sample = samples[0]
    assert sample.name == "active_connections"
    assert sample.value == 42.0
    assert sample.labels == {}


# ── Тест 2 ────────────────────────────────────────────────────────────────────


def test_exporter_serializes_prometheus_format() -> None:
    """``to_prometheus_text`` возвращает строку в Prometheus text формате."""
    exporter = K8sHPAMetricsExporter()
    exporter.record_metric("queue_depth", 128.0, timestamp=1_715_000_000.0)

    text = exporter.to_prometheus_text()

    # Должно содержать имя, значение и timestamp_ms
    assert "queue_depth" in text
    assert "128.0" in text
    assert "1715000000000" in text
    # Завершается переводом строки
    assert text.endswith("\n")


# ── Тест 3 ────────────────────────────────────────────────────────────────────


def test_exporter_skips_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """``get_handler`` возвращает 503, когда feature-flag выключен."""

    # Патчим feature_flags так, чтобы k8s_hpa_exporter = False
    class _FakeFlags:
        k8s_hpa_exporter = False

    # Перехватываем lazy import внутри _handler через sys.modules
    import sys  # noqa: PLC0415

    fake_features_module = type(sys)("fake_features")
    fake_features_module.feature_flags = _FakeFlags()  # type: ignore[attr-defined]

    monkeypatch.setitem(
        sys.modules, "src.backend.core.config.features", fake_features_module
    )

    exporter = K8sHPAMetricsExporter()
    exporter.record_metric("cpu_utilization", 0.75)
    handler = exporter.get_handler()

    result = handler()

    assert result["status"] == 503
    assert "OFF" in result["content"]


# ── Тест 4 ────────────────────────────────────────────────────────────────────


def test_exporter_handles_labels() -> None:
    """Метки корректно включаются в Prometheus text и сортируются."""
    exporter = K8sHPAMetricsExporter()
    exporter.record_metric(
        "http_requests_total",
        1000.0,
        labels={"method": "GET", "path": "/api/v1"},
        timestamp=1_715_000_000.0,
    )

    text = exporter.to_prometheus_text()

    # Проверяем наличие обоих меток в выводе
    assert 'method="GET"' in text
    assert 'path="/api/v1"' in text
    # Метки отсортированы: method < path (лексикографически)
    assert text.index("method") < text.index("path")
    assert "1000.0" in text


# ── Тест 5 ────────────────────────────────────────────────────────────────────


def test_singleton_idempotent() -> None:
    """``get_hpa_exporter`` возвращает один и тот же объект при повторных вызовах."""
    first = get_hpa_exporter()
    second = get_hpa_exporter()
    third = get_hpa_exporter()

    assert first is second
    assert second is third

    # Запись через один экземпляр видна через другой
    first.record_metric("latency_p95", 45.0)
    assert len(third.snapshot()) == 1
