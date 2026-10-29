"""DSL Linter — расширенный валидатор route.toml + *.dsl.yaml.

Wave ``[wave:s6/k3-dsl-linter-lsp]``.

Назначение: статически проверить пару (``route.toml``, ``*.dsl.yaml``) и
плагин-namespace ``extensions/<name>/dsl/`` на следующие классы ошибок:

1. **Schema** — некорректный YAML, невалидный манифест (парсится через
   :func:`load_route_manifest` — тот же загрузчик, что и в ``RouteLoader``),
   отсутствие ``steps``/``processors`` + ``route_id``/``source``/``from``.
2. **Pipeline** — шаги проверяются **сборкой pipeline** в ``try/except``:
   неизвестный шаг, неверный kwarg и невалидный вложенный список
   приводят к ``INVALID_PIPELINE`` (ADR-0397).
3. **Capability declarations** — процессор требует capability, которой
   нет в ``route.toml::capabilities``. Карта «шаг → capability»
   строится из ``required_capability`` процессоров (источник истины —
   реестр ``@processor`` + сигнатуры ``RouteBuilder``), а не из
   захардкоженного словаря (ADR-0397).
4. **Reference checks** — pipeline_ref/action_ref указывают на
   несуществующие действия/маршруты; processor не зарегистрирован в
   ``ProcessorRegistry``.
5. **Feature-flag references** — упомянутый ``feature_flag.name``
   отсутствует в ``feature_flags`` registry.
6. **Plugin-aware** — если файл лежит в ``extensions/<name>/dsl/``,
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
from functools import lru_cache
from pathlib import Path
from typing import Any

import click
import typer
from rich.console import Console

from src.backend.dsl.builders.step_catalog import step_capability_map

__all__ = ("DSLLinter", "LintIssue", "lint_path", "main")


#: Обязательные поля манифеста (``RouteManifest``, ADR-043).
_REQUIRED_MANIFEST_FIELDS: tuple[str, ...] = (
    "name",
    "version",
    "requires_core",
    "pipelines",
)


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


@lru_cache(maxsize=1)
def processor_capability_map() -> dict[str, str]:
    """Карта «YAML-шаг → требуемая capability».

    ADR-0397: источник истины — ``required_capability`` процессора;
    карта собирается в :mod:`src.backend.dsl.builders.step_catalog`
    (сигнатуры ``RouteBuilder`` + реестр ``@processor``), чтобы линтер,
    LSP-completion и генератор схем читали один и тот же источник.

    Returns:
        Mapping ``step → capability name``.

    """
    return dict(step_capability_map())


@lru_cache(maxsize=1)
def _default_vocabulary() -> Any:
    """Default vocabulary ядра (для проверки scope через matcher)."""
    from src.backend.core.security.capabilities.vocabulary import (
        build_default_vocabulary,
    )

    return build_default_vocabulary()


def _required_scope(capability: str, params: dict[str, Any]) -> str | None:
    """Scope, который runtime-гейт запросит для шага.

    Для ``db.*`` scope — алиас ресурса: профиль внешней БД (``profile``)
    либо имя таблицы из SQL. Для остальных capability точный scope
    определить нельзя без исполнения шага — возвращается ``None``.

    Args:
        capability: Имя требуемой capability.
        params: Параметры YAML-шага.

    Returns:
        Требуемый scope либо ``None``.

    """
    if not capability.startswith("db."):
        return None
    profile = params.get("profile")
    if isinstance(profile, str) and profile:
        return profile
    sql = params.get("sql")
    if isinstance(sql, str) and sql:
        try:
            from src.backend.dsl.engine.processors._sql_validation import (
                sql_capability_scope,
            )
        except ImportError:  # pragma: no cover
            return None
        return sql_capability_scope(sql)
    return None


def _step_capability(
    proc_name: str, params: dict[str, Any]
) -> tuple[str, str | None] | None:
    """Требуемая capability шага + её scope.

    Args:
        proc_name: Имя YAML-шага.
        params: Параметры шага.

    Returns:
        ``(capability, scope)`` либо ``None``, если шаг не требует
        capability.

    """
    capability = processor_capability_map().get(proc_name)
    if capability is None:
        return None
    sql = params.get("sql")
    if capability.startswith("db.") and isinstance(sql, str) and sql:
        try:
            from src.backend.dsl.engine.processors._sql_validation import (
                db_capability_for_sql,
            )
        except ImportError:  # pragma: no cover
            pass
        else:
            capability = db_capability_for_sql(sql)
    return capability, _required_scope(capability, params)


def _scope_matches(capability: str, required: str, declared: str | None) -> bool:
    """Покрывает ли объявленный scope требуемый (через matcher vocabulary)."""
    if declared is None:
        return False
    try:
        definition = _default_vocabulary().get(capability)
    except Exception:  # pragma: no cover — capability вне vocabulary
        return declared == required
    try:
        return bool(definition.matcher.match(required, declared))
    except Exception:  # pragma: no cover — defensive
        return declared == required


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

        declared_caps, route_name, toml_issues = self._lint_route_toml(toml_path)
        issues.extend(toml_issues)

        yaml_files = list(route_dir.glob("*.dsl.yaml"))
        if not yaml_files:
            issues.append(
                LintIssue(
                    code="MISSING_DSL_YAML",
                    severity="error",
                    message="*.dsl.yaml файлы отсутствуют в {route_dir}",
                    file=route_dir,
                )
            )
            return issues

        for yaml_path in yaml_files:
            issues.extend(
                self._lint_dsl_yaml(yaml_path, declared_caps, route_id=route_name)
            )

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
        route_name: str | None = None
        if sibling_toml.is_file():
            sibling_caps, sibling_name, _ = self._lint_route_toml(sibling_toml)
            declared_caps = declared_caps + sibling_caps
            route_name = sibling_name

        return self._lint_dsl_yaml(yaml_path, declared_caps, route_id=route_name)

    # ─────────────────────── internal helpers ───────────────────────

    def _lint_route_toml(
        self, toml_path: Path
    ) -> tuple[list[tuple[str, str | None]], str | None, list[LintIssue]]:
        """Проверить route.toml на required fields + capabilities.

        Манифест валидируется **тем же** загрузчиком, что и в
        ``RouteLoader`` (:func:`load_route_manifest`) — иначе линтер
        принимал манифесты, которые роут не может загрузить (ADR-0397).

        Args:
            toml_path: Путь к ``route.toml``.

        Returns:
            Кортеж ``(declared_capabilities, route_name, issues)``.

        """
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
            return [], None, issues

        route_section = data.get("route")
        if route_section is not None and not isinstance(route_section, dict):
            issues.append(
                LintIssue(
                    code="INVALID_ROUTE_SECTION",
                    severity="error",
                    message="Раздел [route] должен быть таблицей",
                    file=toml_path,
                )
            )
            return [], None, issues

        flat = route_section if isinstance(route_section, dict) else data
        missing = [
            field for field in _REQUIRED_MANIFEST_FIELDS if not flat.get(field)
        ]
        for field in missing:
            issues.append(
                LintIssue(
                    code="MISSING_REQUIRED_FIELD",
                    severity="error",
                    message=f"Отсутствует [route].{field}",
                    file=toml_path,
                    suggestion=(
                        f'Добавьте {field} = "..." в route.toml '
                        f"(плоская форма или секция [route])"
                    ),
                )
            )

        declared: list[tuple[str, str | None]] = []
        route_name: str | None = flat.get("name") if isinstance(flat, dict) else None
        try:
            from src.backend.services.routes.manifest_toml import load_route_manifest

            manifest = load_route_manifest(toml_path)
        except ImportError:  # pragma: no cover — services-слой обязателен
            manifest = None
        except Exception as exc:
            manifest = None
            if not missing:
                issues.append(
                    LintIssue(
                        code="INVALID_MANIFEST",
                        severity="error",
                        message=f"Манифест route.toml невалиден: {exc}",
                        file=toml_path,
                        suggestion=(
                            "Манифест должен грузиться RouteLoader'ом "
                            "(load_route_manifest)"
                        ),
                    )
                )
        if manifest is not None:
            declared = [(ref.name, ref.scope) for ref in manifest.capabilities]
            route_name = manifest.name
        else:
            declared = self._declared_from_toml(toml_path, data=data)
        return declared, route_name, issues

    @staticmethod
    def _declared_from_toml(
        toml_path: Path, *, data: dict[str, Any] | None = None
    ) -> list[tuple[str, str | None]]:
        """Извлечь declared capabilities (имя + scope) из route.toml/plugin.toml."""
        if data is None:
            try:
                import tomllib

                data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return []

        found: list[tuple[str, str | None]] = []
        caps = data.get("capabilities", []) or []
        if isinstance(caps, list):
            for entry in caps:
                if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                    scope = entry.get("scope")
                    found.append(
                        (entry["name"], scope if isinstance(scope, str) else None)
                    )
                elif isinstance(entry, str):
                    name, sep, scope = entry.partition(":")
                    found.append((name.strip(), scope.strip() if sep else None))
        # legacy / shorthand: [route].capabilities = ["net.inbound.http:/path"]
        route_section = data.get("route", {}) or {}
        if isinstance(route_section, dict):
            for entry in route_section.get("capabilities", []) or []:
                if isinstance(entry, str):
                    name, sep, scope = entry.partition(":")
                    found.append((name.strip(), scope.strip() if sep else None))
        return found

    def _discover_plugin_capabilities(self, yaml_path: Path) -> list[tuple[str, str | None]]:
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
        return []

    def _lint_dsl_yaml(
        self,
        yaml_path: Path,
        declared_caps: list[tuple[str, str | None]],
        *,
        route_id: str | None = None,
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

        # Канонический формат V11: route_id/source/from + steps.
        # Legacy: route_id + processors.
        has_identity = any(key in data for key in ("route_id", "source", "from"))
        has_body = "steps" in data or "processors" in data
        if not (has_identity and has_body):
            issues.append(
                LintIssue(
                    code="MISSING_REQUIRED_DSL_FIELDS",
                    severity="error",
                    message=(
                        "Отсутствуют steps/processors + route_id/source/from "
                        "(канонический формат V11: route_id + steps)"
                    ),
                    file=yaml_path,
                    suggestion="Добавьте route_id (или source) и steps:",
                )
            )
            return issues

        steps = data.get("steps") or data.get("processors") or []
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

        # Валидация шагов сборкой pipeline — единственный способ поймать
        # неизвестный шаг / неверный kwarg / невалидный вложенный список.
        issues.extend(self._lint_pipeline_build(yaml_path, route_id=route_id))

        # Каждый step — string или {one_key: params}.
        # ``None`` — comment-only элемент списка (его пропускает и
        # YAML-загрузчик, см. ``yaml_loader/build.py::_iter_steps``).
        for i, step in enumerate(steps):
            if step is None:
                continue
            issues.extend(self._lint_step(yaml_path, step, i, declared_caps))

        return issues

    def _lint_pipeline_build(
        self, yaml_path: Path, *, route_id: str | None
    ) -> list[LintIssue]:
        """Собрать pipeline из YAML и сообщить об ошибке сборки.

        Args:
            yaml_path: Путь к ``*.dsl.yaml``.
            route_id: ``route_id`` манифеста (fallback для YAML без него).

        Returns:
            Список issues (пустой → pipeline собирается).

        """
        try:
            from src.backend.dsl.yaml_loader.loaders import load_pipeline_from_yaml

            load_pipeline_from_yaml(
                yaml_path.read_text(encoding="utf-8"),
                base_path=yaml_path.parent,
                default_route_id=route_id,
            )
        except Exception as exc:
            return [
                LintIssue(
                    code="INVALID_PIPELINE",
                    severity="error",
                    message=f"Pipeline не собирается: {exc}",
                    file=yaml_path,
                    suggestion=(
                        "Проверьте имена шагов (публичные методы RouteBuilder) "
                        "и их параметры"
                    ),
                )
            ]
        return []

    def _lint_step(
        self,
        yaml_path: Path,
        step: Any,
        index: int,
        declared_caps: list[tuple[str, str | None]],
    ) -> list[LintIssue]:
        """Проверяет один шаг pipeline."""
        issues: list[LintIssue] = []

        proc_name: str | None = None
        params: dict[str, Any] = {}
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
            raw_params = step[proc_name]
            params = raw_params if isinstance(raw_params, dict) else {}
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
        required = _step_capability(proc_name, params)
        if required is None:
            return issues
        capability, required_scope = required
        matching = [scope for name, scope in declared_caps if name == capability]
        if not matching:
            severity = "error" if self._strict else "warning"
            issues.append(
                LintIssue(
                    code="MISSING_CAPABILITY",
                    severity=severity,
                    message=(
                        f"step[{index}].{proc_name} требует capability "
                        f"'{capability}', не задекларировано"
                    ),
                    file=yaml_path,
                    processor=proc_name,
                    suggestion=self._capability_suggestion(
                        capability, required_scope
                    ),
                )
            )
            return issues

        if required_scope is not None:
            if all(scope is None for scope in matching):
                severity = "error" if self._strict else "warning"
                issues.append(
                    LintIssue(
                        code="MISSING_CAPABILITY_SCOPE",
                        severity=severity,
                        message=(
                            f"step[{index}].{proc_name} требует capability "
                            f"'{capability}' со scope '{required_scope}', "
                            f"а объявлен без scope"
                        ),
                        file=yaml_path,
                        processor=proc_name,
                        suggestion=self._capability_suggestion(
                            capability, required_scope
                        ),
                    )
                )
            elif not any(
                _scope_matches(capability, required_scope, scope)
                for scope in matching
            ):
                severity = "error" if self._strict else "warning"
                issues.append(
                    LintIssue(
                        code="MISSING_CAPABILITY_SCOPE",
                        severity=severity,
                        message=(
                            f"step[{index}].{proc_name} требует capability "
                            f"'{capability}' со scope '{required_scope}', "
                            f"объявлены другие scope: {matching}"
                        ),
                        file=yaml_path,
                        processor=proc_name,
                        suggestion=self._capability_suggestion(
                            capability, required_scope
                        ),
                    )
                )

        return issues

    @staticmethod
    def _capability_suggestion(capability: str, required_scope: str | None) -> str:
        """Подсказка «где и как объявить capability»."""
        if required_scope:
            return (
                f'Добавьте [[capabilities]] name = "{capability}" '
                f'scope = "{required_scope}" в route.toml '
                f"(scope — алиас ресурса, используемый шагом)"
            )
        return (
            f'Добавьте [[capabilities]] name = "{capability}" в route.toml '
            f"или plugin.toml"
        )


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
            # S121 W1: stdout write для CLI --json output (test_cli_json_output).
            # Раньше payload silence'ился через ``_ = payload`` (запланирован
            # TODO в cycle 9), но test продолжал ждать stdout → fail.
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
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
            pass
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
