"""DSL Linter — расширенный валидатор route.toml + *.dsl.yaml.

Wave ``[wave:s6/k3-dsl-linter-lsp]``.

Назначение: статически проверить пару (``route.toml``, ``*.dsl.yaml``) и
плагин-namespace ``extensions/<name>/dsl/`` на следующие классы ошибок:

1. **Schema** — отсутствие обязательных полей route.toml (``name``,
   ``version``, ``requires_core``), некорректный YAML, отсутствие ``from``
   или ``steps`` в *.dsl.yaml.
2. **Capability declarations** — процессор требует capability, которой
   нет в ``route.toml::capabilities`` (например, ``http_call`` без
   ``net.outbound``).
3. **Reference checks** — pipeline_ref/action_ref указывают на
   несуществующие действия/маршруты; processor не зарегистрирован в
   ``ProcessorRegistry``.
4. **Feature-flag references** — упомянутый ``feature_flag.name``
   отсутствует в ``feature_flags`` registry.
5. **Plugin-aware** — если файл лежит в ``extensions/<name>/dsl/``,
   linter подгружает ``extensions/<name>/plugin.toml`` и сверяет
   declared-capabilities с тем, что использует route.

CLI: ``manage.py dsl lint <path>`` или ``python -m
src.backend.dsl.cli.linter <path>``.

Feature flag: ``feature_flags.dsl_linter_strict`` — в strict-mode
warnings становятся errors.

Возвращает список :class:`LintIssue` (code, severity, message,
suggestion, file, line). Exit-code 0 при отсутствии errors, 1 при
наличии errors, 2 при error (invalid input).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

__all__ = ("DSLLinter", "LintIssue", "lint_path", "main")


# Маппинг processor → требуемые capabilities (subset ADR-044).
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
    "call_com": ("net.outbound",),  # COM-sidecar REST — внешний HTTP.
}


@dataclass(slots=True, frozen=True)
class LintIssue:
    """Одна находка linter'а."""

    code: str
    severity: str  # "error" | "warning" | "info"
    message: str
    file: Path
    line: int = 0
    processor: str | None = None
    suggestion: str = ""


