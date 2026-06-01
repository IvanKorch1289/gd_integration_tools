"""Wave 5.2 — CLI для генерации только репозитория.

Полезно когда сервис уже существует, но нужно добавить отдельный репозиторий
поверх другой SQLAlchemy-модели.

Запуск::

    uv run python tools/codegen_repository.py --name customers --backend sqlalchemy
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.codegen_engine import CodegenEngine
from tools.codegen_service import _to_pascal, _to_singular

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI."""
    parser = argparse.ArgumentParser(description="Codegen repository (Wave 5.2).")
    parser.add_argument("--name", required=True, help="snake_case имя (мн.ч.)")
    parser.add_argument(
        "--backend",
        default="sqlalchemy",
        choices=["sqlalchemy"],
        help="Backend репозитория (пока только sqlalchemy).",
    )
    parser.add_argument("--model-class", default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    name = args.name
    pascal_singular = _to_pascal(_to_singular(name))
    pascal_plural = _to_pascal(name)
    model_class = args.model_class or pascal_singular

    eng = CodegenEngine()
    target = ROOT / "src" / "infrastructure" / "repositories" / f"{name}_repository.py"
    code = eng.render(
        "repository.py.j2",
        name=name,
        entity=pascal_singular,
        class_name=f"{pascal_plural}Repository",
        model_class=model_class,
    )
    eng.write(target, code, overwrite=args.overwrite)
    sys.stdout.write(
        f"[codegen-repo] OK {target.relative_to(ROOT)} (backend={args.backend})\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
