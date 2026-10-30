"""TDD-гейт для кластера W5 — документация волны 20 (ADR-0398…ADR-0401).

Каждый тест воспроизводит конкретный дефект из инвентаризации волны 20 и
проверяет соответствие документации **коду и репозиторию**, а не строковые
«магические» строки.

Дефекты (инвентаризация волны 20, кластер W5):

1. ``docs/workflows/index.md`` — не описан ADR-0398: пагинация event-log,
   fail-fast ``sub_flow`` в pg-runner, сброс retry-бюджета при admin-retry,
   per-item результаты ``for_each``;
2. ``docs/workflows/index.md`` — статус ``compensating`` объявлен в enum и в
   PG-enum, но его наблюдаемость (state-replay vs instance-store) не
   разграничена;
3. ``docs/explanation/capability_runtime.md`` — нет ADR-0400: capability-гейт
   AI-процессоров (``agent_dsl``) объявлялся, но не проверялся;
4. ``docs/reference/index.md`` — нет ссылки на каталог JSON-Schema
   процессоров (ADR-0399, ``make schemas``);
5. нет сводки «Известные ограничения и owner-задачи» (route.toml-миграция,
   lock-чанж, прод-значения, missing-secret baseline, ``PolicyMixin.cache()``
   шим, дубль OCR, DLQ-формулировка runbook'а);
6. ``docs/runbooks/hitl-stuck-workflow.md`` — SlaTracker подаётся как
   «не запущен», хотя ``WorkflowFacade`` не инстанцируется **нигде** в
   ``src/`` — это нереализованная возможность, а не сбой конфигурации;
7. ``CHANGELOG.md`` — волна 20 не отражена;
8. ``src/backend/infrastructure/README.md`` — счётчики модулей не соответствуют
   репозиторию;
9. ``docs/roadmap/PROD_READINESS_GAPS.md`` — owner-задача GAP-WF-4.5
   (SlaTracker) упомянута в трёх документах, но **не зафиксирована** в
   реестре gaps — ссылка ведёт в никуда.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DOCS = _PROJECT_ROOT / "docs"

_WORKFLOWS_INDEX = _DOCS / "workflows" / "index.md"
_CAPABILITY = _DOCS / "explanation" / "capability_runtime.md"
_TENANCY = _DOCS / "explanation" / "tenancy_model.md"
_REFERENCE_INDEX = _DOCS / "reference" / "index.md"
_HITL_RUNBOOK = _DOCS / "runbooks" / "hitl-stuck-workflow.md"
_GAPS = _DOCS / "roadmap" / "PROD_READINESS_GAPS.md"
_HOT_RELOAD = _DOCS / "config" / "HOT_RELOAD.md"
_SETTINGS_GUIDE = _DOCS / "config" / "SETTINGS_GUIDE.md"
_RPA_GUIDE = _DOCS / "rpa" / "RPA_GUIDE.md"
_CACHE_AUDIT = _DOCS / "cache" / "CACHE_DSL_AUDIT.md"
_CHANGELOG = _PROJECT_ROOT / "CHANGELOG.md"
_INFRA_README = _PROJECT_ROOT / "src" / "backend" / "infrastructure" / "README.md"

#: Сводка owner-задач волны 20.
_OWNER_TASKS = _DOCS / "roadmap" / "OWNER_TASKS.md"

#: ADR волны 20, которые обязаны быть отражены в документации.
_WAVE20_ADRS = ("0398", "0399", "0400", "0401")

#: Документы, в которых волна 20 обязана быть отражена.
_WAVE20_DOCS = (
    _WORKFLOWS_INDEX,
    _CAPABILITY,
    _TENANCY,
    _REFERENCE_INDEX,
    _HITL_RUNBOOK,
    _HOT_RELOAD,
    _SETTINGS_GUIDE,
    _RPA_GUIDE,
    _CACHE_AUDIT,
    _OWNER_TASKS,
)


def _read(path: Path) -> str:
    """Прочитать текст документа."""
    assert path.exists(), f"Документ не найден: {path}"
    return path.read_text(encoding="utf-8")


def _adr_dir() -> Path:
    """Каталог ADR."""
    return _DOCS / "adr"


# ---------------------------------------------------------------------------
# 1. docs/workflows/index.md — ADR-0398 (пагинация, sub_flow, retry-бюджет)
# ---------------------------------------------------------------------------


def test_workflows_index_documents_event_log_pagination() -> None:
    """(1) ADR-0398: пагинация event-log документирована."""
    text = _read(_WORKFLOWS_INDEX)
    assert "ADR-0398" in text, "docs/workflows/index.md не ссылается на ADR-0398"
    assert "after_seq" in text, (
        "не документирован cursor пагинации event-log (after_seq)"
    )
    assert "event_page_size" in text, (
        "не документирован параметр RunnerConfig.event_page_size — без него "
        "непонятно, откуда берётся размер страницы чтения"
    )


def test_workflows_index_documents_sub_flow_fail_fast() -> None:
    """(1) ADR-0398: ``sub_flow`` в pg-runner — fail-fast, а не «висение»."""
    text = _read(_WORKFLOWS_INDEX)
    assert "sub_flow" in text, "не описан шаг sub_flow"
    assert "sub_flow_unsupported" in text, (
        "не документирована причина отказа pg-runner'а (sub_flow_unsupported)"
    )


def test_workflows_index_documents_retry_budget_reset() -> None:
    """(1) ADR-0398: admin-retry сбрасывает retry-бюджет."""
    text = _read(_WORKFLOWS_INDEX)
    assert "attempts_reset" in text, (
        "не документирован сброс счётчика попыток при admin-retry "
        "(attempts_reset)"
    )


def test_workflows_index_documents_for_each_per_item_results() -> None:
    """(1) ADR-0398: per-item результаты ``for_each`` доступны в exchange."""
    text = _read(_WORKFLOWS_INDEX)
    assert "for_each_results" in text, (
        "не документирован ключ с per-item результатами for_each "
        "(for_each_results)"
    )


# ---------------------------------------------------------------------------
# 2. docs/workflows/index.md — наблюдаемость статуса compensating
# ---------------------------------------------------------------------------


def test_compensating_status_is_observable_and_documented() -> None:
    """(2) ``compensating`` есть в enum — и это отражено в схеме состояний."""
    from src.backend.core.domain.models.workflow_instance import WorkflowStatus

    statuses = {status.value for status in WorkflowStatus}
    assert "compensating" in statuses, (
        "ожидался статус compensating в WorkflowStatus — изменился контракт"
    )
    text = _read(_WORKFLOWS_INDEX)
    assert "compensating" in text, (
        "docs/workflows/index.md: схема состояний не содержит 'compensating', "
        "хотя статус есть в WorkflowStatus и в PG-enum workflow_instances"
    )


def test_compensating_is_not_claimed_as_instance_status() -> None:
    """(2) ``compensating`` НЕ пишется в ``workflow_instances.status``.

    Pg-runner переводит инстанс только в instance-level статусы, поэтому
    утверждение «статус compensating наблюдается у инстанса» было бы ложью.
    Наблюдаем он в materialized state и в ``workflow_state.state``.
    """
    from src.backend.core.domain.models.workflow_instance import WorkflowStatus

    text = _read(_WORKFLOWS_INDEX)
    assert "не пишется" in text or "не наблюдаем" in text, (
        "docs/workflows/index.md не разграничивает, где наблюдается "
        "compensating — читатель решит, что он виден в workflow_instances"
    )
    # Instance-level статусы, которые pg-runner реально пишет.
    instance_level = {
        status.value
        for status in WorkflowStatus
        if status is not WorkflowStatus.compensating
    }
    for status in instance_level:
        assert status in text, f"статус {status} не упомянут в схеме состояний"


def test_workflows_index_documents_workflow_metrics() -> None:
    """(1) ADR-0399: метрики pg-runner'а названы явно."""
    text = _read(_WORKFLOWS_INDEX)
    assert "ADR-0399" in text, "docs/workflows/index.md не ссылается на ADR-0399"
    for metric in (
        "workflow.step_duration",
        "workflow.step_retries",
        "workflow.compensation_total",
        "workflow.status",
    ):
        assert metric in text, f"не документирована метрика {metric}"


