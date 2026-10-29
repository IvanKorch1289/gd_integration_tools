"""TDD-гейт для кластера E — документация воркфлоу (волна 19).

Каждый тест воспроизводит конкретный дефект из проб ревью и проверяет
соответствие документации **коду**: реальные API, схемы, пути и файлы,
а не строковые «магические» строки.

Дефекты (проба ревью, кластер E):

1. ``docs/workflows/index.md`` — несуществующая архитектура
   (``src/backend/workflows/`` не существует);
2. ``docs/workflows/index.md`` — нерабочий API ``invoke_workflow(wait=...)``;
3. ``docs/tutorials/04_temporal_workflow.md`` — нерабочие сниппеты
   (``BranchSpec`` без ``name``, ``Activity`` → ImportError, YAML
   ``args: {applicant_id: ${input.id}}`` → ParserError, ``gateway_xor:`` в
   union шагов → ValidationError);
4. туториалы 04/05 — неверный REST-контракт (``/api/v1/invocations``
   требует ``action``+``payload``; ``mode: "async"`` не существует);
5. нет схемы состояний и раздела «как отладить»;
6. ``docs/explanation/tenancy_model.md`` — устаревшее «RLS — в Sprint 7+»;
7. ``docs/explanation/capability_runtime.md`` — нет ADR-0366 и db-гейта;
8. ``docs/rpa/RPA_GUIDE.md`` — нет prod-политики ADR-0393;
9. не документирован capability-гейт workflow-активити
   (``required_capabilities``);
10. ``docs/runbooks/hitl-stuck-workflow.md`` — неверный feature-flag,
    «default-OFF» вместо дефолта ``True``, несуществующий ``SlaTracker``;
11. ``docs/architecture/index.md`` — неотрендеренный ``$(basename ...)``;
12. ``docs/reference/index.md`` / ``docs/tutorials/index.md`` — заглушки без
    toctree;
13. ``CHANGELOG.md`` — волны 13–19 не отражены;
14. ``src/backend/infrastructure/README.md`` — неверное число файлов;
    ``docs/cookbooks/README.md`` — 5 cookbook'ов в таблице, 6 в каталоге;
15. терминология «шаг»/«этап» не зафиксирована.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import inspect
import re
import textwrap
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DOCS = _PROJECT_ROOT / "docs"

_WORKFLOWS_INDEX = _DOCS / "workflows" / "index.md"
_TUTORIAL_04 = _DOCS / "tutorials" / "04_temporal_workflow.md"
_TUTORIAL_05 = _DOCS / "tutorials" / "05_hitl_workflow.md"
_TENANCY = _DOCS / "explanation" / "tenancy_model.md"
_CAPABILITY = _DOCS / "explanation" / "capability_runtime.md"
_RPA_GUIDE = _DOCS / "rpa" / "RPA_GUIDE.md"
_HITL_RUNBOOK = _DOCS / "runbooks" / "hitl-stuck-workflow.md"
_ARCH_INDEX = _DOCS / "architecture" / "index.md"
_REFERENCE_INDEX = _DOCS / "reference" / "index.md"
_TUTORIALS_INDEX = _DOCS / "tutorials" / "index.md"
_CHANGELOG = _PROJECT_ROOT / "CHANGELOG.md"
_INFRA_README = _PROJECT_ROOT / "src" / "backend" / "infrastructure" / "README.md"
_COOKBOOKS_README = _DOCS / "cookbooks" / "README.md"

#: Кодовый блок в markdown: ```lang ... ```
_BLOCK_RE = re.compile(
    r"```(?P<lang>[A-Za-z0-9_+.-]*)[^\S\n]*\n(?P<body>.*?)```", re.DOTALL
)

#: Блоки, которым нужен живой Temporal-сервер — исполнять нельзя.
_EXTERNAL_SERVICE_MARKERS = ("TemporalWorkerPool", "pool.register_worker")


#: Пути, которые документ явно упоминает как НЕ существующие (анти-примеры).
_ALLOWED_MISSING = frozenset({"src/backend/workflows/"})


def _read(path: Path) -> str:
    """Прочитать текст документа."""
    assert path.exists(), f"Документ не найден: {path}"
    return path.read_text(encoding="utf-8")


def _blocks(path: Path, lang: str) -> list[str]:
    """Все кодовые блоки документа с указанным языком."""
    text = _read(path)
    return [
        match.group("body")
        for match in _BLOCK_RE.finditer(text)
        if match.group("lang") == lang
    ]


def _run_python(code: str, source: str) -> None:
    """Исполнить python-блок документа (sync либо async)."""
    namespace: dict[str, object] = {"__name__": "__docs_probe__"}
    if re.search(r"^\s*await\s", code, re.MULTILINE):
        wrapped = "async def _probe():\n" + textwrap.indent(code, "    ") + "\n"
        exec(compile(wrapped, source, "exec"), namespace)  # noqa: S102
        asyncio.run(namespace["_probe"]())  # type: ignore[operator]
        return
    exec(compile(code, source, "exec"), namespace)  # noqa: S102


def _local_imports(code: str) -> list[tuple[str, list[str]]]:
    """Импорты из локальных пакетов ``src.*`` / ``extensions.*``."""
    tree = ast.parse(code)
    found: list[tuple[str, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith(("src.", "extensions.")):
                found.append((node.module, [alias.name for alias in node.names]))
    return found


def _check_local_imports(code: str, source: str) -> None:
    """Убедиться, что все локальные импорты разрешаются (нет ImportError)."""
    for module_name, names in _local_imports(code):
        module = importlib.import_module(module_name)
        for name in names:
            assert hasattr(module, name), (
                f"{source}: `from {module_name} import {name}` — символ "
                f"не существует в модуле (ImportError в документе)"
            )


def _referenced_src_paths(text: str) -> set[str]:
    """Пути ``src/backend/...`` и ``extensions/...``, упомянутые в тексте."""
    return set(re.findall(r"(?:src|extensions)/[A-Za-z0-9_./-]+", text))


# ---------------------------------------------------------------------------
# 1. docs/workflows/index.md — архитектура
# ---------------------------------------------------------------------------


def test_workflows_index_references_only_existing_paths() -> None:
    """(1) Все упомянутые в docs/workflows/index.md пути существуют."""
    text = _read(_WORKFLOWS_INDEX)
    assert "src/backend/workflows" not in text, (
        "docs/workflows/index.md описывает несуществующий каталог "
        "src/backend/workflows — канон: infrastructure/workflow + dsl/workflow "
        "+ services/workflows + core/workflow"
    )
    missing = sorted(
        path
        for path in _referenced_src_paths(text)
        if path not in _ALLOWED_MISSING and not (_PROJECT_ROOT / path).exists()
    )
    assert not missing, (
        f"docs/workflows/index.md ссылается на несуществующие пути: {missing}"
    )


def test_workflows_index_documents_real_workflow_layers() -> None:
    """(1) Задокументированы все четыре реальных слоя workflow."""
    text = _read(_WORKFLOWS_INDEX)
    for layer in (
        "src/backend/infrastructure/workflow",
        "src/backend/dsl/workflow",
        "src/backend/services/workflows",
        "src/backend/core/workflow",
    ):
        assert layer in text, f"docs/workflows/index.md не упоминает слой {layer}"


# ---------------------------------------------------------------------------
# 2. docs/workflows/index.md — сигнатура invoke_workflow
# ---------------------------------------------------------------------------


def test_workflows_index_invoke_workflow_call_matches_real_signature() -> None:
    """(2) Вызов invoke_workflow в документе соответствует реальной сигнатуре."""
    from src.backend.dsl.builders.integration_core.workflow_mixin import (
        WorkflowOpsMixin,
    )

    real_params = set(inspect.signature(WorkflowOpsMixin.invoke_workflow).parameters)
    calls: list[ast.Call] = []
    for block in _blocks(_WORKFLOWS_INDEX, "python"):
        for node in ast.walk(ast.parse(block)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "invoke_workflow"
            ):
                calls.append(node)
    assert calls, "docs/workflows/index.md не содержит примера invoke_workflow"

    for call in calls:
        kwargs = {kw.arg for kw in call.keywords if kw.arg}
        assert kwargs <= real_params, (
            f"invoke_workflow(...): несуществующие параметры {sorted(kwargs - real_params)}; "
            f"реальная сигнатура: {sorted(real_params)}"
        )
        assert "wait" not in kwargs, (
            "invoke_workflow не имеет параметра wait (реальная сигнатура: "
            f"{sorted(real_params)})"
        )
        assert "timeout" not in kwargs, (
            "invoke_workflow не имеет параметра timeout (используется "
            "reply_timeout_seconds)"
        )


# ---------------------------------------------------------------------------
# 3. туториалы 04/05 — сниппеты должны работать
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_workflow_registry() -> None:
    """Очистить глобальный реестр workflow'ов (иначе повторная регистрация → ValueError)."""
    from src.backend.infrastructure.workflow.registry import workflow_registry

    workflow_registry.clear()
    yield
    workflow_registry.clear()