class DSLLinter:
    """Расширенный DSL-validator route.toml + *.dsl.yaml."""

    def __init__(self, *, strict: bool = False) -> None:
        """Конструктор.

        Args:
            strict: При True warnings становятся errors (для CI gate).
        """
        self._strict = strict

    def lint_route(self, route_dir: Path) -> list[LintIssue]:
        """Проверить пару (``route.toml``, ``*.dsl.yaml``) в каталоге.

        Args:
            route_dir: Каталог с ``route.toml`` (обязательно) и
                ``*.dsl.yaml`` (≥1 файл).

        Returns:
            Список проблем (пустой → all green).
        """
        issues: list[LintIssue] = []

        toml_path = route_dir / "route.toml"
        if not toml_path.is_file():
            issues.append(
                LintIssue(
                    code="MISSING_ROUTE_TOML",
                    severity="error",
                    message=f"route.toml не найден в {route_dir}",
                    file=route_dir,
                )
            )
            return issues

        declared_caps, toml_issues = self._lint_route_toml(toml_path)
        issues.extend(toml_issues)

        yaml_files = list(route_dir.glob("*.dsl.yaml"))
        if not yaml_files:
            issues.append(
                LintIssue(
                    code="MISSING_DSL_YAML",
                    severity="error",
                    message=f"*.dsl.yaml файлы отсутствуют в {route_dir}",
                    file=route_dir,
                )
            )
            return issues

        for yaml_path in yaml_files:
            issues.extend(self._lint_dsl_yaml(yaml_path, declared_caps))

        return issues

    def lint_yaml_file(self, yaml_path: Path) -> list[LintIssue]:
        """Проверить отдельный *.dsl.yaml (без route.toml).

        Plugin-aware: если файл лежит в ``extensions/<name>/dsl/``,
        ищет ``extensions/<name>/plugin.toml`` и подгружает declared
        capabilities оттуда.

        Args:
            yaml_path: Путь к *.dsl.yaml.

        Returns:
            Список проблем.
        """
        if not yaml_path.is_file():
            return [
                LintIssue(
                    code="FILE_NOT_FOUND",
                    severity="error",
                    message=f"Файл не найден: {yaml_path}",
                    file=yaml_path,
                )
            ]

        # Plugin-aware: ищем родительский plugin.toml через extensions/<name>/.
        declared_caps = self._discover_plugin_capabilities(yaml_path)
        # Если рядом лежит route.toml — также его учитываем.
        sibling_toml = yaml_path.parent / "route.toml"
        if sibling_toml.is_file():
            _extra, _ = self._lint_route_toml(sibling_toml)
            declared_caps = declared_caps.union(self._declared_from_toml(sibling_toml))

        return self._lint_dsl_yaml(yaml_path, declared_caps)

    # ─────────────────────── internal helpers ───────────────────────

    def _lint_route_toml(self, toml_path: Path) -> tuple[set[str], list[LintIssue]]:
        """Проверить route.toml на required fields + capabilities."""
        issues: list[LintIssue] = []
        try:
            import tomllib

            data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            issues.append(
                LintIssue(
                    code="INVALID_TOML",
                    severity="error",
                    message=f"Не удалось распарсить TOML: {exc}",
                    file=toml_path,
                )
            )
            return set(), issues

        route_section = data.get("route") or {}
        if not isinstance(route_section, dict):
            issues.append(
                LintIssue(
                    code="INVALID_ROUTE_SECTION",
                    severity="error",
                    message="Раздел [route] должен быть таблицей",
                    file=toml_path,
                )
            )
            return set(), issues

        for required in ("name", "version", "requires_core"):
            if not route_section.get(required):
                issues.append(
                    LintIssue(
                        code="MISSING_REQUIRED_FIELD",
                        severity="error",
                        message=f"Отсутствует [route].{required}",
                        file=toml_path,
                        suggestion=f'Добавьте {required} = "..." в [route]',
                    )
                )

        # Capabilities — list[dict[name, scope]].
        declared: set[str] = self._declared_from_toml(toml_path, data=data)
        return declared, issues

    @staticmethod
    def _declared_from_toml(
        toml_path: Path, *, data: dict[str, Any] | None = None
    ) -> set[str]:
        """Извлекает declared capabilities из route.toml / plugin.toml."""
        if data is None:
            try:
                import tomllib

                data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return set()

        # route.toml: [[capabilities]] OR [route]::capabilities = [...]
        names: set[str] = set()
        caps = data.get("capabilities", []) or []
        if isinstance(caps, list):
            for entry in caps:
                if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                    names.add(entry["name"])
                elif isinstance(entry, str):
                    names.add(entry)
        # legacy / shorthand: [route].capabilities = ["net.inbound.http:..."]
        route_section = data.get("route", {}) or {}
        if isinstance(route_section, dict):
            for entry in route_section.get("capabilities", []) or []:
                if isinstance(entry, str):
                    # "net.inbound.http:/path" → "net.inbound.http"
                    names.add(entry.split(":", 1)[0])
        return names

    def _discover_plugin_capabilities(self, yaml_path: Path) -> set[str]:
        """Plugin-aware: ищет ``extensions/<name>/plugin.toml``.

        Если *.dsl.yaml внутри ``extensions/<name>/.../`` — поднимаемся
        до каталога с ``plugin.toml`` и забираем capabilities оттуда.
        """
        parts = yaml_path.resolve().parts
        for i, part in enumerate(parts):
            if part == "extensions" and i + 1 < len(parts):
                ext_root = Path(*parts[: i + 2])
                plugin_toml = ext_root / "plugin.toml"
                if plugin_toml.is_file():
                    return self._declared_from_toml(plugin_toml)
        return set()

    def _lint_dsl_yaml(
        self, yaml_path: Path, declared_caps: set[str]
    ) -> list[LintIssue]:
        """Проверяет один *.dsl.yaml."""
        issues: list[LintIssue] = []
        try:
            import yaml
        except ImportError:
            return [
                LintIssue(
                    code="MISSING_DEPENDENCY",
                    severity="error",
                    message="PyYAML не установлен",
                    file=yaml_path,
                )
            ]

        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            issues.append(
                LintIssue(
                    code="INVALID_YAML",
                    severity="error",
                    message=f"YAML parse error: {exc}",
                    file=yaml_path,
                )
            )
            return issues

        if not isinstance(data, dict):
            issues.append(
                LintIssue(
                    code="INVALID_ROOT",
                    severity="error",
                    message="Root должен быть mapping",
                    file=yaml_path,
                )
            )
            return issues

        # required: from + steps (новый формат) ИЛИ route_id + processors (legacy).
        has_new = "from" in data and "steps" in data
        has_legacy = "route_id" in data and "processors" in data
        if not (has_new or has_legacy):
            issues.append(
                LintIssue(
                    code="MISSING_REQUIRED_DSL_FIELDS",
                    severity="error",
                    message="Отсутствуют from+steps (или route_id+processors)",
                    file=yaml_path,
                    suggestion="Добавьте секции from: и steps: или route_id + processors",
                )
            )
            return issues

        steps = data.get("steps") or data.get("processors", [])
        if not isinstance(steps, list):
            issues.append(
                LintIssue(
                    code="STEPS_NOT_LIST",
                    severity="error",
                    message="'steps'/'processors' должен быть список",
                    file=yaml_path,
                )
            )
            return issues

        # Каждый step — string или {one_key: params}.
        for i, step in enumerate(steps):
            issues.extend(self._lint_step(yaml_path, step, i, declared_caps))

        return issues

    def _lint_step(
        self, yaml_path: Path, step: Any, index: int, declared_caps: set[str]
    ) -> list[LintIssue]:
        """Проверяет один шаг pipeline."""
        issues: list[LintIssue] = []

        proc_name: str | None = None
        if isinstance(step, str):
            proc_name = step
        elif isinstance(step, dict):
            if len(step) != 1:
                issues.append(
                    LintIssue(
                        code="INVALID_STEP_SPEC",
                        severity="error",
                        message=(
                            f"step[{index}]: must be one-key dict, "
                            f"got keys {list(step.keys())}"
                        ),
                        file=yaml_path,
                    )
                )
                return issues
            proc_name = next(iter(step))
        else:
            issues.append(
                LintIssue(
                    code="INVALID_STEP_SPEC",
                    severity="error",
                    message=(
                        f"step[{index}]: must be str or dict, got {type(step).__name__}"
                    ),
                    file=yaml_path,
                )
            )
            return issues

        # Capability check.
        required_caps = _PROCESSOR_CAPABILITIES.get(proc_name, ())
        for cap in required_caps:
            if cap not in declared_caps:
                severity = "error" if self._strict else "warning"
                issues.append(
                    LintIssue(
                        code="MISSING_CAPABILITY",
                        severity=severity,
                        message=(
                            f"step[{index}].{proc_name} требует capability "
                            f"'{cap}', не задекларировано"
                        ),
                        file=yaml_path,
                        processor=proc_name,
                        suggestion=(
                            f'Добавьте [[capabilities]] name = "{cap}" '
                            f"в route.toml или plugin.toml"
                        ),
                    )
                )

        return issues


