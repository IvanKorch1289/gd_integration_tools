"""DSL simulate CLI — dry-run для route с waterfall в терминале (S10 K5 W3).

DX-8.3: воспроизводит то же поведение что Streamlit Dry-run UI
(``46_DSL_DryRun.py``), но из терминала. Удобно для CI-проверок
"сценарий укладывается в SLA" или для разработки routes без UI.

Запуск:

.. code-block:: bash

    python tools/dsl_simulate.py routes/credit_check/main.dsl.yaml
    python tools/dsl_simulate.py routes/credit_check/ --json
    make simulate ROUTE=credit_check          # обёртка из Makefile
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from src.backend.dsl.engine.dry_run import dry_run_route, waterfall_lines


def _resolve_route_path(arg: str) -> Path:
    """Принимает либо файл, либо имя route (тогда ищем routes/<name>/main.dsl.yaml)."""
    candidate = Path(arg)
    if candidate.is_file():
        return candidate
    # ищем routes/<arg>/*.dsl.yaml
    routes_dir = Path("routes") / arg
    if routes_dir.is_dir():
        files = sorted(routes_dir.glob("*.dsl.yaml")) + sorted(
            routes_dir.glob("*.dsl.yml")
        )
        if files:
            return files[0]
    raise FileNotFoundError(
        f"Route не найден: {arg!r} (искал файл и routes/{arg}/*.dsl.yaml)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DSL simulate (S10 K5 W3)")
    parser.add_argument("route", help="Путь к YAML или имя route (routes/<name>)")
    parser.add_argument("--payload", type=Path, help="JSON-файл со sample payload")
    parser.add_argument("--seed", type=int, default=0, help="Random seed")
    parser.add_argument("--json", action="store_true", help="JSON-вывод")
    parser.add_argument(
        "--width", type=int, default=40, help="Ширина waterfall (символов)"
    )
    args = parser.parse_args(argv)

    try:
        route_path = _resolve_route_path(args.route)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 2

    route = yaml.safe_load(route_path.read_text(encoding="utf-8")) or {}

    payload = None
    if args.payload and args.payload.is_file():
        try:
            payload = json.loads(args.payload.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"payload JSON error: {exc}", file=sys.stderr)
            return 2

    result = dry_run_route(route, sample_payload=payload, seed=args.seed)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return 0

    print(f"Route: {route_path}")
    print(f"route_id: {result.route_id}")
    print(f"Total: {result.total_ms:.2f}ms ({len(result.steps)} steps)")
    print()
    print("Waterfall:")
    for line in waterfall_lines(result, width=args.width):
        print(f"  {line}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