# ---------------------------------------------------------------------------
# 3. docs/explanation/capability_runtime.md — ADR-0400 (BLS-контроль agent_dsl)
# ---------------------------------------------------------------------------


def test_capability_runtime_documents_agent_dsl_gate() -> None:
    """(3) ADR-0400: capability-гейт AI-процессоров реально применяется."""
    text = _read(_CAPABILITY)
    assert "ADR-0400" in text, (
        "docs/explanation/capability_runtime.md не ссылается на ADR-0400"
    )
    assert "agent_dsl" in text, (
        "не описан agent_dsl — 13 классов объявляли required_capability"
    )
    assert "auth_check" in text, (
        "не указан канонический путь проверки (BaseProcessor.auth_check)"
    )


def test_agent_dsl_capability_gate_is_enforced_in_code() -> None:
    """(3) Код подтверждает: capability AI-процессоров проверяется до _run."""
    import inspect

    from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor

    source = inspect.getsource(BaseAIProcessor.process)
    assert "auth_check" in source, (
        "BaseAIProcessor.process() не вызывает auth_check — декларация "
        "required_capability снова без эффекта (ADR-0400)"
    )
    # Проверяем именно ВЫЗОВ, а не любое упоминание: в docstring осталось
    # историческое пояснение («раньше проверка шла обходным путём
    # ``_check_capability``»), это не дефект.
    assert "self._check_capability(" not in source, (
        "BaseAIProcessor.process() всё ещё вызывает обходной "
        "_check_capability — он не учитывает dsl_capability_gate_enabled"
    )


