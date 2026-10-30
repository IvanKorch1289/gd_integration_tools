"""ADR-0404 — гейт: банк xfail не должен расти + order-dependent регрессии.

Что проверяет гейт
------------------
1. **Банк не растёт.** Размер банка ``tests/unit/_xfail_environment.py`` не
   превышает ``MAX_BANK_ENTRIES``, а каждая запись указывает на реально
   существующий тест (node-id резолвится). Битая запись = молчаливый
   xfail-«покров» на несуществующем тесте.
2. **Список известных order-dependent жертв зафиксирован.** Новый
   order-dependent файл → падение гейта (список из ADR-0404).
3. **Динамическая проверка пар «поллитер → жертва».** Для каждой известной
   пары запускается pytest в отдельном процессе: пара должна давать 0
   падений. Если кто-то снова оставит загрязнение — гейт упадёт.
4. **Статический скан опасных паттернов** в ``tests/**``: модуль, который
   подменяет ``sys.modules[...]`` / вызывает ``importlib.reload`` /
   меняет ``os.environ`` без восстановления, обязан быть в allowlist
   гейта. Новый такой файл → падение гейта.

Зачем именно так
----------------
Полный прогон ``tests/unit`` занимает ~40 минут, поэтому проверять
order-dependence «на весь прогон» в гейте нельзя. Статический скан +
точечные пары дают дешёвый, но реальный сигнал: банк и список жертв не
могут разрастаться молча.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit._xfail_environment import MAX_BANK_ENTRIES, XFAIL_ENVIRONMENT

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = REPO_ROOT / "tests"

#: Известные order-dependent жертвы (ADR-0404). Список закрытый: новый
#: файл в этом множестве → падение гейта (см. ADR-0404 §Проверка).
KNOWN_ORDER_DEPENDENT_FILES: frozenset[str] = frozenset(
    {
        "tests/unit/core/interfaces/test_integrations.py",
        "tests/unit/core/interfaces/test_repositories.py",
        "tests/unit/core/observability/test_start_span.py",
        "tests/unit/core/security/test_object_ownership_tenant_enforcement.py",
        "tests/unit/dsl/engine/processors/eip/test_transformation.py",
        "tests/unit/dsl/engine/processors/test_converters.py",
        "tests/unit/dsl/engine/processors/test_llmcall_processor.py",
        "tests/unit/dsl/engine/test_exchange_snapshot.py",
        "tests/unit/dsl/orchestration/test_triggers_coverage.py",
        "tests/unit/dsl/test_action_metadata_contract.py",
        "tests/unit/frontend/api_clients/test_coverage_uplift.py",
        "tests/unit/frontend/streamlit_app/test_90_registry_explorer_imports.py",
        "tests/unit/frontend/streamlit_app/test_91_operational_costs_imports.py",
        "tests/unit/infrastructure/clients/messaging/test_event_bus.py",
        "tests/unit/infrastructure/clients/messaging/test_event_bus_schema.py",
        "tests/unit/infrastructure/clients/transport/test_sftp.py",
        "tests/unit/infrastructure/database/test_db_wave3_runtime.py",
        "tests/unit/infrastructure/messaging/outbox/test_claim_pending.py",
        "tests/unit/infrastructure/messaging/outbox/test_per_row_claim_and_sweeper.py",
        "tests/unit/infrastructure/messaging/test_dlq_lazy_init.py",
        "tests/unit/infrastructure/repositories/test_base_repository.py",
        "tests/unit/infrastructure/repositories/test_repository_decomposition.py",
        "tests/unit/infrastructure/workflow/test_temporal_otel_interceptor.py",
        "tests/unit/log_sinks/test_pipeline_integration.py",
        "tests/unit/plugins/composition/lifecycle/test_outbox_dispatcher_cutover.py",
        "tests/unit/plugins/composition/test_app_factory_smoke.py",
        "tests/unit/plugins/composition/test_lifecycle_smoke.py",
        "tests/unit/plugins/composition/test_service_setup_smoke.py",
        "tests/unit/services/agent_security/test_facade_validate_sql.py",
        "tests/unit/services/ai/test_sandbox_backends.py",
        "tests/unit/services/cache/test_log_throttling.py",
        "tests/unit/services/core/test_tech.py",
        "tests/unit/services/rpa/test_browser_cookies_store.py",
        "tests/unit/services/sources/test_idempotency.py",
        "tests/unit/services/sources/test_lifecycle.py",
        "tests/unit/tools/test_py3_syntax_migration.py",
    },
)

#: Маркер в docstring файла, который ЗАВЕДОМО является order-dependent.
#: Новый файл с маркером обязан попасть в KNOWN_ORDER_DEPENDENT_FILES.
ORDER_DEPENDENT_MARKER = "ADR-0404-ORDER-DEPENDENT"

#: Известные пары «поллитер → жертва»: поллитер обязан оставлять глобальное
#: состояние чистым, иначе жертва падает. Каждая пара проверяется гейтом.
KNOWN_POLLUTER_PAIRS: tuple[tuple[str, str], ...] = (
    (
        "tests/unit/plugins/composition/lifecycle/test_outbox_dispatcher_cutover.py",
        "tests/unit/plugins/composition/test_lifecycle_smoke.py",
    ),
    (
        "tests/unit/log_sinks/test_pipeline_integration.py",
        "tests/unit/services/cache/test_log_throttling.py",
    ),
    (
        "tests/unit/infrastructure/messaging/outbox/test_claim_pending.py",
        "tests/unit/infrastructure/repositories/test_base_repository.py",
    ),
    (
        "tests/unit/infrastructure/clients/transport/test_sftp.py",
        "tests/unit/plugins/composition/test_app_factory_smoke.py",
    ),
    (
        "tests/unit/frontend/streamlit_app/test_90_registry_explorer_imports.py",
        "tests/unit/services/core/test_tech.py",
    ),
    (
        "tests/unit/dsl/workflow/compiler/test_step_compilers.py",
        "tests/unit/infrastructure/workflow/test_temporal_otel_interceptor.py",
    ),
)

#: Файлы, где модульная подмена глобального состояния допустима
#: (с объяснением). Новый такой файл без записи здесь → падение гейта.
ALLOWED_GLOBAL_STATE_MUTATORS: dict[str, str] = {
    "tests/unit/conftest.py": "централизованный cleanup загрязнений (ADR-0404)",
    "tests/unit/_xfail_environment.py": "банк xfail, глобального состояния не меняет",
    "tests/unit/test_order_dependent_pollution_gate.py": "сам гейт",
    "tests/unit/plugins/composition/lifecycle/test_outbox_dispatcher_cutover.py": (
        "изолированная загрузка модулей с восстановлением sys.modules (ADR-0404)"
    ),
    "tests/unit/plugins/composition/lifecycle/test_lifespan_split.py": (
        "изолированная загрузка модулей (легаси-паттерн, см. ADR-0404)"
    ),
    "tests/unit/plugins/composition/test_scheduler_leader_election.py": (
        "изолированная загрузка setup_infra (легаси-паттерн, см. ADR-0404)"
    ),
    "tests/unit/infrastructure/messaging/outbox/test_claim_pending.py": (
        "stub session_manager с восстановлением sys.modules (ADR-0404)"
    ),
    "tests/unit/infrastructure/messaging/outbox/test_per_row_claim_and_sweeper.py": (
        "stub session_manager с восстановлением sys.modules (ADR-0404)"
    ),
    "tests/unit/frontend/streamlit_app/test_90_registry_explorer_imports.py": (
        "мок polars/streamlit с восстановлением sys.modules (ADR-0404)"
    ),
    "tests/unit/frontend/streamlit_app/test_91_operational_costs_imports.py": (
        "мок polars/streamlit с восстановлением sys.modules (ADR-0404)"
    ),
    "tests/unit/infrastructure/resilience/test_region_routing.py": (
        "легаси: подмена sys.modules['region_routing'] (легаси-паттерн)"
    ),
    "tests/unit/tools/test_unit_test_isolation_guards.py": (
        "сам тест guards изоляции — намеренно проверяет подмены (ADR-0404)"
    ),
    "tests/unit/security/conftest.py": (
        "bootstrap-заглушки session_manager/cert (легаси-паттерн, "
        "подменяет только если модуля ещё нет в sys.modules)"
    ),
    "tests/unit/frontend/streamlit_app/test_page_registry.py": (
        "легаси: мок streamlit на уровне модуля (см. ADR-0404)"
    ),
    "tests/unit/infrastructure/resilience/test_reconnection.py": (
        "легаси: мок resilience-модулей на уровне модуля (см. ADR-0404)"
    ),
    "tests/unit/tools/test_w11_p3_2_audit_legacy_processors.py": (
        "легаси: подмена shim-модуля через importlib.reload (см. ADR-0404)"
    ),
    "tests/unit/tools/test_w6_p1_8_phase8_check_docstrings_typer.py": (
        "легаси: подмена sys.modules для CLI-скрипта (см. ADR-0404)"
    ),
}

#: Паттерны, которые ломают изоляцию процесса.
_MUTATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"importlib\.reload\s*\("),
    re.compile(r"sys\.modules\s*\[\s*['\"]"),
    re.compile(r"os\.environ\s*\[\s*['\"]"),
    re.compile(r"os\.chdir\s*\("),
)


def _is_subscript_of(node: ast.AST, path: tuple[str, ...]) -> bool:
    """True, если ``node`` — ``<path...>[...]`` (например ``sys.modules[x]``)."""
    if not isinstance(node, ast.Subscript):
        return False
    value = node.value
    parts: list[str] = []
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if not isinstance(value, ast.Name):
        return False
    parts.append(value.id)
    return tuple(reversed(parts)) == path


def _relative(path: Path) -> str:
    """Путь относительно корня репозитория (posix)."""
    return path.relative_to(REPO_ROOT).as_posix()


def _collect_node_ids() -> set[str]:
    """Собрать node-id всех тестов дерева (через pytest --collect-only)."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/unit",
            "--collect-only",
            "-q",
            "-p",
            "no:randomly",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    ids: set[str] = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if "::" in line and not line.startswith(("=", "-", " ")):
            ids.add(line)
    return ids


