#!/usr/bin/env python3
"""Scaffold generator for new light route (MINIMAX W10 DX).

Создаёт `routes/<name>/` (V11.1a «лёгкий плагин»):
- ``route.toml``     — манифест (name/version/capabilities/feature_flag/slo);
- ``main.dsl.yaml``  — маршрут: feature-flag gate → validate → echo-response;
- ``README.md``      — cURL smoke (позитив + флаг-gate) для ручной проверки.

Usage:
    uv run python ops/scripts/new_route.py <snake_case_name> [--root PATH]

Examples:
    uv run python ops/scripts/new_route.py order_status
    uv run python ops/scripts/new_route.py kyc_check --root /tmp/repo
"""

from __future__ import annotations

import re
from pathlib import Path

import typer

app = typer.Typer(help="Scaffold new light route (routes/<name>/)")


def _validate_name(name: str) -> str:
    """snake_case-имя маршрута: [a-z][a-z0-9_]* (id маршрута и файлов)."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        typer.echo(
            f"Ошибка: имя '{name}' должно быть snake_case "
            f"([a-z][a-z0-9_]*), например 'order_status'",
            err=True,
        )
        raise typer.Exit(code=1)
    return name


ROUTE_TOML_TEMPLATE = """\
# route.toml (V11): manifest for route '{name}' (generated: make new-route).
# Отредактируйте capabilities/slo под домен; CHANGEME-плейсхолдеров в toml нет.
name = "{name}"
version = "0.1.0"
requires_core = ">=0.20,<0.21"
capabilities = ["net.outbound", "audit.write"]
tenant_aware = true
feature_flag = {{ enabled = true, gate = "{name}_enabled" }}
slo = {{ p95_ms = 500, timeout_ms = 5000 }}
schedule = "never"
"""

ROUTE_YAML_TEMPLATE = """\
route_id: {name}
source:
  http:
    method: POST
    path: /api/v1/{name}   # CHANGEME: целевой public path маршрута
steps:
- feature_flag:
    flag: {name}_enabled
    default: true
    stop_on_disabled: false
    output_field: {name}_active
- validate_request:
    schema:
      type: object
- to:
    response:
      code: 200
      body: ${{body}}   # CHANGEME: доменная логика (добавьте steps до `to`)
"""

ROUTE_README_TEMPLATE = """\
# route: {name}

Скаффолд сгенерирован `make new-route NAME={name}`. Заполните `main.dsl.yaml`
доменными steps (словарь шагов — `docs/integration/INTEGRATION_GUIDE.md`).

## Функциональный smoke (cURL)

После `make dev-light` (backend на :8000):

```bash
# Позитивный сценарий (флаг {name}_enabled включён по умолчанию)
curl -sf -X POST http://localhost:8000/api/v1/{name} \\
  -H 'Content-Type: application/json' -d '{{}}' | jq .

# Flag-gate: выключенный флаг → skipped-статус (не 404)
curl -sf -X POST http://localhost:8000/api/v1/{name} \\
  -H 'Content-Type: application/json' -d '{{}}' -H 'X-Feature-Flag-{name}_enabled: false' | jq .
```

Критерий: 2xx и ответ содержит эхо `body` (или `skipped` при выключенном
флаге). Браузерный smoke: Swagger UI `http://localhost:8000/docs` →
POST /api/v1/{name} → «Try it out» → 2xx.
"""


@app.command()
def main(
    name: str = typer.Argument(
        ..., help="snake_case имя маршрута (напр. order_status)"
    ),
    root: Path = typer.Option(
        None, "--root", help="Корень репозитория (default: авто-детект)"
    ),
) -> None:
    """Создать routes/<name>/ с route.toml, main.dsl.yaml и cURL-README."""
    _validate_name(name)
    repo_root = root if root is not None else Path(__file__).resolve().parents[2]
    route_dir = repo_root / "routes" / name
    if route_dir.exists():
        typer.echo(f"Ошибка: {route_dir} уже существует", err=True)
        raise typer.Exit(code=1)

    route_dir.mkdir(parents=True)
    (route_dir / "route.toml").write_text(
        ROUTE_TOML_TEMPLATE.format(name=name), encoding="utf-8"
    )
    (route_dir / "main.dsl.yaml").write_text(
        ROUTE_YAML_TEMPLATE.format(name=name), encoding="utf-8"
    )
    (route_dir / "README.md").write_text(
        ROUTE_README_TEMPLATE.format(name=name), encoding="utf-8"
    )

    typer.echo(f"Создано: {route_dir}/")
    typer.echo("Следующие шаги:")
    typer.echo(f"  1. Заполнить steps в routes/{name}/main.dsl.yaml (CHANGEME path)")
    typer.echo("  2. Проверить манифест: pytest tests/unit/services/routes/")
    typer.echo(f"  3. make dev-light → cURL smoke из routes/{name}/README.md")


if __name__ == "__main__":
    app()
