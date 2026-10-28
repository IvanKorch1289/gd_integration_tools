"""Wave F.9 (опционально): проверка покрытия .env.example + ADR-0373.

Скрипт проходит по всем Pydantic Settings в ``src/backend/core/config/`` и
выясняет ожидаемые env-переменные (``<prefix>_<field>``). Затем
сверяет с реальным ``.env.example`` — список missing/extra переменных.

Правило ADR-0373 «в .env только секреты»
-----------------------------------------
``.env.example`` содержит **только** секреты и **только** с пустыми
значениями:

* несекретный ключ (например ``APP_PROFILE=dev``) — нарушение: значение
  живёт в ``config_profiles/{profile}.yml``;
* непустое значение секрета (даже плейсхолдер) — нарушение: шаблон не
  должен содержать значений.

Поведение:

* Exit 0 — всё покрыто, правило «только секреты» соблюдено.
* Exit 1 — есть переменные в Settings, не описанные в .env.example
  (warning-level: добавьте описание), либо нарушено правило ADR-0373
  (нарушения правила блокируют гейт во всех режимах).
* ``--strict`` — exit 1 ещё и если в .env.example есть лишние
  переменные, не используемые в Settings.
* ``--secrets-only`` — только правило ADR-0373 (быстрый CI-шаг).

Использование:

  python tools/check_env_example.py
  python tools/check_env_example.py --strict
  python tools/check_env_example.py --secrets-only

MINIMAX W6 P1-8 Phase 3 (cycle 153): мигрирован с ``argparse`` на ``typer`` +
``rich`` (libraries > custom, per ADR-0084). Сохранены: typer-native entry +
legacy ``main()`` callback для backward-compat с pre-existing scripts.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import NamedTuple

import typer
from rich.console import Console

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "src" / "backend" / "core" / "config"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"

# Канонические правила распознавания секретов (ADR-0373) — общие для
# ``check_env_example`` и ``config_audit``. ``sys.path`` дополняется, чтобы
# скрипт работал и как ``python tools/check_env_example.py``.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.config_secret_rules import is_secret_field, is_secret_name  # noqa: E402

app = typer.Typer(
    name="check-env-example",
    help="Проверка покрытия .env.example относительно Pydantic Settings.",
    add_completion=False,
)
_console = Console(stderr=True)


class EnvField(NamedTuple):
    """Описание env-переменной, собранной из Settings-модели.

    Attributes:
        env_var: Имя переменной окружения (``SEC_API_KEY``).
        field_name: Имя поля модели (``api_key``).
        annotation: Строковое представление аннотации типа.
        is_required: Поле без default (``Field(...)``).

    """

    env_var: str
    field_name: str
    annotation: str
    is_required: bool

    @property
    def is_secret(self) -> bool:
        """Считается ли поле секретом (по типу и/или имени)."""
        return is_secret_field(self.field_name, self.annotation)


class EnvExampleViolation(NamedTuple):
    """Нарушение правила ADR-0373 «в .env.example только секреты».

    Attributes:
        name: Имя переменной окружения.
        reason: ``non-secret`` (несекретный ключ) либо ``non-empty-secret``
            (у секрета задано значение).
        detail: Человекочитаемое описание нарушения.

    """

    name: str
    reason: str
    detail: str


def _is_class_var(annotation: ast.expr | None) -> bool:
    """Аннотировано ли поле как ``ClassVar[...]`` (не env-переменная)."""
    if annotation is None:
        return False
    return "ClassVar" in ast.unparse(annotation)


def _is_required(value: ast.expr | None) -> bool:
    """Поле без default (``Field(...)``) — обязательное."""
    if value is None:
        return True
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    if not isinstance(func, ast.Name) or func.id != "Field":
        return False
    if any(isinstance(arg, ast.Constant) and arg.value is ... for arg in value.args):
        return True
    if not value.args:
        return not any(
            kw.arg in {"default", "default_factory"} for kw in value.keywords
        )
    return False


def _extract_env_fields_from_file(path: Path) -> list[EnvField]:
    """Собирает env-переменные одного модуля с Settings-классами.

    Парсит AST, ищет классы с ``model_config = SettingsConfigDict(env_prefix=...)``
    и их поля-аннотации. Поля ``ClassVar[...]`` (например ``yaml_group``) и
    computed-поля в сбор **не** попадают — они не читаются из окружения
    (ADR-0373: ранее сбор давал 69 псевдо-переменных ``*_YAML_GROUP``).
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return []

    out: list[EnvField] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        prefix = ""
        for item in node.body:
            if isinstance(item, ast.Assign):
                for tgt in item.targets:
                    if (
                        isinstance(tgt, ast.Name)
                        and tgt.id == "model_config"
                        and isinstance(item.value, ast.Call)
                    ):
                        for kw in item.value.keywords:
                            if (
                                kw.arg == "env_prefix"
                                and isinstance(kw.value, ast.Constant)
                                and isinstance(kw.value.value, str)
                            ):
                                prefix = kw.value.value
        if not prefix:
            continue

        env_prefix = prefix.rstrip("_")
        for item in node.body:
            if not isinstance(item, ast.AnnAssign):
                continue
            if not isinstance(item.target, ast.Name):
                continue
            if _is_class_var(item.annotation):
                continue
            field_name = item.target.id
            out.append(
                EnvField(
                    env_var=f"{env_prefix}_{field_name}".upper(),
                    field_name=field_name,
                    annotation=ast.unparse(item.annotation),
                    is_required=_is_required(item.value),
                )
            )
    return out