# ---------------------------------------------------------------------------
# 4. docs/reference/index.md — ссылка на схемы процессоров (ADR-0399)
# ---------------------------------------------------------------------------


def test_reference_index_links_processor_schemas() -> None:
    """(4) ADR-0399: каталог JSON-Schema процессоров доступен из reference."""
    text = _read(_REFERENCE_INDEX)
    assert "processors" in text, (
        "docs/reference/index.md не ссылается на каталог схем процессоров"
    )
    assert "ADR-0399" in text, "docs/reference/index.md не ссылается на ADR-0399"
    assert ( _DOCS / "reference" / "schemas" / "processors" ).is_dir(), (
        "каталог публикации схем процессоров отсутствует — "
        "make schemas (ADR-0399) не отработал"
    )


def test_reference_index_step_count_matches_catalog() -> None:
    """(4) Число шагов в доке совпадает с каталогом (ADR-0399)."""
    from src.backend.dsl.builders.step_catalog import builder_step_names

    steps = builder_step_names()
    assert steps, "каталог шагов пуст — число в доке не проверяемо"
    text = _read(_REFERENCE_INDEX)
    assert str(len(steps)) in text, (
        f"docs/reference/index.md не содержит актуального числа шагов каталога "
        f"({len(steps)})"
    )


# ---------------------------------------------------------------------------
# 4a. ADR-0400 / ADR-0401 — отражение в профильных доках
# ---------------------------------------------------------------------------


def test_tenancy_model_documents_snapshot_under_rls() -> None:
    """(4a) ADR-0400: snapshot с tenant-скоупом под RLS."""
    text = _read(_TENANCY)
    assert "ADR-0400" in text, "docs/explanation/tenancy_model.md не ссылается на ADR-0400"
    assert "set_config" in text, (
        "не документирована установка tenant-скоупа перед выборкой (set_config)"
    )
    assert "BYPASSRLS" in text, (
        "не указано ограничение: под RLS снимок покрывает один tenant"
    )


def test_hot_reload_documents_restart_required_sections() -> None:
    """(4a) ADR-0400: database.* / external_databases.* требуют рестарта."""
    text = _read(_HOT_RELOAD)
    assert "ADR-0400" in text, "docs/config/HOT_RELOAD.md не ссылается на ADR-0400"
    assert "RESTART_REQUIRED_SECTIONS" in text, (
        "не названа константа секций, требующих рестарта"
    )
    for section in ("database.*", "external_databases.*"):
        assert section in text, f"не указана секция {section}"


def test_settings_guide_documents_graphql_introspection() -> None:
    """(4a) ADR-0400: интроспекция — только при ключе И environment=development."""
    text = _read(_SETTINGS_GUIDE)
    assert "enable_introspection" in text, (
        "не документирован ключ graphql.enable_introspection"
    )
    assert "development" in text, (
        "не указано условие окружения для разрешения интроспекции"
    )


def test_rpa_guide_documents_runtime_wiring() -> None:
    """(4a) ADR-0401: RPA-runtime wiring через DI-провайдер."""
    text = _read(_RPA_GUIDE)
    assert "ADR-0401" in text, "docs/rpa/RPA_GUIDE.md не ссылается на ADR-0401"
    assert "get_browser_pool_provider" in text, (
        "не назван DI-провайдер RPA-runtime (get_browser_pool_provider)"
    )
    assert "audit_event" in text, (
        "не документирована эмиссия audit-событий процессоров"
    )


def test_cache_audit_documents_invalidation_and_quotas() -> None:
    """(4a) ADR-0401: инвалидация по всем уровням кэша и квоты файлов."""
    text = _read(_CACHE_AUDIT)
    assert "ADR-0401" in text, "docs/cache/CACHE_DSL_AUDIT.md не ссылается на ADR-0401"
    assert "create_cache_fallback_backends" in text, (
        "не названа фабрика fallback-уровней кэша"
    )
    assert "quota" in text.lower(), "не документированы квоты файлов"


