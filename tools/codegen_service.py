"""Wave 5.1 — CLI для генерации service+repo+schema+action скелета.

Запуск::

    uv run python tools/codegen_service.py \\
        --name customers --domain core --crud --fields '{"first_name":"str","email":"str"}'

Создаёт:

* ``src/services/<domain>/<name>_service.py``  — сервис.
* ``src/infrastructure/repositories/<name>_repository.py`` — репозиторий.
* ``src/schemas/<name>.py`` — Pydantic-схемы.
* ``src/dsl/commands/<name>_actions.py`` — DSL-actions.

Не модифицирует существующие файлы (FileExistsError, если что-то уже есть).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.codegen_engine import CodegenEngine

ROOT = Path(__file__).resolve().parents[1]


def _to_pascal(name: str) -> str:
    """``customers`` → ``Customers``; ``order_items`` → ``OrderItems``."""
    return "".join(p.capitalize() for p in name.split("_"))


def _to_singular(name: str) -> str:
    """Грубая де-плюрализация: ``customers`` → ``customer``, ``boxes`` → ``box``."""
    if name.endswith("ies"):
        return name[:-3] + "y"
    if name.endswith("ses") or name.endswith("xes"):
        return name[:-2]
    if name.endswith("s") and not name.endswith("ss"):
        return name[:-1]
    return name


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI."""
    parser = argparse.ArgumentParser(description="Codegen service skeleton (Wave 5.1).")
    parser.add_argument("--name", required=True, help="snake_case имя сервиса (мн.ч.)")
    parser.add_argument("--domain", required=True, help="core | ai | integrations | ...")
    parser.add_argument("--crud", action="store_true", help="включить CRUD-методы")
    parser.add_argument(
        "--fields",
        default="{}",
        help='JSON {"field":"py_type"} для Create/Update схем',
    )
    parser.add_argument(
        "--model-class",
        default=None,
        help="имя SQLAlchemy-модели (default: PascalCase singular)",
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="разрешить перезапись существующих"
    )
    args = parser.parse_args(argv)

    name = args.name
    domain = args.domain
    singular = _to_singular(name)
    pascal_singular = _to_pascal(singular)
    pascal_plural = _to_pascal(name)
    fields = json.loads(args.fields) or {"name": "str"}
    model_class = args.model_class or pascal_singular

    eng = CodegenEngine()
    paths = {
        "service": ROOT / "src" / "services" / domain / f"{name}_service.py",
        "repository": ROOT / "src" / "infrastructure" / "repositories" / f"{name}_repository.py",
        "schema": ROOT / "src" / "schemas" / f"{name}.py",
        "action": ROOT / "src" / "dsl" / "commands" / f"{name}_actions.py",
    }

    common = {
        "name": name,
        "domain": domain,
        "entity": pascal_singular,
        "entity_short": singular,
        "class_name_short": pascal_singular,
        "model_class": model_class,
        "fields": fields,
    }

    for kind, target in paths.items():
        ctx = {
            **common,
            "class_name": (
                f"{pascal_plural}Service"
                if kind == "service"
                else f"{pascal_plural}Repository"
                if kind == "repository"
                else f"{pascal_singular}Schemas"
            ),
            "crud": args.crud if kind == "service" else False,
        }
        template = f"{kind}.py.j2"
        code = eng.render(template, **ctx)
        eng.write(target, code, overwrite=args.overwrite)
        sys.stdout.write(f"[codegen] wrote {target.relative_to(ROOT)}\n")

    sys.stdout.write(
        f"[codegen] OK {name} (domain={domain}, crud={args.crud}, fields={list(fields)})\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