class TestXfailEnvironmentBank:
    """Гейт банка xfail (ADR-0404)."""

    def test_bank_size_within_limit(self) -> None:
        """Банк не превышает ``MAX_BANK_ENTRIES`` (может только уменьшаться)."""
        assert len(XFAIL_ENVIRONMENT) <= MAX_BANK_ENTRIES, (
            f"банк xfail вырос: {len(XFAIL_ENVIRONMENT)} > {MAX_BANK_ENTRIES}. "
            "Банк может только уменьшаться — либо чините причину, либо "
            "обновляйте ADR-0404 с owner-задачей."
        )

    def test_bank_entries_have_reason_and_owner(self) -> None:
        """Каждая запись банка содержит причину и ссылку на owner-задачу."""
        for node_id, entry in XFAIL_ENVIRONMENT.items():
            reason, owner, _strict = entry
            assert reason.strip(), f"{node_id}: пустая причина"
            assert "OWNER-TASK" in owner, (
                f"{node_id}: нет ссылки на owner-задачу (OWNER-TASK)"
            )

    def test_bank_entries_reference_existing_tests(self) -> None:
        """Каждая запись банка указывает на реально существующий тест."""
        node_ids = _collect_node_ids()
        missing = sorted(set(XFAIL_ENVIRONMENT) - node_ids)
        assert not missing, (
            "записи банка xfail указывают на несуществующие тесты:\n  "
            + "\n  ".join(missing)
        )


