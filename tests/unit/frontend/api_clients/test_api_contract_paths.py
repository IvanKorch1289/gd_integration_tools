"""ADR-0422 — контракт путей клиент↔сервер (``api_clients`` ↔ v1-роутер).

Контекст дефекта
----------------
Streamlit-клиенты (``src/frontend/streamlit_app/api_clients``) обращаются к
API по **захардкоженным** путям. Роутер сервера
(``src/backend/entrypoints/api/v1/routers.py``) — единственный канонический
источник правды о том, какие пути реально зарегистрированы.

До ADR-0422 эти два списка разъехались: 18 обращений клиента указывали на
несуществующие пути и получали 404:

* ``/api/v1/admin/audit/capability`` — сервер отдаёт ``/api/v1/audit/capability``;
* ``/api/v1/admin/feature-flags/{name}/toggle`` — сервер отдаёт
  ``/api/v1/admin/feature-flags/toggle``;
* ``/api/v1/orders/*`` — канонические CRUD-пути ``/api/v1/order/*``
  (``/api/v1/orders/*`` существовали только как скрытые legacy-алиасы);
* ``/api/v1/admin/workflow/step-logs*`` — сервер отдаёт
  ``/api/v1/admin/workflows`` и ``/api/v1/admin/workflows/{instance_id}``;
* ``/api/v1/admin/metrics`` → ``/api/v1/admin/system-info``;
* ``/api/v1/admin/trace-logs`` → ``/api/v1/search/logs``;
* ``/api/v1/admin/litellm-gateway/stats`` → ``/api/v1/admin/ai-costs``;
* ``/api/v1/ai/chat`` → ``/api/v1/ai/llm/stream``;
* ``/api/v1/admin/embedding-providers`` — добавлен серверный endpoint.

Тест — CI-гейт: любой новый путь в клиенте обязан существовать на сервере.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI

from src.backend.entrypoints.api.generator.legacy_aliases import register_legacy_aliases
from src.backend.entrypoints.api.v1.routers import get_v1_routers

#: Каталог клиентских HTTP-клиентов Streamlit.
_CLIENTS_DIR = Path("src/frontend/streamlit_app/api_clients")

#: Имена методов клиента, первым аргументом которых является путь.
_PATH_CALLS = frozenset({"get", "post", "put", "patch", "delete"})

#: ``_request(method, path, ...)`` — путь во втором позиционном аргументе.
_REQUEST_CALL = "_request"

#: Пути верхнего уровня (вне ``/api/v1``), которые регистрирует app_factory.
_APP_LEVEL_PATHS = frozenset(
    {
        "/docs",
        "/health",
        "/livez",
        "/metrics",
        "/openapi.json",
        "/ready",
        "/readyz",
        "/redoc",
    }
)


def _normalize(path: str) -> str:
    """Привести путь к шаблонной форме (``{param}`` → ``{}``).

    Дублирующиеся слэши (следствие подстановки параметра) схлопываются,
    чтобы ``/a/{id}/b`` и ``/a//b`` считались одним путём.
    """
    out: list[str] = []
    depth = 0
    for char in path:
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth = max(0, depth - 1)
            continue
        if depth == 0:
            out.append(char)
    return re.sub(r"/{2,}", "/", "".join(out))


def _path_literal(node: ast.expr) -> str | None:
    """Извлечь шаблон пути из константы или f-строки."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                parts.append("{}")
            else:
                return None
        return "".join(parts)
    return None


def _client_paths() -> dict[str, set[str]]:
    """Собрать ``{нормализованный путь → {файлы-источники}}`` по AST клиентов.

    Разбор идёт по AST, а не по regex: docstring'и клиентов тоже содержат
    пути, и regex-скан по ним давал бы ложные срабатывания.
    """
    found: dict[str, set[str]] = {}
    for source in sorted(_CLIENTS_DIR.glob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            index = 0 if func.attr in _PATH_CALLS else None
            if func.attr == _REQUEST_CALL:
                index = 1
            if index is None or index >= len(node.args):
                continue
            raw = _path_literal(node.args[index])
            if raw is None or not raw.startswith("/"):
                continue
            found.setdefault(_normalize(raw), set()).add(source.name)
    return found


def _iter_router_paths(router: APIRouter, prefix: str = "") -> Iterator[str]:
    """Рекурсивно обойти роуты, включая вложенные ``include_router``."""
    for route in router.routes:
        original = getattr(route, "original_router", None)
        if original is not None:
            context = getattr(route, "include_context", None)
            sub_prefix = getattr(context, "prefix", "") or ""
            yield from _iter_router_paths(original, prefix + sub_prefix)
            continue
        path = getattr(route, "path", None)
        if path is not None:
            yield prefix + path


def _server_paths() -> set[str]:
    """Пути, реально зарегистрированные сервером (v1-роутер + legacy-алиасы)."""
    paths = {f"/api/v1{path}" for path in _iter_router_paths(get_v1_routers())}
    app = FastAPI()
    register_legacy_aliases(app)
    paths |= {
        route.path for route in app.routes if getattr(route, "path", "").startswith("/")
    }
    return paths


@pytest.mark.unit
class TestClientServerPathContract:
    """Каждый путь клиента обязан существовать на сервере."""

    def test_client_paths_are_discovered(self) -> None:
        """Сканер находит клиентские пути (защита от «пустого» теста)."""
        paths = _client_paths()
        assert len(paths) >= 30, f"ожидалось ≥30 клиентских путей, найдено {len(paths)}"
        assert "/api/v1/admin/capabilities" in paths

    def test_every_client_path_exists_on_server(self) -> None:
        """Нет клиентского пути, который сервер не регистрирует."""
        server = {_normalize(path) for path in _server_paths()}
        missing: dict[str, set[str]] = {}
        for path, sources in _client_paths().items():
            if path in server or path in _APP_LEVEL_PATHS:
                continue
            missing[path] = sources
        assert not missing, (
            "клиентские пути отсутствуют на сервере (канон — роутер сервера): "
            f"{ {k: sorted(v) for k, v in sorted(missing.items())} }"
        )

    def test_no_legacy_alias_dependency_in_clients(self) -> None:
        """Клиент не должен зависеть от скрытых legacy-алиасов.

        ``/api/v1/orders/*`` и ``/api/v1/users/*`` существуют только как
        deprecated-алиасы (``include_in_schema=False``) — они не видны в
        OpenAPI и будут удалены. Канонические пути — ``/api/v1/order/*``,
        ``/api/v1/user/*``.
        """
        legacy_prefixes = ("/api/v1/orders/", "/api/v1/users/", "/api/v1/files/")
        offenders = sorted(
            path for path in _client_paths() if path.startswith(legacy_prefixes)
        )
        assert not offenders, f"клиент зависит от legacy-алиасов: {offenders}"
