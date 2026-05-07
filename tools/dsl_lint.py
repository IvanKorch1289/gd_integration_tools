"""R2.6 — `dsl_lint`: статический валидатор DSL YAML routes.

Проверяет declarative DSL без поднятия pipeline-runtime:

* Required fields (`route_id`, `source`, `processors`).
* Каждый processor — публичный метод `RouteBuilder` (whitelist).
* Параметры процессора совместимы с сигнатурой метода
  (unknown kwargs → finding).
* Если рядом с YAML лежит ``route.toml`` (V11, ADR-043) — capability-check:
  processors, которые требуют capability (например ``http_call`` →
  ``net.outbound``), должны быть задекларированы в манифесте.

Запуск::

    uv run python tools/dsl_lint.py routes/my_route/main.dsl.yaml
    uv run python tools/dsl_lint.py routes/ --strict --json
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.backend.dsl.builder import RouteBuilder

__all__ = ("Finding", "lint_file", "lint_yaml", "main")


# Маппинг processor → требуемые capabilities (subset из ADR-044).
# Используется при наличии route.toml.
_PROCESSOR_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "http_call": ("net.outbound",),
    "soap_call": ("net.outbound",),
    "grpc_call": ("net.outbound",),
    "ws_publish": ("net.outbound",),
    "mq_publish": ("mq.publish",),
    "db_query_external": ("db.read",),
    "db_persist": ("db.write",),
    "secret_get": ("secrets.read",),
    "file_read": ("fs.read",),
    "file_write": ("fs.write",),
}


@dataclass(slots=True, frozen=True)
class Finding:
    """Одна проблема в YAML."""

    path: Path
    line: int
    rule: str
    message: str
    processor: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "line": self.line,
            "rule": self.rule,
            "message": self.message,
            "processor": self.processor,
        }


@dataclass(slots=True)
class _LintContext:
    """Контекст одного lint-прохода."""

    path: Path
    findings: list[Finding] = field(default_factory=list)
    declared_capabilities: set[str] = field(default_factory=set)


def _emit(
    ctx: _LintContext,
    *,
    rule: str,
    message: str,
    line: int = 0,
    processor: str | None = None,
) -> None:
    ctx.findings.append(
        Finding(
            path=ctx.path, line=line, rule=rule, message=message, processor=processor
        )
    )


def _load_route_toml(yaml_path: Path) -> set[str]:
    """Прочитать declared capabilities из соседнего ``route.toml``."""
    toml_path = yaml_path.parent / "route.toml"
    if not toml_path.is_file():
        return set()
    try:
        import tomllib

        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    declared = data.get("capabilities", []) or []
    if not isinstance(declared, list):
        return set()
    names: set[str] = set()
    for entry in declared:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            names.add(entry["name"])
    return names


def _public_methods() -> dict[str, inspect.Signature]:
    """Кэш публичных методов RouteBuilder с их сигнатурами."""
    methods: dict[str, inspect.Signature] = {}
    for name in dir(RouteBuilder):
        if name.startswith("_"):
            continue
        attr = getattr(RouteBuilder, name, None)
        if not callable(attr):
            continue
        try:
            methods[name] = inspect.signature(attr)
        except (TypeError, ValueError):
            continue
    return methods


_BUILDER_METHODS = _public_methods()


def _check_processor(ctx: _LintContext, spec: Any, line_hint: int) -> None:
    """Проверка одного processor-spec'а."""
    if isinstance(spec, str):
        proc_name = spec
        params: dict[str, Any] = {}
    elif isinstance(spec, dict):
        if len(spec) != 1:
            _emit(
                ctx,
                rule="invalid-processor-spec",
                message=f"processor must have exactly one key, got {list(spec.keys())}",
                line=line_hint,
            )
            return
        proc_name = next(iter(spec))
        raw_params = spec[proc_name]
        params = raw_params if isinstance(raw_params, dict) else {}
    else:
        _emit(
            ctx,
            rule="invalid-processor-spec",
            message=f"processor spec must be str or dict, got {type(spec).__name__}",
            line=line_hint,
        )
        return

    if proc_name not in _BUILDER_METHODS:
        _emit(
            ctx,
            rule="unknown-processor",
            message=f"'{proc_name}' is not a public RouteBuilder method",
            line=line_hint,
            processor=proc_name,
        )
        return

    sig = _BUILDER_METHODS[proc_name]
    sig_params = set(sig.parameters.keys()) - {"self"}
    has_kwargs = any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )
    if not has_kwargs:
        for p in params:
            if p not in sig_params:
                _emit(
                    ctx,
                    rule="unknown-param",
                    message=f"'{proc_name}' does not accept kwarg '{p}'",
                    line=line_hint,
                    processor=proc_name,
                )

    # capability check (если есть route.toml).
    required = _PROCESSOR_CAPABILITIES.get(proc_name, ())
    for cap in required:
        if ctx.declared_capabilities and cap not in ctx.declared_capabilities:
            _emit(
                ctx,
                rule="missing-capability",
                message=(
                    f"'{proc_name}' requires capability '{cap}' "
                    f"but route.toml declares only "
                    f"{sorted(ctx.declared_capabilities) or '[]'}"
                ),
                line=line_hint,
                processor=proc_name,
            )


