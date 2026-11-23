"""Функциональный smoke-тест: один запрос по каждому workflow.

Запуск (из корня репозитория)::

    docker compose -f ops/compose/docker-compose.yml \\
        -f ops/compose/docker-compose.prod.yml \\
        exec -T app python /app/ops/compose/smoke_all_workflows.py

Скрипт выполняется ВНУТРИ контейнера приложения: ключ API берётся из
настроек приложения (секрет наружу не выходит).

Что проверяется
----------------
1. **HTTP-роуты** (DSL-роуты, опубликованные как REST-эндпоинты) — реальный
   запрос к работающему приложению: routing → авторизация → capability-гейт →
   движок → внешние вызовы → ответ.
2. **Workflow-спецификации** (шаблоны DSL + workflow'и расширений) — запуск
   через тот же триггер workflow'ов, что и в проде:
   ``POST /api/v1/admin/workflows/trigger/{workflow_name}``.

Итог печатается таблицей и машинно-читаемым JSON (итог в stdout между
маркерами ``---SMOKE-JSON---``).
"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.error
import urllib.request
from typing import Any

from src.backend.core.config.settings import settings

HOST = "api.prod.local"
BASE = "http://localhost:8000"
JSON_MARKER = "---SMOKE-JSON---"

#: HTTP-роуты, опубликованные приложением (метод → путь → тело).
HTTP_ROUTES: list[tuple[str, str, str, dict[str, Any]]] = [
    ("POST", "/api/v1/demo/echo", "echo_demo", {"message": "smoke"}),
    ("GET", "/api/v1/demo/health", "health_proxy_demo", {}),
    ("POST", "/api/v1/jupyter/run", "jupyter_hub_run/run", {}),
    ("POST", "/api/v1/jupyter/run-file", "jupyter_hub_run/run-file", {}),
    ("POST", "/api/v1/jupyter/run-inline", "jupyter_hub_run/run-inline", {}),
    ("POST", "/api/v1/osint/report", "osint_agent", {}),
]


def _headers() -> dict[str, str]:
    raw = settings.secure.api_key
    key = raw.get_secret_value() if raw is not None else ""
    return {
        "X-API-Key": key,
        "Host": HOST,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _request(
    method: str, path: str, body: dict[str, Any] | None = None
) -> tuple[int | str, str]:
    """Выполняет HTTP-запрос к приложению внутри контейнера."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(  # noqa: S310 — фиксированный адрес localhost
        f"{BASE}{path}", data=data, method=method, headers=_headers()
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:  # noqa: S310
            return response.status, response.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")
    except Exception as exc:  # noqa: BLE001 — любой сбой — результат теста
        return "ERR", f"{type(exc).__name__}: {exc}"


def _workflow_names() -> list[str]:
    """Список workflow'ов из реестра приложения + шаблонов DSL."""
    names: set[str] = set()
    status, payload = _request("GET", "/api/v1/admin/workflows")
    if status == 200:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("workflow_id")
                    if isinstance(name, str):
                        names.add(name)
    status, payload = _request("GET", "/api/v1/admin/workflow-templates/")
    if status == 200:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    name = item.get("name")
                    if isinstance(name, str):
                        names.add(name)
    return sorted(names)


async def main() -> None:
    """Выполняет по одному запросу на каждый workflow и печатает отчёт."""
    results: list[dict[str, Any]] = []

    print("== HTTP-роуты ==")
    for method, path, label, body in HTTP_ROUTES:
        status, payload = await asyncio.to_thread(_request, method, path, body)
        ok = status in (200, 201, 202, 204)
        results.append(
            {
                "kind": "route",
                "name": label,
                "method": method,
                "path": path,
                "status": status,
                "ok": ok,
                "response": payload[:220],
            }
        )
        print(f"  [{'OK ' if ok else 'FAIL'}] {method:4} {path:34} → {status}")

    print("== Workflow-спецификации (trigger) ==")
    for name in _workflow_names():
        status, payload = await asyncio.to_thread(
            _request, "POST", f"/api/v1/admin/workflows/trigger/{name}", {}
        )
        ok = status in (200, 201, 202)
        results.append(
            {
                "kind": "workflow",
                "name": name,
                "method": "POST",
                "path": f"/api/v1/admin/workflows/trigger/{name}",
                "status": status,
                "ok": ok,
                "response": payload[:220],
            }
        )
        print(f"  [{'OK ' if ok else 'FAIL'}] trigger {name:38} → {status}")

    total = len(results)
    failed = [r for r in results if not r["ok"]]
    print(f"\nИтого: {total - len(failed)}/{total} успешно")
    for item in failed:
        print(f"  FAIL {item['kind']:8} {item['name']:38} → {item['status']}")
    print(JSON_MARKER)
    print(
        json.dumps(
            {"total": total, "failed": len(failed), "results": results},
            ensure_ascii=False,
        )
    )
    sys.stdout.flush()


if __name__ == "__main__":
    asyncio.run(main())
