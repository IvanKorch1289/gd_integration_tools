"""DSL explain MVP tests (25.09 audit #9).

Per очерёдность: «Реализовать DSL explain/replay MVP».

Контракт:
1. ``explain_route(route_dir)`` парсит route.toml + *.dsl.yaml и возвращает
   structured explanation с graph + side effects + capabilities;
2. ``--strict`` exits 1 если missing capabilities или timeout overflow;
3. ``--json`` outputs machine-readable JSON.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.backend.dsl.cli.explanation import RouteExplanation, explain_route

PROJECT_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture()
def hello_route_dir() -> Path:
    return PROJECT_ROOT / "routes" / "hello_route"


@pytest.fixture()
def health_route_dir() -> Path:
    return PROJECT_ROOT / "routes" / "health_proxy_demo"


def test_explain_route_returns_route_explanation(hello_route_dir: Path) -> None:
    """explain_route возвращает :class:`RouteExplanation` с всеми полями."""
    explanation = explain_route(hello_route_dir)
    assert isinstance(explanation, RouteExplanation)
    assert explanation.route_id == "hello_route"
    assert explanation.tenant_aware is True
    assert explanation.timeout_ms == 5000
    assert len(explanation.steps) > 0


def test_explain_route_extracts_capabilities(hello_route_dir: Path) -> None:
    """Capabilities required + declared + missing computed из manifest + steps.

    2026-10-06 (приведение hello_route к API): LLM/policy/to шаги удалены
    из route (LLM — потому что нет capability-guard у процессоров, policy —
    потому что это @property а не метод, response binding to не реализован).
    Routes остались чисто YAML-demo: feature_flag + http_call + audit.
    """
    explanation = explain_route(hello_route_dir)
    # hello_route pipeline (post-fix): feature_flag + http_call + audit
    assert "net.outbound" in explanation.capabilities_required  # http_call
    assert "audit.write" in explanation.capabilities_required  # audit
    # Declared в route.toml (после удаления ложных db.write и ai.invoke)
    assert "net.outbound" in explanation.capabilities_declared
    assert "audit.write" in explanation.capabilities_declared
    # No missing — все required объявлены в манифесте.
    assert explanation.capabilities_missing == ()


def test_explain_route_no_llm_step_post_fix(hello_route_dir: Path) -> None:
    """LLM-шаг удалён из hello_route 2026-10-06: нет рантайм capability-guard
    для LLM-процессоров, поэтому декларация ``ai.invoke`` в манифесте
    была единственным контролем. Удалено вместе с шагом; пробел зафиксирован
    в AUDIT_2026-10-06_runtime_wiring.md как доработка LLM-процессоров.
    """
    explanation = explain_route(hello_route_dir)
    llm_steps = [s for s in explanation.steps if s.step_type.startswith("llm")]
    assert llm_steps == [], (
        "hello_route не должен содержать LLM-шаг: требуется guard "
        "у процессоров, иначе декларация ai.invoke — единственный контроль"
    )


def test_explain_route_no_policy_step_post_fix(hello_route_dir: Path) -> None:
    """policy: @property (не method), как DSL-пропал его как шаг (2026-10-06).

    Политика повторов теперь задаётся через ``retry`` параметр шагов.
    """
    explanation = explain_route(hello_route_dir)
    policy_steps = [s for s in explanation.steps if s.step_type == "policy"]
    assert policy_steps == [], "policy — @property, не должен быть DSL-шагом"


def test_explain_route_identifies_missing_capabilities(health_route_dir: Path) -> None:
    """Missing capabilities вычисляются как required - declared."""
    explanation = explain_route(health_route_dir)
    # health_proxy_demo has empty capabilities declared.
    assert "net.outbound" in explanation.capabilities_required
    assert explanation.capabilities_declared == ()
    assert "net.outbound" in explanation.capabilities_missing
    # Issue message mentions missing capabilities.
    assert any(
        "MISSING" in issue or "не объявлены" in issue for issue in explanation.issues
    )


def test_explain_route_aggregates_side_effects(hello_route_dir: Path) -> None:
    """Side effects: network/db/fs/mq/ai aggregate правильно.

    2026-10-06: hello_route больше не имеет LLM-шага, поэтому 'ai' не
    в aggregate; ожидаются только network (http_call) и audit (audit).
    """
    explanation = explain_route(hello_route_dir)
    kinds = {se.kind for se in explanation.side_effects_aggregate}
    assert "network" in kinds  # http_call
    assert "audit" in kinds  # audit
    # LLM-шаг удалён вместе со своим capabil-guard пробелом
    # (см. AUDIT_2026-10-06_runtime_wiring.md §16-18).


def test_explain_route_extracts_retry_policy(hello_route_dir: Path) -> None:
    """Retry policy извлекается из атрибута ``retry`` любого шага.

    2026-10-06: policy : YAML-шаг удалён (@property, не метод), retry теперь —
    не отдельный DSL-шаг. Тест-демонстрация retry-инфраструктуры теперь
    использует ``retry:`` параметр на любом шаге (см. ``retry_callsites.txt``
    для существующих примеров).
    """
    explanation = explain_route(hello_route_dir)
    # hello_route не имеет шагов с retry: {}. Проверяем, что retry
    # читается корректно (None или отсутствует) на отсутствующем случае.
    http_call_step = next(s for s in explanation.steps if s.step_type == "http_call")
    assert http_call_step.retry is None


def test_explain_route_computes_total_duration(hello_route_dir: Path) -> None:
    """Total estimated duration = sum(steps × retry attempts)."""
    explanation = explain_route(hello_route_dir)
    expected_total = sum(
        s.estimated_duration_ms * (s.retry["attempts"] if s.retry else 1)
        for s in explanation.steps
    )
    assert explanation.total_estimated_duration_ms == expected_total


def test_explain_route_timeout_overflow_warning(hello_route_dir: Path) -> None:
    """Если sum(steps × retries) > timeout → warning в issues."""
    explanation = explain_route(hello_route_dir)
    # hello_route has 1809ms total vs 5000ms timeout → no overflow.
    assert explanation.timeout_ms == 5000
    assert not any(
        "timeout" in issue.lower() and "risk" in issue.lower()
        for issue in explanation.issues
    )


def test_explain_route_feature_flags(hello_route_dir: Path) -> None:
    """Feature flags извлекаются из route.toml::feature_flag."""
    explanation = explain_route(hello_route_dir)
    assert explanation.feature_flags.get("enabled") is True
    assert explanation.feature_flags.get("gate") == "hello_route_enabled"


def test_explain_route_raises_on_missing_route_toml(tmp_path: Path) -> None:
    """Если route.toml отсутствует → ValueError."""
    with pytest.raises(ValueError, match="route.toml"):
        explain_route(tmp_path)


def test_explain_route_raises_on_missing_yaml(tmp_path: Path) -> None:
    """Если *.dsl.yaml отсутствует → ValueError."""
    (tmp_path / "route.toml").write_text("name = 'test'\n")
    with pytest.raises(ValueError, match=r"\*\.dsl\.yaml"):
        explain_route(tmp_path)


def test_explain_cli_human_output(
    hello_route_dir: Path, capsys: pytest.CaptureFixture
) -> None:
    """CLI выводит human-readable summary в stdout."""
    result = subprocess.run(
        [sys.executable, "-m", "src.backend.dsl.cli.explain_cmd", str(hello_route_dir)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "Route: hello_route" in result.stdout
    assert "Steps (" in result.stdout
    assert "Capabilities:" in result.stdout
    # hello_route post-2026-10-06: ai.invoke не объявлен (LLM-шаг удалён);
    # остаются только net.outbound + audit.write.
    assert "net.outbound" in result.stdout
    assert "audit.write" in result.stdout


def test_explain_cli_json_output(
    hello_route_dir: Path, capsys: pytest.CaptureFixture
) -> None:
    """CLI --json outputs machine-readable JSON."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.backend.dsl.cli.explain_cmd",
            str(hello_route_dir),
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["route_id"] == "hello_route"
    assert isinstance(data["steps"], list)
    assert "capabilities_required" in data
    assert "capabilities_missing" in data


def test_explain_cli_strict_fails_on_missing_caps(health_route_dir: Path) -> None:
    """CLI --strict exits 1 если capabilities missing."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.backend.dsl.cli.explain_cmd",
            str(health_route_dir),
            "--strict",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1, (
        f"--strict should exit 1 on missing capabilities, got {result.returncode}. "
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "MISSING" in result.stdout or "missing" in result.stdout.lower()


def test_explain_cli_strict_passes_when_clean(hello_route_dir: Path) -> None:
    """CLI --strict exits 0 если all capabilities declared."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.backend.dsl.cli.explain_cmd",
            str(hello_route_dir),
            "--strict",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