# ---------------------------------------------------------------------------
# 5. Сводка «Известные ограничения и owner-задачи»
# ---------------------------------------------------------------------------


def test_owner_tasks_summary_exists() -> None:
    """(5) Сводка owner-задач существует и озаглавлена."""
    assert _OWNER_TASKS.exists(), (
        f"Нет сводки owner-задач: {_OWNER_TASKS}. Ожидается раздел "
        "«Известные ограничения и owner-задачи»."
    )
    text = _read(_OWNER_TASKS)
    assert "Известные ограничения и owner-задачи" in text, (
        "в сводке owner-задач нет требуемого заголовка"
    )


@pytest.mark.parametrize(
    ("marker", "description"),
    [
        ("route.toml", "миграция route.toml под новый namespace"),
        ("ADR-0284", "ссылка на governance-правило ADR-0284 §1.1"),
        ("pillow", "lock-чанж: Pillow 13"),
        ("psycopg", "lock-чанж: psycopg[binary] → db_drivers"),
        ("HS256", "прод-значение: HS256 в prod"),
        ("allow_hosts", "прод-значение: WAF allow_hosts"),
        ("open_webui", "прод-значение: open_webui fallback"),
        ("replica_dsn", "прод-значение: replica_dsn=null"),
        ("missing-secret", "baseline missing-secret/missing-non-secret"),
        ("PolicyMixin.cache", "шим PolicyMixin.cache()"),
        ("ocr_processor", "дубль OCR-процессора"),
        ("pg_runner_backend.py:250", "pg_runner_backend.py:250 → NotImplementedError"),
        ("credit_pipeline", "activity-имена расширения credit_pipeline"),
        ("BYPASSRLS", "межtenant-снимок требует роли BYPASSRLS"),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_owner_tasks_summary_covers_inventory(marker: str, description: str) -> None:
    """(5) Каждая позиция инвентаризации волны 20 есть в сводке."""
    text = _read(_OWNER_TASKS)
    assert marker in text, f"в сводке owner-задач нет позиции: {description}"


def test_owner_tasks_summary_marks_ownership() -> None:
    """(5) Позиции, требующие владельца, помечены явно."""
    text = _read(_OWNER_TASKS)
    assert "требует владельца" in text, (
        "сводка owner-задач не содержит пометки «требует владельца» — "
        "непонятно, что можно закрыть самостоятельно"
    )


def test_owner_tasks_summary_dlq_formulation_is_correct() -> None:
    """(5) DLQ-runbook — про messaging; формулировка не смешивает его с workflow."""
    text = _read(_OWNER_TASKS)
    assert "messaging" in text, (
        "не разграничено: runbook DLQ относится к messaging, а не к workflow"
    )


# ---------------------------------------------------------------------------
# 6. docs/runbooks/hitl-stuck-workflow.md — SlaTracker честно «не реализовано»
# ---------------------------------------------------------------------------


def test_hitl_runbook_marks_sla_tracker_not_implemented() -> None:
    """(6) SlaTracker помечен «не реализовано», а не «не запущен»."""
    text = _read(_HITL_RUNBOOK)
    assert "SlaTracker" in text, "runbook не упоминает SlaTracker"
    assert "не реализовано" in text, (
        "runbook должен честно помечать SlaTracker как «не реализовано»"
    )
    assert "owner-задач" in text.lower(), (
        "runbook не ссылается на owner-задачу по SLA-алертингу"
    )


def test_workflow_facade_is_never_instantiated() -> None:
    """(6) ``WorkflowFacade`` не инстанцируется нигде в src/ — утверждение верно."""
    import ast

    instantiations: list[str] = []
    for path in (_PROJECT_ROOT / "src").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "WorkflowFacade"
            ):
                instantiations.append(str(path.relative_to(_PROJECT_ROOT)))
    assert not instantiations, (
        "WorkflowFacade инстанцируется в src/ — утверждение runbook'а "
        f"«не создан нигде» устарело: {instantiations}"
    )


def test_hitl_runbook_links_owner_tasks() -> None:
    """(6) Runbook ссылается на сводку owner-задач."""
    text = _read(_HITL_RUNBOOK)
    assert "OWNER_TASKS.md" in text, (
        "runbook не ссылается на сводку owner-задач (OWNER_TASKS.md)"
    )


# ---------------------------------------------------------------------------
# 7. CHANGELOG — волна 20
# ---------------------------------------------------------------------------


def test_changelog_has_wave20_section() -> None:
    """(7) CHANGELOG содержит раздел волны 20."""
    text = _read(_CHANGELOG)
    assert "Волна 20" in text, "CHANGELOG не содержит раздела «Волна 20»"
    for number in _WAVE20_ADRS:
        assert f"ADR-{number}" in text, f"CHANGELOG не упоминает ADR-{number}"


# ---------------------------------------------------------------------------
# 8. src/backend/infrastructure/README.md — счётчики модулей
# ---------------------------------------------------------------------------


def test_infra_readme_counts_match_repository() -> None:
    """(8) Счётчики модулей в README соответствуют репозиторию."""
    text = _read(_INFRA_README)
    infra = _PROJECT_ROOT / "src" / "backend" / "infrastructure"

    rows = dict(
        (name, int(count))
        for name, count in re.findall(r"\|\s*`([a-z_]+/)`\s*\|\s*(\d+)\s*\|", text)
    )
    assert rows, "README infrastructure не содержит таблицы подкаталогов"

    actual = {
        f"{child.name}/": sum(
            1
            for f in child.rglob("*.py")
            if "__pycache__" not in f.parts
        )
        for child in infra.iterdir()
        if child.is_dir() and child.name != "__pycache__"
    }
    assert set(rows) == set(actual), (
        "набор подкаталогов в README infrastructure не совпадает с "
        f"репозиторием: лишние {sorted(set(rows) - set(actual))}, "
        f"пропущенные {sorted(set(actual) - set(rows))}"
    )
    wrong = {name: (rows[name], actual[name]) for name in rows if rows[name] != actual[name]}
    assert not wrong, "счётчики .py-файлов в README infrastructure неверны: " + str(
        wrong
    )


def test_infra_readme_total_matches() -> None:
    """(8) Итог по .py-файлам совпадает с фактом."""
    text = _read(_INFRA_README)
    infra = _PROJECT_ROOT / "src" / "backend" / "infrastructure"
    actual_total = sum(
        1 for f in infra.rglob("*.py") if "__pycache__" not in f.parts
    )
    match = re.search(r"(\d+)\s*\.py-файл", text)
    assert match, "README infrastructure не содержит итогового счётчика .py-файлов"
    assert int(match.group(1)) == actual_total, (
        f"итог в README ({match.group(1)}) != факту ({actual_total})"
    )


# ---------------------------------------------------------------------------
# 9. Реестр gaps — owner-задача GAP-WF-4.5 зафиксирована
# ---------------------------------------------------------------------------


def test_gap_wf_4_5_is_registered_in_gaps_registry() -> None:
    """(9) GAP-WF-4.5 (SlaTracker) зафиксирована в реестре gaps."""
    text = _read(_GAPS)
    assert "GAP-WF-4.5" in text, (
        "GAP-WF-4.5 (SlaTracker) упоминается в трёх документах, но не "
        "зафиксирована в docs/roadmap/PROD_READINESS_GAPS.md — ссылка "
        "ведёт в никуда"
    )


# ---------------------------------------------------------------------------
# 10. Ссылки и ADR во всех изменённых документах
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "doc",
    _WAVE20_DOCS,
    ids=lambda path: path.name,
)
def test_referenced_adr_exists(doc: Path) -> None:
    """(10) Каждая упомянутая ADR существует в docs/adr/."""
    text = _read(doc)
    missing = [
        number
        for number in sorted(set(re.findall(r"ADR-(\d{4})", text)))
        if not list(_adr_dir().glob(f"{number}-*.md"))
    ]
    assert not missing, f"{doc.name}: ссылки на несуществующие ADR {missing}"


@pytest.mark.parametrize(
    "doc",
    _WAVE20_DOCS,
    ids=lambda path: path.name,
)
def test_relative_markdown_links_resolve(doc: Path) -> None:
    """(10) Относительные markdown-ссылки существуют."""
    text = _read(doc)
    broken: list[str] = []
    for target in re.findall(r"\]\((?!https?://|#)([^)\s]+)\)", text):
        path_part = target.split("#", 1)[0]
        if not path_part:
            continue
        if not (doc.parent / path_part).resolve().exists():
            broken.append(target)
    assert not broken, f"{doc.name}: битые ссылки {sorted(set(broken))}"


@pytest.mark.parametrize(
    "doc",
    _WAVE20_DOCS,
    ids=lambda path: path.name,
)
def test_referenced_src_paths_exist(doc: Path) -> None:
    """(10) Упомянутые в документах пути src/ и extensions/ существуют."""
    text = _read(doc)
    missing = [
        path
        for path in sorted(
            set(re.findall(r"(?:src|extensions)/[A-Za-z0-9_./-]+", text))
        )
        if not (_PROJECT_ROOT / path).exists()
    ]
    assert not missing, f"{doc.name}: ссылки на несуществующие пути {missing}"
