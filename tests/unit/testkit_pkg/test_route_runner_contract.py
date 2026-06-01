"""Контракт-тест: пинит публичную сигнатуру :meth:`RouteRunner.run`.

К2 (routes/<name>/route.toml + RouteLoader full-cycle) расширяет схему
аддитивно. Этот тест не позволяет нечаянно поменять сигнатуру и
сломать testkit-потребителей (chaos-тесты, perf-сценарии, тьюторы).
"""

from __future__ import annotations

import inspect

from testkit.route_runner import RouteRunner


def test_route_runner_run_signature_pinned() -> None:
    """Параметры RouteRunner.run не изменились."""
    sig = inspect.signature(RouteRunner.run)
    params = list(sig.parameters.values())
    names = [p.name for p in params]
    assert names == ["self", "route_id", "payload", "tenant"], names
    # tenant — keyword-only
    tenant = sig.parameters["tenant"]
    assert tenant.kind is inspect.Parameter.KEYWORD_ONLY
    # payload имеет дефолт None
    assert sig.parameters["payload"].default is None
    assert sig.parameters["tenant"].default is None