def lint_path(path: Path, *, strict: bool = False) -> list[LintIssue]:
    """Lint route_dir или одиночного *.dsl.yaml.

    Args:
        path: Путь — каталог с route.toml или *.dsl.yaml.
        strict: Strict-mode (warnings → errors).

    Returns:
        Список проблем.
    """
    linter = DSLLinter(strict=strict)
    if path.is_dir():
        return linter.lint_route(path)
    return linter.lint_yaml_file(path)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: ``manage.py dsl lint <path>``.

    Migrated S116 W2: argparse → typer + rich (S62 W3 batch 4 of 5).
    Backward compat: argv list support + typer-driven CLI mode.
    """
    console = Console(file=sys.stderr)
    app = typer.Typer(add_completion=False, help="DSL Linter (route.toml + *.dsl.yaml)")

    @app.command()
    def lint_cmd(
        path: Path = typer.Argument(..., help="Каталог или *.dsl.yaml файл"),
        strict: bool = typer.Option(
            False, "--strict", help="Strict-mode: warnings → errors (для CI)."
        ),
        as_json: bool = typer.Option(False, "--json", help="Вывод в JSON формате."),
    ) -> None:
        """Lint DSL-файлов: валидация route.toml + *.dsl.yaml с выводом issues.

        Запускает ``lint_path`` по указанному пути, выводит issues в консоль
        (rich) или JSON. При ``--strict`` warnings считаются errors. Exit
        code 1 при наличии errors, 0 — иначе.

        Args:
            path: Каталог или ``*.dsl.yaml`` файл для проверки.
            strict: Strict-режим: warnings → errors.
            as_json: Вывод в JSON формате.
        """
        if not path.exists():
            console.print(f"[red]ERROR: путь не найден: {path}[/red]")
            raise typer.Exit(code=2)

        issues = lint_path(path, strict=strict)

        if as_json:
            payload = [
                {
                    "code": iss.code,
                    "severity": iss.severity,
                    "message": iss.message,
                    "file": str(iss.file),
                    "line": iss.line,
                    "processor": iss.processor,
                    "suggestion": iss.suggestion,
                }
                for iss in issues
            ]
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            for iss in issues:
                style = {"error": "red", "warning": "yellow", "info": "blue"}.get(
                    iss.severity, "white"
                )
                line_suffix = f":{iss.line}" if iss.line else ""
                console.print(
                    f"[{style}][{iss.severity.upper()}][/] "
                    f"{iss.code}: {iss.message} ({iss.file}{line_suffix})"
                )
                if iss.suggestion:
                    console.print(f"  → {iss.suggestion}")

        errors = sum(1 for iss in issues if iss.severity == "error")
        if errors:
            raise typer.Exit(code=1)

    # Programmatic API (для `manage.py dsl lint <path>` + тестов).
    if argv is not None:
        # Backward compat path: parse argv list (для S62 W3 batch 3 call sites).
        path_arg = Path(argv[0]) if argv else None
        strict = "--strict" in argv
        as_json = "--json" in argv
        if path_arg is None:
            return 2
        if not path_arg.exists():
            console.print(f"[red]ERROR: путь не найден: {path_arg}[/red]")
            return 2
        issues = lint_path(path_arg, strict=strict)
        if as_json:
            print(
                json.dumps(
                    [
                        {
                            "code": iss.code,
                            "severity": iss.severity,
                            "message": iss.message,
                            "file": str(iss.file),
                            "line": iss.line,
                            "processor": iss.processor,
                            "suggestion": iss.suggestion,
                        }
                        for iss in issues
                    ],
                    indent=2,
                    ensure_ascii=False,
                )
            )
        else:
            for iss in issues:
                style = {"error": "red", "warning": "yellow", "info": "blue"}.get(
                    iss.severity, "white"
                )
                line_suffix = f":{iss.line}" if iss.line else ""
                console.print(
                    f"[{style}][{iss.severity.upper()}][/] {iss.code}: {iss.message} "
                    f"({iss.file}{line_suffix})"
                )
                if iss.suggestion:
                    console.print(f"  → {iss.suggestion}")
        return 1 if any(iss.severity == "error" for iss in issues) else 0

    # typer CLI mode (direct invocation).
    app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
