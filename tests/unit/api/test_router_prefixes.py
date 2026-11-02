"""ADR-0421 — устранение двойных префиксов в v1-роутере + монтаж NATS.

До ADR-0421:

* ``admin_langgraph`` монтировался с ``prefix="/admin"`` при собственном
  ``prefix="/admin/langgraph"`` → ``/api/v1/admin/admin/langgraph/*``;
* ``admin_plugins`` монтировался с ``prefix="/admin/plugins"`` при
  собственном ``prefix="/admin/plugins"`` →
  ``/api/v1/admin/plugins/admin/plugins/*``;
* ``admin_nats`` не был смонтирован вообще → 404.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, FastAPI

from src.backend.entrypoints.api.v1.routers import get_v1_routers


def _iter_paths(router: APIRouter, prefix: str = "") -> Iterator[str]:
    """Рекурсивно обходит роуты, включая вложенные ``include_router``.

    FastAPI 0.141 не разворачивает подключённые роутеры в ``router.routes``
    — вместо этого появляется ``_IncludedRouter`` с ``original_router`` и
    ``include_context.prefix``. Пути собираются вручную.
    """
    for route in router.routes:
        original = getattr(route, "original_router", None)
        if original is not None:
            context = getattr(route, "include_context", None)
            sub_prefix = getattr(context, "prefix", "") or ""
            yield from _iter_paths(original, prefix + sub_prefix)
            continue
        path = getattr(route, "path", None)
        if path is not None:
            yield prefix + path


def _paths(router: APIRouter) -> set[str]:
    """Множество путей роутов (без учёта внешнего префикса ``/api/v1``)."""
    return set(_iter_paths(router))


class TestV1RouterPrefixes:
    """Проверки структуры путей v1-роутера."""

    def test_no_doubled_admin_prefix(self) -> None:
        paths = _paths(get_v1_routers())
        doubled = sorted(p for p in paths if "/admin/admin/" in p)
        assert doubled == [], f"Двойные префиксы admin: {doubled}"

    def test_no_doubled_plugins_prefix(self) -> None:
        paths = _paths(get_v1_routers())
        doubled = sorted(p for p in paths if "/plugins/admin/plugins" in p)
        assert doubled == [], f"Двойные префиксы plugins: {doubled}"

    def test_no_repeated_segment_in_admin_paths(self) -> None:
        """Ни один сегмент подряд не повторяется дважды в admin-путях."""
        paths = _paths(get_v1_routers())
        offenders = sorted(
            p
            for p in paths
            if "/admin/" in p
            and any(
                f"/{seg}/{seg}/" in p
                for seg in {s for s in p.split("/") if s and s != "admin"}
            )
        )
        assert offenders == [], f"Повторяющиеся сегменты: {offenders}"

    def test_langgraph_mounted_once(self) -> None:
        paths = _paths(get_v1_routers())
        assert "/admin/langgraph/checkpoints" in paths
        assert "/admin/langgraph/checkpoints/{session_id}" in paths
        assert "/admin/langgraph/checkpoints/{session_id}/restore" in paths

    def test_admin_plugins_mounted_once(self) -> None:
        paths = _paths(get_v1_routers())
        assert "/admin/plugins" in paths
        assert "/admin/plugins/{name}/manifest" in paths

    def test_admin_nats_mounted(self) -> None:
        """NATS-роутер был не смонтирован (404) — теперь доступен."""
        paths = _paths(get_v1_routers())
        assert "/admin/nats/consumers" in paths
        assert "/admin/nats/consumers/{stream}/{durable}/info" in paths


class TestV1RouterMount:
    """Роутер монтируется в приложение без ошибок."""

    def test_router_includes_expected_paths(self) -> None:
        app = FastAPI()
        app.include_router(get_v1_routers(), prefix="/api/v1")
        paths = set(_iter_paths(app.router))
        assert "/api/v1/admin/langgraph/checkpoints" in paths
        assert "/api/v1/admin/plugins" in paths
        assert "/api/v1/admin/nats/consumers" in paths
        assert "/api/v1/admin/admin/langgraph/checkpoints" not in paths
        assert "/api/v1/admin/plugins/admin/plugins" not in paths