def lint_yaml(yaml_text: str, path: Path | None = None) -> list[Finding]:
    """Анализ одного YAML-документа."""
    p = path or Path("<string>")
    ctx = _LintContext(path=p)
    if path is not None:
        ctx.declared_capabilities = _load_route_toml(path)

    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        line = getattr(getattr(exc, "problem_mark", None), "line", 0) + 1
        _emit(ctx, rule="yaml-syntax", message=str(exc), line=line)
        return ctx.findings

    if not isinstance(data, dict):
        _emit(ctx, rule="invalid-root", message="YAML root must be a mapping")
        return ctx.findings

    if not data.get("route_id"):
        _emit(ctx, rule="missing-field", message="missing required field: route_id")

    if not data.get("source"):
        _emit(ctx, rule="missing-field", message="missing required field: source")

    processors = data.get("processors")
    if not isinstance(processors, list):
        _emit(ctx, rule="invalid-processors", message="'processors' must be a list")
        return ctx.findings

    for idx, spec in enumerate(processors):
        _check_processor(ctx, spec, line_hint=idx + 1)

    return ctx.findings


def lint_file(path: Path) -> list[Finding]:
    """Анализ одного ``.yaml``/``.yml``."""
    if not path.is_file() or path.suffix not in {".yaml", ".yml"}:
        return []
    return lint_yaml(path.read_text(encoding="utf-8"), path=path)


def lint_paths(paths: list[Path]) -> list[Finding]:
    """Рекурсивный обход директорий + файлов."""
    findings: list[Finding] = []
    for p in paths:
        if p.is_dir():
            for child in sorted(list(p.rglob("*.yaml")) + list(p.rglob("*.yml"))):
                findings.extend(lint_file(child))
        else:
            findings.extend(lint_file(p))
    return findings


def main(argv: list[str] | None = None) -> int:
    """CLI entry-point."""
    parser = argparse.ArgumentParser(
        description="DSL YAML linter (R2.6) — capability-aware static validator"
    )
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true", help="JSON report")
    parser.add_argument("--strict", action="store_true", help="exit 1 if any findings")
    args = parser.parse_args(argv)

    findings = lint_paths(args.paths)

    if args.json:
        payload = {
            "summary": {
                "files_scanned": len({f.path for f in findings}),
                "findings": len(findings),
                "by_rule": _count_by_rule(findings),
            },
            "findings": [f.to_dict() for f in findings],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for f in findings:
            print(f"{f.path}:{f.line}: {f.rule}: {f.message}")
        print(
            f"\nTotal: {len(findings)} findings across "
            f"{len({f.path for f in findings})} files"
        )

    if args.strict and findings:
        return 1
    return 0


def _count_by_rule(findings: list[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.rule] = counts.get(f.rule, 0) + 1
    return counts


if __name__ == "__main__":
    sys.exit(main())
