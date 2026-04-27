"""Генератор DSL YAML-роутов из распарсенных спецификаций.

Формат вывода — минимальный совместимый с ``config/routes/imported/``.
Каждый route = imports-entrypoint + forward-to-external для дефолтного
proxy-пути (Wave 3.5 завершит proxy-процессоры; до этого роут
используется как скелет).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

__all__ = ("render_routes_yaml", "write_routes_yaml")


def render_routes_yaml(*, parsed: dict[str, Any]) -> str:
    """Формирует YAML-текст со списком routes для DSL."""
    lines: list[str] = [
        f"# Авто-сгенерировано {datetime.utcnow().isoformat(timespec='seconds')}Z",
        f"# Источник: {parsed.get('source', 'unknown')}",
        f"# Title: {parsed.get('title', '')}",
        f"# Version: {parsed.get('version', '')}",
        "routes:",
    ]
    for route in parsed.get("routes", []):
        rid = _route_id(route)
        method = route.get("method", "GET")
        path = route.get("path", "/")
        summary = (route.get("summary") or "").replace('"', '\\"')
        req_model = route.get("request_body_ref")
        resp_model = route.get("responses_ref")
        lines.append(f"  - id: {rid}")
        lines.append(f"    method: {method}")
        lines.append(f'    path: "{path}"')
        if summary:
            lines.append(f'    summary: "{summary}"')
        if req_model:
            lines.append(f'    request_schema: "src.schemas.auto.{req_model}"')
        if resp_model:
            lines.append(f'    response_schema: "src.schemas.auto.{resp_model}"')
        lines.append("    steps: []   # ← дополните процессорами или подключите proxy")
    return "\n".join(lines) + "\n"


def write_routes_yaml(*, parsed: dict[str, Any], out_path: str | Path) -> Path:
    """Сериализует результат в файл."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_routes_yaml(parsed=parsed), encoding="utf-8")
    return out


def _route_id(route: dict[str, Any]) -> str:
    op = route.get("operation_id") or ""
    if op:
        return op
    method = route.get("method", "GET").lower()
    path = (
        route.get("path", "/")
        .strip("/")
        .replace("/", "_")
        .replace("{", "")
        .replace("}", "")
    )
    return f"{method}_{path}" or method