def _extract_env_prefixes_from_file(
    path: Path,
) -> list[tuple[str, list[tuple[str, bool]]]]:
    """Совместимая обёртка: ``(env_prefix, [(field_name, is_required), ...])``.

    Историческая сигнатура гейта (используется существующими тестами);
    сама логика сбора живёт в :func:`_extract_env_fields_from_file`.
    """
    grouped: dict[str, list[tuple[str, bool]]] = {}
    for field in _extract_env_fields_from_file(path):
        env_prefix = field.env_var[: -len(field.field_name)]
        grouped.setdefault(env_prefix, []).append((field.field_name, field.is_required))
    return [(prefix, fields) for prefix, fields in grouped.items()]


def collect_env_fields(config_dir: Path = CONFIG_DIR) -> dict[str, EnvField]:
    """Собирает все env-переменные Settings-моделей: ``{ENV_VAR: EnvField}``."""
    fields: dict[str, EnvField] = {}
    for path in config_dir.rglob("*.py"):
        for field in _extract_env_fields_from_file(path):
            fields.setdefault(field.env_var, field)
    return fields


def collect_expected_env_vars(config_dir: Path = CONFIG_DIR) -> set[str]:
    """Собирает ожидаемые env-переменные из всех Pydantic Settings."""
    return set(collect_env_fields(config_dir))


def collect_required_secret_env_vars(config_dir: Path = CONFIG_DIR) -> set[str]:
    """Собирает required env vars с секретными именами/типами.

    Эти переменные ОБЯЗАНЫ быть в ``.env.example`` (иначе — bootstrap fallback).
    """
    return {
        field.env_var
        for field in collect_env_fields(config_dir).values()
        if field.is_required and field.is_secret
    }


def parse_env_example(path: Path = ENV_EXAMPLE) -> list[tuple[str, str]]:
    """Парсит ``.env.example`` и возвращает список ``(имя, значение)``.

    Комментарии и строки без ``=`` игнорируются; порядок файла сохраняется.
    """
    if not path.exists():
        return []
    pairs: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        pairs.append((name.strip(), value.strip()))
    return pairs


def collect_env_example_vars(path: Path = ENV_EXAMPLE) -> set[str]:
    """Парсит ``.env.example`` и возвращает множество описанных переменных."""
    return {name for name, _ in parse_env_example(path)}


def _is_secret_field_name(name: str) -> bool:
    """Эвристика: похоже ли имя поля на секрет (канонические правила)."""
    return is_secret_name(name)


