"""AST-aware проверка запрещённых паттернов PLAN.md V22 §5.

Покрытие (8 правил):
    1. orphan-create-task        — ``asyncio.create_task`` без TaskRegistry.
    2. threading-lock-in-async   — ``threading.Lock`` / ``threading.RLock``.
    3. ssl-insecure              — ``ssl.CERT_NONE`` или ``check_hostname=False``.
    4. inline-metric             — ``Counter``/``Histogram``/``Gauge``/``Summary``
                                   вне ``MetricsRegistry``.
    5. except-pass               — ``except [Exception]: pass``.
    6. yaml-load-unsafe          — PyYAML ``yaml.load()`` без ``safe_load``
                                   (``ruamel.yaml.YAML().load()`` игнорируется).
    7. pickle-loads              — ``pickle.load(s)`` / ``marshal.load(s)``.
    8. eval-exec                 — ``eval()`` / ``exec()`` без sandbox.

Исключения (false-positive filters):
    - **docstring-блоки**: AST не парсит содержимое строковых литералов,
      поэтому примеры в ``Пример::`` / ``.. code-block:: python`` не порождают
      Call-узлов и игнорируются автоматически;
    - **CLI selftest**: тело ``def _selftest()`` / ``def selftest()`` и весь
      блок ``if __name__ == "__main__":`` исключаются (определяются в pre-pass);
    - **ruamel.yaml**: ``from ruamel.yaml import YAML; yaml = YAML(); yaml.load(x)``
      не считается нарушением — pre-pass отслеживает только импортированные
      PyYAML-aliases (``import yaml`` / ``from yaml import load``);
    - **allowlist**: строка с комментарием ``# noqa: violation-check`` пропускается;
    - **MetricsRegistry**: файлы в ``core/metrics/`` и ``observability/metrics/``
      освобождены от правила 4 (это сами реестры).

Выходные коды:
    0 — нарушений не найдено;
    1 — обнаружены нарушения (``file:line: [rule] message``).

Использование:
    python tools/checks/check_grep_violations.py [--root src/backend] [--json]
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

# --- Правила (идентификаторы) ----------------------------------------------- #
RULE_ORPHAN_TASK = "orphan-create-task"
RULE_THREADING_LOCK = "threading-lock-in-async"
RULE_SSL_INSECURE = "ssl-insecure"
RULE_INLINE_METRIC = "inline-metric"
RULE_EXCEPT_PASS = "except-pass"  # noqa: S105 — идентификатор правила, не пароль
RULE_YAML_UNSAFE = "yaml-load-unsafe"
RULE_PICKLE_UNSAFE = "pickle-loads"
RULE_EVAL_EXEC = "eval-exec"


# --- Конфигурация ----------------------------------------------------------- #
METRIC_REGISTRY_ALLOWLIST_GLOBS: tuple[str, ...] = (
    "core/metrics/",
    "observability/metrics",
    "/metrics/registry",
)

NOQA_TOKEN = "# noqa: violation-check"  # noqa: S105 — allowlist-маркер, не пароль

PROMETHEUS_METRIC_NAMES: frozenset[str] = frozenset(
    {"Counter", "Histogram", "Gauge", "Summary"}
)

PYYAML_DEFAULT_NAMES: frozenset[str] = frozenset(
    {"load", "Loader", "FullLoader", "UnsafeLoader"}
)


# --- Модель ---------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Violation:
    """Одно нарушение запрещённого паттерна.

    Атрибуты:
        file: путь к исходному файлу (как строка для JSON-сериализации).
        line: номер строки 1-based.
        rule: идентификатор правила (см. константы ``RULE_*``).
        message: человекочитаемое описание со ссылкой на PLAN.md V22 §5.
    """

    file: str
    line: int
    rule: str
    message: str


# --- Вспомогательные функции ------------------------------------------------ #
def _attr_chain(node: ast.AST) -> str | None:
    """Свернуть ``Attribute``-цепочку в строку ``a.b.c``.

    Возвращает ``None``, если выражение не сводится к chain имён
    (например, содержит вызов или индекс посередине).
    """
    parts: list[str] = []
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _is_noqa(source_lines: list[str], lineno: int) -> bool:
    """Проверить allowlist-комментарий ``# noqa: violation-check`` на строке."""
    if 0 < lineno <= len(source_lines):
        return NOQA_TOKEN in source_lines[lineno - 1]
    return False


def _is_metric_registry_file(path: Path) -> bool:
    """Файл сам по себе является реестром метрик и освобождён от правила 4."""
    normalized = str(path).replace("\\", "/")
    return any(needle in normalized for needle in METRIC_REGISTRY_ALLOWLIST_GLOBS)