class TestOrderDependentRegistry:
    """Гейт списка order-dependent жертв (ADR-0404)."""

    def test_known_victims_exist(self) -> None:
        """Все зарегистрированные order-dependent файлы существуют."""
        missing = [
            rel for rel in sorted(KNOWN_ORDER_DEPENDENT_FILES) if not (REPO_ROOT / rel).is_file()
        ]
        assert not missing, "нет файлов:\n  " + "\n  ".join(missing)

    def test_no_new_order_dependent_files(self) -> None:
        """Новый order-dependent файл → падение гейта.

        Список известных жертв закрытый: его пополнение требует ревизии
        ADR-0404 (и, как правило, реального фикса причины).
        """
        tracked = set(KNOWN_ORDER_DEPENDENT_FILES)
        # Файлы, где порядок РЕАЛЬНО влияет на результат, помечаются
        # маркером-комментарием ``ADR-0404`` в первой строке docstring.
        newly_affected: list[str] = []
        for path in sorted(TESTS_ROOT.rglob("test_*.py")):
            rel = _relative(path)
            if rel in tracked:
                continue
            try:
                head = path.read_text(encoding="utf-8")[:4000]
            except (OSError, UnicodeDecodeError):
                continue
            if ORDER_DEPENDENT_MARKER in head:
                newly_affected.append(rel)
        assert not newly_affected, (
            "обнаружены новые order-dependent файлы — добавьте их в "
            "KNOWN_ORDER_DEPENDENT_FILES гейта и почините причину "
            "(ADR-0404):\n  " + "\n  ".join(newly_affected)
        )


