"""make scaffold-route — interactive wizard для нового DSL route (S10 K5 W2).

DX-8.2: Typer-prompt спрашивает source / sink / AI? / retry?, затем
генерирует ``routes/<name>/route.toml`` + ``*.dsl.yaml`` с минимально
рабочим скелетом.

Запуск:

.. code-block:: bash

    python tools/scaffold_route.py
    # либо неинтерактивно:
    python tools/scaffold_route.py \
        --name credit_check --source http --sink http --ai --retry

Опции:
* ``--name`` — обязательное имя route'а (snake_case);
* ``--source`` — http / cron / kafka / webhook / file_watch / cdc;
* ``--sink`` — http / kafka / db / file / dlq / log;
* ``--ai`` — добавить .llm_call() step и mock-LLM fallback;
* ``--retry`` — добавить .policy.retry(attempts=3, backoff=exponential);
* ``--force`` — перезаписать существующий каталог.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from textwrap import dedent
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ROUTES_DIR = ROOT / "routes"

SOURCE_CHOICES = ("http", "cron", "kafka", "webhook", "file_watch", "cdc")
SINK_CHOICES = ("http", "kafka", "db", "file", "dlq", "log")


def _ask(
    prompt: str, *, default: str | None = None, choices: tuple[str, ...] | None = None
) -> str:
    """Простой prompt; интерактивный, если TTY, иначе берём default."""
    label = prompt
    if choices:
        label += f" [{'/'.join(choices)}]"
    if default is not None:
        label += f" (default: {default})"
    label += ": "
    if not sys.stdin.isatty():
        if default is None:
            raise RuntimeError(f"{prompt}: значение обязательно в non-tty режиме")
        return default
    ans = input(label).strip()
    if not ans and default is not None:
        return default
    if choices and ans not in choices:
        print(f"  Допустимы: {choices}; вы ввели {ans!r}; используем default={default}")
        return default or choices[0]
    return ans


def _yes_no(prompt: str, *, default: bool = False) -> bool:
    if not sys.stdin.isatty():
        return default
    suffix = "[Y/n]" if default else "[y/N]"
    ans = input(f"{prompt} {suffix}: ").strip().lower()
    if not ans:
        return default
    return ans in {"y", "yes", "д", "да"}


def _source_yaml(source: str) -> dict[str, Any]:
    if source == "http":
        return {"http": {"method": "POST", "path": "/api/v1/CHANGEME"}}
    if source == "cron":
        return {"cron": "0 */6 * * *"}
    if source == "kafka":
        return {"kafka": {"topic": "CHANGEME", "group_id": "CHANGEME"}}
    if source == "webhook":
        return {"webhook": {"path": "/webhooks/CHANGEME"}}
    if source == "file_watch":
        return {"file_watch": {"glob": "/data/incoming/*.csv"}}
    if source == "cdc":
        return {"cdc": {"table": "public.CHANGEME"}}
    return {source: "TODO"}


def _sink_step(sink: str) -> dict[str, Any]:
    if sink == "http":
        return {"http_call": {"url": "https://api.test/sink", "method": "POST"}}
    if sink == "kafka":
        return {"sink_publish": {"sink_kind": "kafka", "topic": "CHANGEME"}}
    if sink == "db":
        return {"crud_create": {"entity": "CHANGEME", "body": "${body}"}}
    if sink == "file":
        return {"sink_publish": {"sink_kind": "file", "path": "/data/out/$id.json"}}
    if sink == "dlq":
        return {"sink_publish": {"sink_kind": "dlq", "queue": "default_dlq"}}
    return {"log": {"level": "info"}}


def build_dsl_yaml(*, source: str, sink: str, ai: bool, retry: bool, name: str) -> str:
    """Собирает основной YAML-маршрут."""
    steps: list[Any] = [
        {"call_function": {"ref": f"extensions.{name}.normalizer:apply_rules"}}
    ]
    if retry:
        steps.append({"policy": {"retry": {"attempts": 3, "backoff": "exponential"}}})
    if ai:
        steps.append(
            {
                "llm_call": {
                    "provider": "claude",
                    "model": "claude-3-5-sonnet-20241022",
                    "prompt_from": "body.context",
                    "result_property": "ai_response",
                    "dry_run_provider": "mock-llm",
                }
            }
        )
    steps.append(_sink_step(sink))
    steps.append({"audit": {"action": f"{name}.processed"}})
    steps.append({"to": {"response": {"code": 200, "body": "${body}"}}})

    route: dict[str, Any] = {
        "route_id": name,
        "source": _source_yaml(source),
        "steps": steps,
    }

    import yaml

    return yaml.safe_dump(route, allow_unicode=True, sort_keys=False)


def build_route_toml(*, name: str, ai: bool) -> str:
    """Собирает route.toml manifest."""
    capabilities = ["net.outbound", "db.write", "audit.write"]
    if ai:
        capabilities.append("ai.llm")
    cap_toml = "[" + ", ".join(f'"{c}"' for c in capabilities) + "]"
    return dedent(
        f"""\
        # route.toml (V11): manifest для route '{name}' (S10 K5 W2 scaffold).
        name = "{name}"
        version = "0.1.0"
        requires_core = ">=15.0,<16"
        capabilities = {cap_toml}
        tenant_aware = true

        [slo]
        p95_ms = 500
        timeout_ms = 5000

        [feature_flag]
        enabled = true
        gate = "{name}_enabled"
        """
    )


def write_scaffold(
    name: str,
    *,
    source: str,
    sink: str,
    ai: bool,
    retry: bool,
    force: bool,
    routes_dir: Path = ROUTES_DIR,
) -> Path:
    """Записывает route.toml + main.dsl.yaml. Возвращает путь к каталогу."""
    target = routes_dir / name
    if target.exists() and not force:
        raise FileExistsError(
            f"Каталог уже существует: {target}. Используйте --force для перезаписи."
        )
    target.mkdir(parents=True, exist_ok=True)

    (target / "route.toml").write_text(
        build_route_toml(name=name, ai=ai), encoding="utf-8"
    )
    (target / "main.dsl.yaml").write_text(
        build_dsl_yaml(source=source, sink=sink, ai=ai, retry=retry, name=name),
        encoding="utf-8",
    )
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="scaffold-route wizard (S10 K5 W2)")
    parser.add_argument("--name", default=None, help="snake_case имя route")
    parser.add_argument("--source", default=None, choices=SOURCE_CHOICES)
    parser.add_argument("--sink", default=None, choices=SINK_CHOICES)
    parser.add_argument("--ai", action="store_true")
    parser.add_argument("--retry", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--routes-dir", type=Path, default=ROUTES_DIR)
    args = parser.parse_args(argv)

    name = args.name or _ask("Имя route (snake_case)", default=None)
    source = args.source or _ask("Source", choices=SOURCE_CHOICES, default="http")
    sink = args.sink or _ask("Sink", choices=SINK_CHOICES, default="http")
    ai = args.ai or _yes_no("Добавить AI step?", default=False)
    retry = args.retry or _yes_no("Добавить retry policy?", default=False)

    try:
        target = write_scaffold(
            name,
            source=source,
            sink=sink,
            ai=ai,
            retry=retry,
            force=args.force,
            routes_dir=args.routes_dir,
        )
    except FileExistsError as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"OK: scaffold создан в {target}")
    print(f"  → {target / 'route.toml'}")
    print(f"  → {target / 'main.dsl.yaml'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
