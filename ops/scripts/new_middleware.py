#!/usr/bin/env python3
"""Scaffold generator for new ASGI middleware (D136).

Usage:
    uv run python ops/scripts/new_middleware.py <snake_case_name> [--layer 1-4]

Examples:
    uv run python ops/scripts/new_middleware.py request_signature
    uv run python ops/scripts/new_middleware.py my_audit --layer 4
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "middleware_scaffold.py.tmpl"
TARGET_DIR = (
    Path(__file__).parent.parent.parent
    / "src" / "backend" / "entrypoints" / "middlewares"
)
TEST_DIR = (
    Path(__file__).parent.parent.parent
    / "tests" / "unit" / "entrypoints" / "middlewares"
)

LAYER_ORDERS = {
    1: (0, 249),
    2: (250, 499),
    3: (500, 749),
    4: (750, 999),
}


def snake_to_class(s: str) -> str:
    """snake_case → PascalCase + Middleware suffix."""
    parts = s.split("_")
    return "".join(p.capitalize() for p in parts) + "Middleware"


def main() -> int:
    parser = argparse.ArgumentParser(description="Scaffold new ASGI middleware")
    parser.add_argument("name", help="snake_case middleware name (e.g. request_signature)")
    parser.add_argument("--layer", type=int, choices=LAYER_ORDERS, default=3,
                        help="1=early exit, 2=request mgmt, 3=body/auth, 4=logging")
    parser.add_argument("--order", type=int, default=None,
                        help="Order within layer (default: mid-layer)")
    parser.add_argument("--description", default="TODO", help="One-line description")
    args = parser.parse_args()

    if not re.match(r"^[a-z][a-z0-9_]*$", args.name):
        print(f"ERROR: invalid name {args.name!r} — must be snake_case", file=sys.stderr)
        return 1

    layer_lo, layer_hi = LAYER_ORDERS[args.layer]
    order = args.order if args.order is not None else (layer_lo + layer_hi) // 2

    class_name = snake_to_class(args.name)
    template = TEMPLATE_PATH.read_text()
    code = (template
            .replace("<MIDDLEWARE_NAME>", args.name)
            .replace("<MIDDLEWARE_CLASS>", class_name)
            .replace("<LAYER>", str(args.layer))
            .replace("<ORDER>", str(order))
            .replace("<DESCRIPTION>", args.description))

    middleware_path = TARGET_DIR / f"{args.name}.py"
    middleware_path.write_text(code)
    print(f"OK Created {middleware_path}")

    test_path = TEST_DIR / f"test_{args.name}.py"
    test_path.write_text(f'''"""Tests for {class_name}."""
from __future__ import annotations
from unittest.mock import MagicMock


class Test{class_name}:
    def test_instantiates(self) -> None:
        from src.backend.entrypoints.middlewares.{args.name} import {class_name}
        mw = {class_name}(app=MagicMock())
        assert mw is not None
''')
    print(f"OK Created {test_path}")

    print(f"\nNext steps:")
    print(f"  1. Implement dispatch() in {middleware_path}")
    print(f"  2. Add tests in {test_path}")
    print(f"  3. Register in setup_middlewares.py (layer {args.layer}, order {order})")
    print(f"  4. Run: make lint && make type-check && make test")
    return 0


if __name__ == "__main__":
    sys.exit(main())