# --- Pre-pass: импорты + selftest-диапазоны --------------------------------- #
class _PreScanner:
    """Сбор контекста до основного обхода.

    Собирает:
        - aliases PyYAML (``import yaml as ...`` / ``from yaml import load``);
        - aliases ruamel.yaml (используются только для отчёта, к правилу
          не применяются — pre-pass для PyYAML и так не цепляет ruamel);
        - line-диапазоны selftest-блоков (``def _selftest`` и
          ``if __name__ == "__main__":``).
    """

    def __init__(self, tree: ast.AST) -> None:
        self.pyyaml_aliases: set[str] = set()
        self.ruamel_yaml_aliases: set[str] = set()
        self.selftest_ranges: list[tuple[int, int]] = []
        self._scan(tree)

    def _scan(self, tree: ast.AST) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self._scan_import(node)
            elif isinstance(node, ast.ImportFrom):
                self._scan_import_from(node)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in {"_selftest", "selftest", "_self_test"}:
                    end = node.end_lineno or node.lineno
                    self.selftest_ranges.append((node.lineno, end))
            elif isinstance(node, ast.If) and self._is_main_guard(node):
                end = node.end_lineno or node.lineno
                self.selftest_ranges.append((node.lineno, end))

    def _scan_import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "yaml":
                self.pyyaml_aliases.add(alias.asname or "yaml")
            elif alias.name.startswith("ruamel"):
                self.ruamel_yaml_aliases.add(alias.asname or alias.name.split(".")[0])

    def _scan_import_from(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if module == "yaml":
            for alias in node.names:
                if alias.name in PYYAML_DEFAULT_NAMES:
                    self.pyyaml_aliases.add(alias.asname or alias.name)
        elif module.startswith("ruamel.yaml") or module == "ruamel":
            for alias in node.names:
                self.ruamel_yaml_aliases.add(alias.asname or alias.name)

    @staticmethod
    def _is_main_guard(node: ast.If) -> bool:
        """Распознать ``if __name__ == "__main__":``."""
        test = node.test
        if not isinstance(test, ast.Compare):
            return False
        left = test.left
        if not (isinstance(left, ast.Name) and left.id == "__name__"):
            return False
        if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
            return False
        comp = test.comparators[0]
        return isinstance(comp, ast.Constant) and comp.value == "__main__"

    def is_selftest(self, lineno: int) -> bool:
        """Попадает ли строка в один из selftest-диапазонов."""
        return any(start <= lineno <= end for start, end in self.selftest_ranges)


# --- Основной visitor ------------------------------------------------------- #
class _ViolationVisitor(ast.NodeVisitor):
    """Обход AST и сбор нарушений 8 правил."""

    def __init__(
        self,
        file: Path,
        source_lines: list[str],
        prescan: _PreScanner,
        is_metric_registry: bool,
    ) -> None:
        self.file = file
        self.source_lines = source_lines
        self.prescan = prescan
        self.is_metric_registry = is_metric_registry
        self.violations: list[Violation] = []

    def _add(self, lineno: int, rule: str, message: str) -> None:
        if self.prescan.is_selftest(lineno):
            return
        if _is_noqa(self.source_lines, lineno):
            return
        self.violations.append(
            Violation(file=str(self.file), line=lineno, rule=rule, message=message)
        )

    # --- Call-узлы --------------------------------------------------------- #
    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        func = node.func

        if isinstance(func, ast.Name):
            self._check_name_call(func, node.lineno)
        elif isinstance(func, ast.Attribute):
            self._check_attribute_call(func, node.lineno)

        for kw in node.keywords:
            if (
                kw.arg == "check_hostname"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is False
            ):
                self._add(
                    kw.value.lineno,
                    RULE_SSL_INSECURE,
                    "check_hostname=False запрещён (V22 §5)",
                )

        self.generic_visit(node)

    def _check_name_call(self, func: ast.Name, lineno: int) -> None:
        """Вызовы вида ``foo(...)`` — eval/exec и импортированные метрики."""
        if func.id in {"eval", "exec"}:
            self._add(
                lineno,
                RULE_EVAL_EXEC,
                f"{func.id}() запрещён без явного sandbox (V22 §5)",
            )
            return

        if func.id in PROMETHEUS_METRIC_NAMES and not self.is_metric_registry:
            self._add(
                lineno,
                RULE_INLINE_METRIC,
                (
                    f"{func.id}() вне MetricsRegistry — регистрируйте метрику "
                    "через core.metrics.MetricsRegistry (V22 §5)"
                ),
            )

    def _check_attribute_call(self, func: ast.Attribute, lineno: int) -> None:
        """Вызовы вида ``a.b.c(...)``."""
        chain = _attr_chain(func)
        attr = func.attr

        if chain == "asyncio.create_task":
            self._add(
                lineno,
                RULE_ORPHAN_TASK,
                (
                    "asyncio.create_task без TaskRegistry — используйте "
                    "TaskRegistry.create_task (V22 §5)"
                ),
            )

        if chain in {"threading.Lock", "threading.RLock"}:
            self._add(
                lineno,
                RULE_THREADING_LOCK,
                (f"{chain}() — в async-коде используйте asyncio.Lock (V22 §5)"),
            )

        if chain in {"pickle.loads", "pickle.load", "marshal.loads", "marshal.load"}:
            self._add(
                lineno,
                RULE_PICKLE_UNSAFE,
                f"{chain}() для untrusted данных запрещён (V22 §5)",
            )

        if (
            attr == "load"
            and isinstance(func.value, ast.Name)
            and func.value.id in self.prescan.pyyaml_aliases
        ):
            self._add(
                lineno,
                RULE_YAML_UNSAFE,
                (
                    f"{func.value.id}.load() — используйте "
                    f"{func.value.id}.safe_load() (V22 §5)"
                ),
            )

        if (
            attr in PROMETHEUS_METRIC_NAMES
            and chain is not None
            and chain.startswith(("prometheus_client.", "prom."))
            and not self.is_metric_registry
        ):
            self._add(
                lineno,
                RULE_INLINE_METRIC,
                (
                    f"{chain}() вне MetricsRegistry — регистрируйте через "
                    "MetricsRegistry (V22 §5)"
                ),
            )

    # --- Attribute-узлы ---------------------------------------------------- #
    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        chain = _attr_chain(node)
        if chain == "ssl.CERT_NONE":
            self._add(node.lineno, RULE_SSL_INSECURE, "ssl.CERT_NONE запрещён (V22 §5)")
        self.generic_visit(node)

    # --- Except-узлы ------------------------------------------------------- #
    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:  # noqa: N802
        if self._is_bare_pass(node):
            self._add(
                node.lineno,
                RULE_EXCEPT_PASS,
                (
                    "except: pass проглатывает ошибку без логирования "
                    "(V22 §5; залогируйте или re-raise)"
                ),
            )
        self.generic_visit(node)

    @staticmethod
    def _is_bare_pass(node: ast.ExceptHandler) -> bool:
        """``except ...: pass`` без иного тела."""
        return len(node.body) == 1 and isinstance(node.body[0], ast.Pass)


# --- Pipeline --------------------------------------------------------------- #
def check_file(path: Path) -> list[Violation]:
    """Распарсить файл и вернуть список нарушений."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    source_lines = source.splitlines()
    prescan = _PreScanner(tree)
    visitor = _ViolationVisitor(
        file=path,
        source_lines=source_lines,
        prescan=prescan,
        is_metric_registry=_is_metric_registry_file(path),
    )
    visitor.visit(tree)
    return visitor.violations


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        "__pycache__",
        ".venv",
        "venv",
        ".git",
        "build",
        "dist",
        ".mypy_cache",
        ".ruff_cache",
    }
)


def iter_python_files(root: Path) -> Iterator[Path]:
    """Найти все ``.py`` под ``root``; ``root`` может быть файлом или директорией."""
    if root.is_file():
        if root.suffix == ".py":
            yield root
        return
    for path in root.rglob("*.py"):
        if _SKIP_DIRS & set(path.parts):
            continue
        yield path


def main(argv: list[str] | None = None) -> int:
    """CLI: обойти ``--root`` и вывести нарушения; exit 1 если найдены."""
    parser = argparse.ArgumentParser(
        description="AST-aware проверка запрещённых паттернов PLAN.md V22 §5"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("src/backend"),
        help="Директория или файл для проверки (default: src/backend)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Вывод в JSON вместо человекочитаемого формата",
    )
    args = parser.parse_args(argv)

    all_violations: list[Violation] = []
    for path in iter_python_files(args.root):
        all_violations.extend(check_file(path))

    if args.json:
        payload = [asdict(v) for v in all_violations]
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for v in all_violations:
            print(f"{v.file}:{v.line}: [{v.rule}] {v.message}")
        if all_violations:
            print(f"\n{len(all_violations)} violation(s) found.", file=sys.stderr)
        else:
            print("OK: no violations.")

    return 1 if all_violations else 0


if __name__ == "__main__":
    sys.exit(main())