@pytest.mark.parametrize("doc", [_TUTORIAL_04, _TUTORIAL_05], ids=["04", "05"])
def test_tutorial_python_blocks_are_importable_and_executable(
    doc: Path, clean_workflow_registry: None
) -> None:
    """(3) Python-блоки туториалов парсятся, импортируются и исполняются."""
    blocks = _blocks(doc, "python")
    assert blocks, f"{doc.name}: нет python-блоков"

    for idx, block in enumerate(blocks):
        source = f"{doc.name}#python[{idx}]"
        ast.parse(block)  # синтаксис
        _check_local_imports(block, source)
        if any(marker in block for marker in _EXTERNAL_SERVICE_MARKERS):
            continue
        _run_python(block, source)


@pytest.mark.parametrize("doc", [_TUTORIAL_04, _TUTORIAL_05], ids=["04", "05"])
def test_tutorial_yaml_blocks_parse_as_workflow_declarations(doc: Path) -> None:
    """(3) YAML-блоки туториалов — валидные декларации workflow."""
    from src.backend.dsl.workflow.yaml_io import load_workflow_from_yaml

    blocks = _blocks(doc, "yaml")
    assert blocks, f"{doc.name}: нет yaml-блоков"

    for idx, block in enumerate(blocks):
        declaration = load_workflow_from_yaml(block)
        assert declaration.name
        assert declaration.steps, f"{doc.name}#yaml[{idx}]: пустой steps[]"