def check_secrets_only(
    env_example: Path = ENV_EXAMPLE, config_dir: Path = CONFIG_DIR
) -> list[EnvExampleViolation]:
    """Проверяет правило ADR-0373 «в .env.example только секреты с пустыми значениями».

    Для каждой документированной переменной определяется, секрет ли она:
    по полю Settings-модели (если переменная известна) — с учётом типа
    (``SecretStr``) и имени, иначе — по каноническим правилам имени.

    Args:
        env_example: Путь к файлу-шаблону окружения.
        config_dir: Каталог с моделями настроек.

    Returns:
        Список нарушений (пустой список — шаблон корректен).

    """
    fields = collect_env_fields(config_dir)
    violations: list[EnvExampleViolation] = []
    for name, value in parse_env_example(env_example):
        field = fields.get(name)
        secret = field.is_secret if field is not None else is_secret_name(name)
        if not secret:
            violations.append(
                EnvExampleViolation(
                    name=name,
                    reason="non-secret",
                    detail=(
                        f"{name}: не секрет — значение должно жить в "
                        "config_profiles/{profile}.yml, а не в .env.example"
                    ),
                )
            )
        elif value:
            violations.append(
                EnvExampleViolation(
                    name=name,
                    reason="non-empty-secret",
                    detail=(
                        f"{name}: в шаблоне секрет должен иметь пустое значение "
                        f"(сейчас {value!r})"
                    ),
                )
            )
    return violations


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Также fail при наличии лишних переменных в .env.example.",
    ),
    matrix: bool = typer.Option(
        False,
        "--matrix",
        help="Расширенная matrix-проверка: required secret vars, unknown vars.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable JSON output."),
    secrets_only: bool = typer.Option(
        False,
        "--secrets-only",
        help=(
            "Только правило ADR-0373: в .env.example — только секреты "
            "и только с пустыми значениями."
        ),
    ),
    env_example: Path = typer.Option(
        ENV_EXAMPLE,
        "--env-example",
        help="Файл-шаблон окружения (по умолчанию: .env.example).",
    ),
) -> None:
    """Wave F.9: проверка покрытия .env.example + правило ADR-0373.

    W11 P0-3: добавлен --matrix для required-secret и unknown-vars проверок.
    Cycle 172 (ADR-0373): добавлена проверка «в .env только секреты» —
    нарушения блокируют гейт во всех режимах.
    """
    if ctx.invoked_subcommand is not None:
        return

    # ADR-0373: документированный ключ = секрет, значение секрета пустое.
    violations = check_secrets_only(env_example, CONFIG_DIR)

    expected = collect_expected_env_vars()
    documented = collect_env_example_vars(env_example)

    missing = sorted(expected - documented)
    extra = sorted(documented - expected)

    # W11 P0-3 matrix checks
    matrix_missing_secret: list[str] = []
    if matrix:
        required_secrets = collect_required_secret_env_vars()
        matrix_missing_secret = sorted(required_secrets - documented)

    rc = 1 if violations else 0
    if not secrets_only:
        if missing:
            # W11 P0-3: project convention — .env.example хранит ТОЛЬКО секреты,
            # остальные vars в config_profiles/{profile}.yml. Default — warning
            # (exit 0), --strict — fail (для проектов, где ВСЁ в .env.example).
            _console.print(
                f"[yellow][check-env-example][/] {len(missing)} переменных Settings не описаны в .env.example "
                f"(могут быть в config_profiles/*.yml — это норма для layered config):"
            )
            for v in missing[:20]:
                _console.print(f"  - {v}")
            if len(missing) > 20:
                _console.print(f"  ... и ещё {len(missing) - 20}")
            if strict:
                rc = 1
        if matrix and matrix_missing_secret:
            # Required secrets обязаны быть в .env.example — иначе bootstrap-fallback.
            _console.print(
                f"[red][check-env-example --matrix][/] "
                f"{len(matrix_missing_secret)} обязательных SECRET-переменных отсутствуют в .env.example "
                f"(риск bootstrap-fallback):"
            )
            for v in matrix_missing_secret[:20]:
                _console.print(f"  - {v}")
            if len(matrix_missing_secret) > 20:
                _console.print(f"  ... и ещё {len(matrix_missing_secret) - 20}")
            rc = 1
        if extra:
            _console.print(
                f"[yellow][check-env-example][/] {len(extra)} переменных в .env.example не используются в Settings:"
            )
            for v in extra[:20]:
                _console.print(f"  - {v}")
            if len(extra) > 20:
                _console.print(f"  ... и ещё {len(extra) - 20}")
            if strict:
                rc = 1

    if violations and not as_json:
        _console.print(
            f"[red][check-env-example][/] ADR-0373: нарушений правила "
            f"«в .env только секреты» — {len(violations)}:"
        )
        for violation in violations:
            _console.print(f"  - {violation.detail}")

    # JSON output (для CI integration)
    if as_json:
        import json as _json
        import sys as _sys

        payload = {
            "total_expected": len(expected),
            "total_documented": len(documented),
            "missing": missing,
            "extra": extra,
            "matrix_required_secrets_missing": matrix_missing_secret if matrix else [],
            "secrets_only_violations": [
                {
                    "name": violation.name,
                    "reason": violation.reason,
                    "detail": violation.detail,
                }
                for violation in violations
            ],
        }
        _sys.stdout.write(_json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    elif rc == 0:
        _console.print(
            f"[green][check-env-example][/] OK: {len(expected)} переменных обнаружено, "
            f"{len(documented)} в .env.example, "
            f"{len(extra)} unknown (use --strict для fail)."
        )
    raise typer.Exit(code=rc)


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI (backward-compat shim).

    Запускает typer app через typer.testing.CliRunner (для тестов)
    или sys.argv (для CLI invocation). Возвращает exit code.
    """
    if argv is not None:
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, argv)
        return result.exit_code
    # CLI invocation: typer сам подхватит sys.argv[1:]
    try:
        app()
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