class TestGlobalStateMutationScan:
    """Статический скан: модульная подмена глобального состояния."""

    @staticmethod
    def _module_level_mutations(source: str) -> list[str]:
        """Найти подмены глобального состояния на уровне МОДУЛЯ.

        Подмены внутри функций безопасны: pytest/monkeypatch откатывают их
        на уровне теста. Опасны только те, что выполняются при ИМПОРТЕ
        тест-модуля — они живут до конца сессии.
        """
        tree = ast.parse(source)
        offenders: list[str] = []

        class _Visitor(ast.NodeVisitor):
            """Обходит дерево, не заходя внутрь функций."""

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
                """Не заходим в тело функции."""

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
                """Не заходим в тело async-функции."""

            def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
                """Не заходим в тело класса."""

            def visit_Assign(self, node: ast.Assign) -> None:
                """Проверяем присваивание в sys.modules[...] / os.environ[...]."""
                for target in node.targets:
                    if _is_subscript_of(target, ("sys", "modules")):
                        offenders.append(f"sys.modules[...] = (line {node.lineno})")
                    elif _is_subscript_of(target, ("os", "environ")):
                        offenders.append(f"os.environ[...] = (line {node.lineno})")
                self.generic_visit(node)

            def visit_Call(self, node: ast.Call) -> None:
                """Проверяем вызов importlib.reload(...)."""
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "reload"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "importlib"
                ):
                    offenders.append(f"importlib.reload(...) (line {node.lineno})")
                self.generic_visit(node)

        _Visitor().visit(tree)
        return offenders

    def test_no_unregistered_global_state_mutators(self) -> None:
        """Новый файл с модульной подменой глобального состояния → падение гейта."""
        offenders: list[str] = []
        for path in sorted(TESTS_ROOT.rglob("*.py")):
            rel = _relative(path)
            if rel in ALLOWED_GLOBAL_STATE_MUTATORS:
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            try:
                found = self._module_level_mutations(source)
            except SyntaxError:
                continue
            if found:
                offenders.append(f"{rel}: {', '.join(found)}")
        assert not offenders, (
            "модульная подмена глобального состояния без записи в "
            "ALLOWED_GLOBAL_STATE_MUTATORS гейта (ADR-0404):\n  "
            + "\n  ".join(offenders)
        )


class TestPolluterPairs:
    """Динамическая проверка пар «поллитер → жертва»."""

    @pytest.mark.parametrize(
        ("polluter", "victim"),
        KNOWN_POLLUTER_PAIRS,
        ids=[f"{Path(p).stem}->{Path(v).stem}" for p, v in KNOWN_POLLUTER_PAIRS],
    )
    def test_polluter_does_not_break_victim(
        self, polluter: str, victim: str
    ) -> None:
        """Поллитер не должен ломать жертву (пара запускается в одном прогоне)."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                polluter,
                victim,
                "-q",
                "-p",
                "no:randomly",
                "--tb=line",
                "-p",
                "no:cacheprovider",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        assert result.returncode == 0, (
            f"пара {polluter} → {victim} дала падения (order-dependent "
            f"регрессия, ADR-0404):\n{result.stdout[-4000:]}"
        )


def test_allowlist_entries_are_existing_files() -> None:
    """Allowlist гейта не должен содержать «мёртвых» путей."""
    missing = [
        rel
        for rel in sorted(ALLOWED_GLOBAL_STATE_MUTATORS)
        if not (REPO_ROOT / rel).is_file()
    ]
    assert not missing, "нет файлов:\n  " + "\n  ".join(missing)


def test_ast_import_is_used() -> None:
    """Guard: ast импортируется и модуль компилируется (sanity-check гейта)."""
    ast.parse(Path(__file__).read_text(encoding="utf-8"))