def test_tutorial_04_yaml_uses_supported_step_types() -> None:
    """(3) YAML туториала 04 использует поддерживаемые типы шагов union."""
    from typing import get_args, get_type_hints

    from src.backend.dsl.workflow.spec.workflow import WorkflowStep

    union = get_args(WorkflowStep)[0]
    supported = {
        get_args(get_type_hints(declaration)["type"])[0]
        for declaration in get_args(union)
    }
    for idx, block in enumerate(_blocks(_TUTORIAL_04, "yaml")):
        import yaml as pyyaml

        raw = pyyaml.safe_load(block)
        for step in raw.get("steps", []):
            assert "type" in step, (
                f"04_temporal_workflow.md#yaml[{idx}]: шаг без discriminator 'type' "
                f"({step!r})"
            )
            assert step["type"] in supported, (
                f"04_temporal_workflow.md#yaml[{idx}]: тип {step['type']!r} не входит "
                f"в union шагов {sorted(supported)}"
            )


# ---------------------------------------------------------------------------
# 4. REST-контракт туториалов
# ---------------------------------------------------------------------------


def test_invocation_api_contract_matches_documented_claim() -> None:
    """(4) /api/v1/invocations требует action+payload; mode='async' невалиден."""
    from pydantic import ValidationError

    from src.backend.schemas.invocation_api import InvocationRequestSchema

    with pytest.raises(ValidationError):
        InvocationRequestSchema.model_validate({"workflow": "x", "input": {}})
    with pytest.raises(ValidationError):
        InvocationRequestSchema.model_validate(
            {"action": "x", "payload": {}, "mode": "async"}
        )


