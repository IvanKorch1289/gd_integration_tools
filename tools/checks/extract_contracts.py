"""Extract protocol contracts для Contract Diff Gate (OP-6).

Генерирует три JSON-артефакта в целевую директорию (default
``.baselines/contracts/``):

- ``rest_openapi.json``         — OpenAPI из FastAPI-приложения;
- ``graphql_introspection.json``— introspection ``__schema`` strawberry;
- ``grpc_proto.json``           — services/methods из proto-дескрипторов.

Использование::

    uv run python tools/checks/extract_contracts.py --out .baselines/contracts
    uv run python tools/checks/contract_diff_gate.py diff \\
        --current .baselines/contracts --baseline .baselines/contracts

Каждый протокол изолирован: ошибка одного не блокирует остальные
(файл не пишется → гейт сообщает missing file для этого протокола).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Bootstrap: repo root в sys.path (import extensions.* из tools/).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.backend.core.logging import get_logger

__all__ = ("extract_all", "extract_rest", "extract_graphql", "extract_grpc")

_logger = get_logger("contract-extract")

_REST_FILE = "rest_openapi.json"
_GRAPHQL_FILE = "graphql_introspection.json"
_GRPC_FILE = "grpc_proto.json"


def extract_rest() -> dict[str, Any]:
    """OpenAPI-схема приложения (без запуска сервера)."""
    from src.backend.main import app

    return app.openapi()


def extract_graphql() -> dict[str, Any]:
    """Introspection ``__schema`` strawberry auto-schema."""
    from graphql import get_introspection_query, graphql_sync

    # ActionHandlerRegistry наполняется при create_app; для standalone-экстракции
    # делаем то же самое (иначе auto-schema пустая).
    try:
        from src.backend.dsl.commands.setup import register_action_handlers

        register_action_handlers()
    except Exception as exc:  # noqa: BLE001
        _logger.warning("register_action_handlers failed: %s", exc)

    from src.backend.entrypoints.graphql.auto_schema import build_auto_strawberry_schema

    built = build_auto_strawberry_schema()
    schema = built.schema if hasattr(built, "schema") else built
    if schema is None:
        raise RuntimeError("GraphQL auto-schema не построена (нет actions?)")
    result = graphql_sync(schema._schema, get_introspection_query(descriptions=True))
    if result.errors:
        raise RuntimeError(f"GraphQL introspection failed: {result.errors[0]}")
    return {"__schema": result.data["__schema"]}  # type: ignore[index]


def extract_grpc() -> dict[str, Any]:
    """services/methods из auto proto-дескрипторов + явных protos."""
    services: list[dict[str, Any]] = []
    seen: set[str] = set()

    from src.backend.entrypoints.grpc.auto_servicer import build_auto_servicers

    for bundle in build_auto_servicers():
        for svc_name, svc_desc in bundle.pb2.DESCRIPTOR.services_by_name.items():
            if svc_name in seen:
                continue
            seen.add(svc_name)
            services.append(
                {
                    "name": svc_name,
                    "methods": [
                        {"name": m.name} for m in svc_desc.methods
                    ],
                }
            )

    # Явные protos (invoker/orders/files/orderkinds/users) — через их pb2-модули.
    from src.backend.entrypoints.grpc.protobuf import files_pb2, invoker_pb2, orders_pb2

    for pb2 in (invoker_pb2, orders_pb2, files_pb2):
        for svc_name, svc_desc in pb2.DESCRIPTOR.services_by_name.items():
            if svc_name in seen:
                continue
            seen.add(svc_name)
            services.append(
                {
                    "name": svc_name,
                    "methods": [
                        {"name": m.name} for m in svc_desc.methods
                    ],
                }
            )

    return {"services": services}


def extract_all(out_dir: Path) -> dict[str, str]:
    """Извлечь все три контракта; возвращает карту протокол → статус."""
    out_dir.mkdir(parents=True, exist_ok=True)
    status: dict[str, str] = {}

    for name, fn, filename in (
        ("REST", extract_rest, _REST_FILE),
        ("GraphQL", extract_graphql, _GRAPHQL_FILE),
        ("gRPC", extract_grpc, _GRPC_FILE),
    ):
        try:
            data = fn()
            (out_dir / filename).write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            status[name] = "OK"
        except Exception as exc:  # noqa: BLE001 — изоляция протоколов
            _logger.warning("contract extract %s failed: %s", name, exc)
            status[name] = f"FAILED: {exc}"
    return status


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Extract protocol contracts для contract_diff_gate"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(".baselines/contracts"),
        help="Целевая директория (default: .baselines/contracts)",
    )
    args = parser.parse_args()

    status = extract_all(args.out)
    for proto, st in status.items():
        print(f"[{'OK' if st == 'OK' else 'FAIL'}] {proto}: {st}")
    failed = [p for p, st in status.items() if st != "OK"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
