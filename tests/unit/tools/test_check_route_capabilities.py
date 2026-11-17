"""ADR-0430 — гейт обязательных capability-деклараций роутов и плагинов."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_TOOL = Path("tools/check_route_capabilities.py")
_ROUTES_DIR = Path("routes")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    """Запустить гейт в текущем репозитории."""
    return subprocess.run(
        [sys.executable, str(_TOOL), *args], capture_output=True, text=True, check=False
    )


def test_gate_passes_on_current_tree() -> None:
    """Текущее состояние репозитория проходит гейт (легаси — в baseline)."""
    result = _run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Capability-декларации: OK" in result.stdout


def test_gate_fails_for_new_manifest_without_declarations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Новый роут без ``net.inbound`` блокируется гейтом."""
    from tools import check_route_capabilities as gate

    routes = tmp_path / "routes"
    new_route = routes / "new_route"
    new_route.mkdir(parents=True)
    (new_route / "route.toml").write_text(
        '[route]\nname = "new_route"\nversion = "0.1.0"\n', encoding="utf-8"
    )

    monkeypatch.setattr(gate, "_ROUTE_DIR", routes)
    monkeypatch.setattr(gate, "_PLUGIN_DIR", tmp_path / "plugins")
    monkeypatch.setattr(gate, "_BASELINE_PATH", tmp_path / "baseline.txt")

    code = gate.main([])
    assert code == 1


def test_gate_accepts_declared_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Роут с декларацией ``net.inbound`` проходит."""
    from tools import check_route_capabilities as gate

    routes = tmp_path / "routes"
    new_route = routes / "good_route"
    new_route.mkdir(parents=True)
    (new_route / "route.toml").write_text(
        '[route]\nname = "good_route"\nversion = "0.1.0"\n'
        '[[route.capabilities]]\nname = "net.inbound"\nscope = "http:/api/v1/good"\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(gate, "_ROUTE_DIR", routes)
    monkeypatch.setattr(gate, "_PLUGIN_DIR", tmp_path / "plugins")
    monkeypatch.setattr(gate, "_BASELINE_PATH", tmp_path / "baseline.txt")

    assert gate.main([]) == 0


def test_gate_catches_missing_processor_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Роут с шагом ``audit`` без декларации ``audit.write`` блокируется.

    ADR-0454: capability шага берётся из того же источника, что и рантайм-
    проверка (``required_capability`` + ``@processor(capabilities=...)``),
    поэтому гейт видит ``audit → audit.write`` и требует декларацию.
    """
    from tools import check_route_capabilities as gate

    routes = tmp_path / "routes"
    new_route = routes / "audit_route"
    new_route.mkdir(parents=True)
    (new_route / "route.toml").write_text(
        '[route]\nname = "audit_route"\nversion = "0.1.0"\n'
        'pipelines = ["main.dsl.yaml"]\n'
        '[[route.capabilities]]\nname = "net.inbound"\nscope = "http:/api/v1/audit"\n',
        encoding="utf-8",
    )
    (new_route / "main.dsl.yaml").write_text(
        "steps:\n  - audit:\n      action: demo.audit\n", encoding="utf-8"
    )

    monkeypatch.setattr(gate, "_ROUTE_DIR", routes)
    monkeypatch.setattr(gate, "_PLUGIN_DIR", tmp_path / "plugins")
    monkeypatch.setattr(gate, "_BASELINE_PATH", tmp_path / "baseline.txt")

    assert gate.main([]) == 1, "роут с audit-шагом без audit.write обязан падать"


def test_baseline_file_exists_and_is_not_empty() -> None:
    """Baseline-файл существует (легаси зафиксирован явно)."""
    baseline = Path(".security/route-capabilities-baseline.txt")
    assert baseline.exists(), "нет baseline-файла гейта capability-деклараций"
    entries = [
        line.strip()
        for line in baseline.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert entries, "baseline пуст — легаси-манифесты не зафиксированы"
    assert all(":" in entry for entry in entries), entries


def _route_audit_actions(manifest: Path) -> list[str]:
    """Статические ``action`` шагов ``audit`` из DSL-спеков роута.

    Args:
        manifest: Путь к ``route.toml`` роута.

    Returns:
        Список action'ов; пустой список — если шагов ``audit`` нет
        (или action задан динамически через ``action_from`` — такой
        scope статически не вычислить).

    """
    route = tomllib.loads(manifest.read_text(encoding="utf-8")).get("route", {})
    actions: list[str] = []
    for entry in route.get("pipelines") or []:
        if not isinstance(entry, str):
            continue
        spec = manifest.parent / entry
        if not spec.exists():
            continue
        raw = yaml.safe_load(spec.read_text(encoding="utf-8")) or {}
        for step in raw.get("steps") or []:
            if not isinstance(step, dict) or "audit" not in step:
                continue
            audit = step.get("audit") or {}
            action = audit.get("action")
            if isinstance(action, str) and action:
                actions.append(action)
    return actions


def test_audit_scope_covers_runtime_request() -> None:
    """Декларированный scope ``audit.write`` покрывает runtime-запрос шага.

    Гейт ``check_route_capabilities`` сверяет **имя** capability, но не
    scope: декларация ``audit.write`` со scope ``audit:other`` проходит
    CI, а рантайм отклоняет шаг (запись в audit-sink теряется). Тест
    закрывает эту дыру: scope запроса вычисляет сам процессор
    (:meth:`AuditProcessor._capability_scope` — единственный источник
    истины про преобразование ``action`` → ``audit:<action>``), а
    покрытие проверяет matcher'ом vocabulary.
    """
    from src.backend.core.security.capabilities.vocabulary.defaults import (
        build_default_vocabulary,
    )
    from src.backend.dsl.engine.exchange import Exchange, Message
    from src.backend.dsl.engine.processors.audit import AuditProcessor

    matcher = build_default_vocabulary().get("audit.write").matcher
    exchange = Exchange(in_message=Message(body={}))
    checked = 0
    for manifest in sorted(_ROUTES_DIR.glob("*/route.toml")):
        route = tomllib.loads(manifest.read_text(encoding="utf-8")).get("route", {})
        actions = _route_audit_actions(manifest)
        if not actions:
            continue
        declared = {
            str(ref.get("name")): ref.get("scope")
            for ref in route.get("capabilities") or []
            if isinstance(ref, dict)
        }
        scope = declared.get("audit.write")
        assert scope is not None, f"{manifest}: нет декларации audit.write"
        for action in actions:
            requested = AuditProcessor(action=action)._capability_scope(exchange)
            assert isinstance(requested, str), (
                f"{manifest}: scope запроса для action={action!r} не определён"
            )
            assert matcher.match(requested, scope), (
                f"{manifest}: scope {scope!r} не покрывает runtime-запрос "
                f"{requested!r} (action={action!r})"
            )
            checked += 1
    assert checked, "не найдено ни одного шага audit — тест неактуален"
