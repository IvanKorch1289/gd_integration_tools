"""Фасад SchemaImporter — OpenAPI/Postman → Pydantic + DSL YAML.

Usage:

    from app.tools.schema_importer import SchemaImporter

    importer = SchemaImporter()
    models_path, routes_path = importer.from_openapi(
        "petstore.yaml",
        models_out="src/schemas/auto/petstore.py",
        routes_out="config/routes/imported/petstore.yaml",
    )
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.tools.schema_importer.openapi_parser import parse_openapi
from app.tools.schema_importer.postman_parser import parse_postman
from app.tools.schema_importer.pydantic_gen import render_models
from app.tools.schema_importer.route_gen import write_routes_yaml

__all__ = ("SchemaImporter",)


class SchemaImporter:
    """Фасад для конвертации внешних спецификаций во внутренние артефакты."""

    default_models_dir: str = "src/schemas/auto"
    default_routes_dir: str = "config/routes/imported"

    def from_openapi(
        self,
        path: str | Path,
        *,
        models_out: str | Path | None = None,
        routes_out: str | Path | None = None,
    ) -> tuple[Path, Path]:
        """Парсит OpenAPI 3.x файл и генерирует Pydantic + YAML-routes.

        Returns:
            ``(models_path, routes_path)``.
        """
        parsed = parse_openapi(path)
        models_path = self._write_models(
            parsed=parsed, kind="OpenAPI", models_out=models_out, base_name=Path(path).stem
        )
        routes_path = self._write_routes(
            parsed=parsed, routes_out=routes_out, base_name=Path(path).stem
        )
        return models_path, routes_path

    def from_postman(
        self,
        path: str | Path,
        *,
        models_out: str | Path | None = None,
        routes_out: str | Path | None = None,
    ) -> tuple[Path, Path]:
        """Парсит Postman Collection v2.1 и генерирует артефакты."""
        parsed = parse_postman(path)
        models_path = self._write_models(
            parsed=parsed, kind="Postman", models_out=models_out, base_name=Path(path).stem
        )
        routes_path = self._write_routes(
            parsed=parsed, routes_out=routes_out, base_name=Path(path).stem
        )
        return models_path, routes_path

    # -- Internals ----------------------------------------------------

    def _write_models(
        self,
        *,
        parsed: dict[str, Any],
        kind: str,
        models_out: str | Path | None,
        base_name: str,
    ) -> Path:
        out = Path(models_out) if models_out else Path(self.default_models_dir) / f"{base_name}.py"
        out.parent.mkdir(parents=True, exist_ok=True)
        schemas = parsed.get("schemas") or {}
        code = render_models(
            models=schemas, source=parsed.get("source", "unknown"), kind=kind
        )
        out.write_text(code, encoding="utf-8")
        return out

    def _write_routes(
        self,
        *,
        parsed: dict[str, Any],
        routes_out: str | Path | None,
        base_name: str,
    ) -> Path:
        out = (
            Path(routes_out)
            if routes_out
            else Path(self.default_routes_dir) / f"{base_name}.yaml"
        )
        return write_routes_yaml(parsed=parsed, out_path=out)