@pytest.mark.parametrize("doc", [_TUTORIAL_04, _TUTORIAL_05], ids=["04", "05"])
def test_tutorial_documents_real_workflow_launch_endpoint(doc: Path) -> None:
    """(4) Запуск workflow документирован через admin-API, не через invocations."""
    from src.backend.entrypoints.api.v1.endpoints.admin_workflows import router

    paths = {route.path for route in router.routes}
    assert "/workflows/trigger/{workflow_name}" in paths

    text = _read(doc)
    assert "/api/v1/admin/workflows/trigger/" in text, (
        f"{doc.name}: не документирован реальный эндпоинт запуска workflow "
        "(POST /api/v1/admin/workflows/trigger/{workflow_name})"
    )
    assert '"workflow":' not in text or "/api/v1/invocations" not in text, (
        f"{doc.name}: workflow не запускается через /api/v1/invocations — "
        "эндпоинт требует action+payload и не понимает тело {workflow, input}"
    )
    assert '"mode": "async"' not in text, (
        f'{doc.name}: mode "async" отсутствует в InvocationModeLiteral — 422'
    )
    assert '"status": "completed"' not in text, (
        f'{doc.name}: статуса "completed" нет среди WorkflowStatus'
    )


# ---------------------------------------------------------------------------
# 5. схема состояний + «как отладить»
# ---------------------------------------------------------------------------


def test_workflows_index_documents_all_workflow_states() -> None:
    """(5) Все 8 статусов WorkflowStatus задокументированы."""
    from src.backend.core.domain.models.workflow_instance import WorkflowStatus

    text = _read(_WORKFLOWS_INDEX)
    missing = [status.value for status in WorkflowStatus if status.value not in text]
    assert not missing, (
        f"docs/workflows/index.md: не задокументированы статусы {missing}"
    )


def test_workflows_index_documents_debug_endpoints() -> None:
    """(5) Раздел «как отладить» содержит реальные admin-эндпоинты."""
    from src.backend.entrypoints.api.v1.endpoints.admin_workflows import router

    paths = {route.path for route in router.routes}
    text = _read(_WORKFLOWS_INDEX)
    for suffix in ("/events", "/retry", "/cancel", "/resume"):
        assert any(path.endswith(suffix) for path in paths), (
            f"в admin-router нет эндпоинта {suffix} — тест устарел"
        )
        assert suffix in text, (
            f"docs/workflows/index.md не описывает admin-эндпоинт {suffix}"
        )


# ---------------------------------------------------------------------------
# 6. tenancy_model.md — RLS
# ---------------------------------------------------------------------------


def _load_rls_migration() -> object:
    """Загрузить модуль миграции RLS (имя файла содержит дефис — не импортируется)."""
    import importlib.util

    path = (
        _PROJECT_ROOT
        / "src/backend/infrastructure/database/migrations/versions"
        / "2026_10_29_1200-e2f3a4b5c6d7_rls_all_tenant_tables.py"
    )
    assert path.exists(), f"миграция RLS не найдена: {path}"
    spec = importlib.util.spec_from_file_location("rls_migration_probe", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tenancy_model_documents_current_rls_state() -> None:
    """(6) tenancy_model.md отражает RLS на 9 таблицах + ORM/raw-guard/audit."""
    text = _read(_TENANCY)
    assert "Sprint 7" not in text, (
        "docs/explanation/tenancy_model.md устарел: «RLS — в Sprint 7+», "
        "а RLS уже на 9 таблицах"
    )
    assert "ADR-0383" in text and "ADR-0386" in text
    assert "2026_10_29_1200" in text, "не указана миграция RLS"

    rls_tables = (
        "workflow_instances",
        "workflow_state",
        "rule_engine_rulesets",
        "orders",
        "users",
        "files",
        "dsl_snapshots",
        "workflow_events",
        "orderkinds",
    )
    missing = [table for table in rls_tables if table not in text]
    assert not missing, f"tenancy_model.md: не перечислены RLS-таблицы {missing}"


def test_rls_migration_really_covers_nine_tables() -> None:
    """(6) Проба кода: в миграции RLS ровно 9 tenant-таблиц."""
    module = _load_rls_migration()
    assert len(module.RLS_TABLES) == 9  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 7. capability_runtime.md — ADR-0366 + db-гейт
# ---------------------------------------------------------------------------


def test_capability_runtime_documents_resolver_and_db_gate() -> None:
    """(7) capability_runtime.md описывает ADR-0366, db.read/db.write, ADR-0393."""
    text = _read(_CAPABILITY)
    assert "ADR-0366" in text, "не описан runtime-резолвер namespace (ADR-0366)"
    assert "ADR-0393" in text, "не описан db-capability-гейт (ADR-0393)"
    assert "db.read" in text and "db.write" in text
    assert "prod" in text, "не описана prod/staging-политика capability-гейта"


def test_capability_runtime_claims_match_profiles() -> None:
    """(7) Проба профилей: prod/staging — гейт включён, core-baseline выключен."""
    import yaml as pyyaml

    for profile in ("prod", "staging"):
        raw = pyyaml.safe_load(
            (_PROJECT_ROOT / "config_profiles" / f"{profile}.yml").read_text(
                encoding="utf-8"
            )
        )
        features = raw.get("features", raw)
        assert features["dsl_capability_gate_enabled"] is True, profile
        assert features["dsl_capability_core_baseline_enabled"] is False, profile


# ---------------------------------------------------------------------------
# 8. RPA_GUIDE.md — prod-политика
# ---------------------------------------------------------------------------


def test_rpa_guide_warns_about_prod_fail_closed_policy() -> None:
    """(8) RPA_GUIDE.md предупреждает о fail-closed политике в prod/staging."""
    text = _read(_RPA_GUIDE)
    lowered = text.lower()
    assert "prod" in lowered and "staging" in lowered, (
        "docs/rpa/RPA_GUIDE.md не описывает prod/staging-политику ADR-0393"
    )
    assert "fail-closed" in lowered or "fail closed" in lowered or "отклон" in lowered
    assert "ADR-0393" in text, "не указан ADR-0393"


# ---------------------------------------------------------------------------
# 9. capability-гейт workflow-активити
# ---------------------------------------------------------------------------


def test_workflow_activity_capability_gate_is_documented() -> None:
    """(9) required_capabilities workflow-активити документированы."""
    from src.backend.dsl.workflow.spec.activity_declarations import ActivityDeclaration

    assert "required_capabilities" in ActivityDeclaration.model_fields

    texts = "\n".join(
        _read(path) for path in (_WORKFLOWS_INDEX, _CAPABILITY, _TUTORIAL_04)
    )
    assert "required_capabilities" in texts, (
        "Capability-гейт workflow-активити (required_capabilities → "
        "activity_bridge) нигде не документирован"
    )


# ---------------------------------------------------------------------------
# 10. runbook HITL
# ---------------------------------------------------------------------------


def test_hitl_runbook_matches_real_feature_flag() -> None:
    """(10) Имя флага верное, дефолт — True (не default-OFF)."""
    from src.backend.core.config.features import feature_flags

    text = _read(_HITL_RUNBOOK)
    assert "feature_flags.hitl_panel_enabled" in text
    assert "feature_flag.hitl_panel_enabled" not in text
    assert "default-OFF" not in text, (
        "runbook утверждает default-OFF, а дефолт флага — True"
    )
    assert feature_flags.hitl_panel_enabled is True, (
        "дефолт hitl_panel_enabled изменился — обновить runbook"
    )


def test_hitl_runbook_marks_unimplemented_sla_tracker() -> None:
    """(10) SlaTracker помечен как не реализованный."""
    from src.backend.services.workflows import sla_alerting

    text = _read(_HITL_RUNBOOK)
    assert "SlaTracker" in text
    assert "не реализовано" in text.lower()
    assert sla_alerting.SlaTracker is not None


def test_sla_tracker_is_not_instantiated_in_src() -> None:
    """(10) Проба кода: SlaTracker нигде не инстанцируется."""
    import re as _re

    hits: list[str] = []
    for path in (_PROJECT_ROOT / "src").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if _re.search(r"SlaTracker\s*\(", text):
            hits.append(str(path.relative_to(_PROJECT_ROOT)))
    assert not hits, f"SlaTracker инстанцируется в {hits} — runbook устарел"


# ---------------------------------------------------------------------------
# 11. docs/architecture/index.md
# ---------------------------------------------------------------------------


def test_architecture_index_is_rendered_and_lists_real_docs() -> None:
    """(11) Нет shell-плейсхолдера; в toctree — реальные файлы каталога."""
    text = _read(_ARCH_INDEX)
    assert "$(basename" not in text, (
        "docs/architecture/index.md содержит неотрендеренный shell-плейсхолдер"
    )
    assert "toctree" in text, "docs/architecture/index.md без toctree"

    arch_dir = _DOCS / "architecture"
    existing = {path.stem for path in arch_dir.glob("*.md")} - {"index"}
    listed = set(re.findall(r"^\s*([A-Za-z0-9_-]+)\s*$", text, re.MULTILINE))
    missing = sorted(existing - listed)
    assert not missing, f"docs/architecture/index.md не перечисляет {missing}"


def test_architecture_has_workflow_architecture_page() -> None:
    """(11) Workflow-архитектура присутствует в docs/architecture/."""
    pages = {path.name for path in (_DOCS / "architecture").glob("*.md")}
    assert any("workflow" in name.lower() for name in pages), (
        f"в docs/architecture/ нет страницы про workflow-архитектуру: {sorted(pages)}"
    )


# ---------------------------------------------------------------------------
# 12. reference/index.md + tutorials/index.md
# ---------------------------------------------------------------------------


def test_reference_index_has_toctree() -> None:
    """(12) docs/reference/index.md — не заглушка."""
    text = _read(_REFERENCE_INDEX)
    assert "toctree" in text
    for page in (_DOCS / "reference").glob("*.md"):
        if page.name == "index.md":
            continue
        assert page.stem in text, f"docs/reference/index.md не ссылается на {page.name}"


def test_tutorials_index_has_toctree() -> None:
    """(12) docs/tutorials/index.md — не заглушка."""
    text = _read(_TUTORIALS_INDEX)
    assert "toctree" in text
    for page in (_DOCS / "tutorials").glob("*.md"):
        if page.name == "index.md":
            continue
        assert page.stem in text, f"docs/tutorials/index.md не ссылается на {page.name}"


# ---------------------------------------------------------------------------
# 13. CHANGELOG
# ---------------------------------------------------------------------------


def test_changelog_has_wave_13_19_section() -> None:
    """(13) CHANGELOG содержит раздел за 2026-10-28 с волнами 13–19."""
    text = _read(_CHANGELOG)
    assert "2026-10-28" in text, "CHANGELOG: нет раздела за 2026-10-28"
    for wave in range(13, 20):
        assert re.search(rf"волн[аы]\s*{wave}\b", text.lower()), (
            f"CHANGELOG не отражает волну {wave}"
        )


# ---------------------------------------------------------------------------
# 14. infrastructure/README.md + cookbooks/README.md
# ---------------------------------------------------------------------------


def test_infrastructure_readme_workflow_file_count_is_accurate() -> None:
    """(14) Число файлов workflow/ в README совпадает с реальным."""
    actual = len(
        [
            path
            for path in (_PROJECT_ROOT / "src/backend/infrastructure/workflow").rglob(
                "*.py"
            )
            if "__pycache__" not in path.parts
        ]
    )
    text = _read(_INFRA_README)
    match = re.search(r"^\|\s*`?workflow/`?\s*\|\s*(\d+)\s*\|", text, re.MULTILINE)
    assert match, "в src/backend/infrastructure/README.md нет строки про workflow/"
    assert int(match.group(1)) == actual, (
        f"README говорит {match.group(1)} .py в workflow/, фактически {actual}"
    )


def test_cookbooks_readme_lists_every_cookbook() -> None:
    """(14) docs/cookbooks/README.md перечисляет все cookbook'и каталога."""
    text = _read(_COOKBOOKS_README)
    missing = sorted(
        path.name
        for path in (_DOCS / "cookbooks").glob("*.md")
        if path.name != "README.md" and path.name not in text
    )
    assert not missing, f"docs/cookbooks/README.md не перечисляет {missing}"


# ---------------------------------------------------------------------------
# 15. терминология
# ---------------------------------------------------------------------------


def test_workflows_index_defines_step_and_stage_terms() -> None:
    """(15) Термины «шаг» (основной) и «этап» (крупная фаза) определены."""
    text = _read(_WORKFLOWS_INDEX)
    lowered = text.lower()
    assert "шаг" in lowered
    assert "этап" in lowered
    assert re.search(r"\*\*шаг\*\*|\*шаг\*|«шаг»", lowered), (
        "термин «шаг» не выделен как основной"
    )
    assert re.search(r"\*\*этап\*\*|\*этап\*|«этап»", lowered), (
        "термин «этап» не определён"
    )


# ---------------------------------------------------------------------------
# Дополнительные гейты: согласованность ссылок и типов шагов
# ---------------------------------------------------------------------------


def test_workflows_index_lists_exact_step_types() -> None:
    """Перечень типов шагов в docs/workflows/index.md == union WorkflowStep."""
    from typing import get_args, get_type_hints

    from src.backend.dsl.workflow.spec.workflow import WorkflowStep

    union = get_args(WorkflowStep)[0]
    supported = {
        get_args(get_type_hints(declaration)["type"])[0]
        for declaration in get_args(union)
    }
    text = _read(_WORKFLOWS_INDEX)
    missing = sorted(step_type for step_type in supported if step_type not in text)
    assert not missing, f"docs/workflows/index.md не упоминает типы шагов {missing}"


def test_workflows_index_yaml_examples_are_valid_declarations() -> None:
    """(9) YAML-примеры docs/workflows/index.md — валидные декларации workflow."""
    import yaml as pyyaml

    from src.backend.dsl.workflow.yaml_io import load_workflow_from_yaml

    blocks = _blocks(_WORKFLOWS_INDEX, "yaml")
    assert blocks, "docs/workflows/index.md не содержит YAML-примеров"
    for idx, block in enumerate(blocks):
        raw = pyyaml.safe_load(block)
        if "name" not in raw:
            # фрагмент (например, только steps[]) — оборачиваем в декларацию
            raw = {"name": "probe", "version": "1.0", **raw}
        declaration = load_workflow_from_yaml(pyyaml.safe_dump(raw, allow_unicode=True))
        assert declaration.steps, f"workflows/index.md#yaml[{idx}]: пустой steps[]"


@pytest.mark.parametrize(
    "doc",
    [
        _WORKFLOWS_INDEX,
        _TUTORIAL_04,
        _TUTORIAL_05,
        _TENANCY,
        _CAPABILITY,
        _RPA_GUIDE,
        _HITL_RUNBOOK,
        _ARCH_INDEX,
        _REFERENCE_INDEX,
        _TUTORIALS_INDEX,
        _DOCS / "architecture" / "workflow_architecture.md",
    ],
    ids=lambda path: path.name,
)
def test_relative_markdown_links_resolve(doc: Path) -> None:
    """Все относительные markdown-ссылки изменённых документов существуют."""
    text = _read(doc)
    broken: list[str] = []
    for target in re.findall(r"\]\((?!https?://|#)([^)\s]+)\)", text):
        path_part = target.split("#", 1)[0]
        if not path_part:
            continue
        resolved = (doc.parent / path_part).resolve()
        if not resolved.exists():
            broken.append(target)
    assert not broken, f"{doc.name}: битые ссылки {sorted(set(broken))}"


@pytest.mark.parametrize(
    "doc",
    [
        _WORKFLOWS_INDEX,
        _TUTORIAL_04,
        _TUTORIAL_05,
        _TENANCY,
        _CAPABILITY,
        _RPA_GUIDE,
        _HITL_RUNBOOK,
        _DOCS / "architecture" / "workflow_architecture.md",
    ],
    ids=lambda path: path.name,
)
def test_adr_references_exist(doc: Path) -> None:
    """Каждая упомянутая ADR существует в docs/adr/."""
    text = _read(doc)
    adr_dir = _DOCS / "adr"
    missing: list[str] = []
    for number in set(re.findall(r"ADR-(\d{4})", text)):
        if not list(adr_dir.glob(f"{number}-*.md")):
            missing.append(number)
    assert not missing, f"{doc.name}: ссылки на несуществующие ADR {sorted(missing)}"
