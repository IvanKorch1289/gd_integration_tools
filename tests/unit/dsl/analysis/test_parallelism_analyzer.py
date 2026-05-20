"""Unit-тесты ParallelismAnalyzer (S13 K2 W3, PERF-6.8)."""

# ruff: noqa: S101

from __future__ import annotations

from src.backend.dsl.analysis.parallelism_analyzer import ParallelismAnalyzer


def test_empty_route() -> None:
    report = ParallelismAnalyzer().analyze([])
    assert report.total_steps == 0
    assert report.parallel_groups == []


def test_linear_chain_no_parallelism() -> None:
    # s2 пишет body.y → s3 читает body.y → линейная цепочка.
    steps = [
        {"type": "get_setting", "id": "s1", "to": "body.url"},
        {"type": "proxy", "id": "s2", "dst": "${body.url}", "to": "body.resp"},
        {"type": "audit", "id": "s3", "data": "${body.resp}"},
    ]
    report = ParallelismAnalyzer().analyze(steps)
    assert report.total_steps == 3
    # Все 3 шага последовательны.
    assert len(report.parallel_groups) == 3
    assert all(len(g) == 1 for g in report.parallel_groups)


def test_independent_steps_grouped() -> None:
    steps = [
        {"type": "crud_create", "id": "a", "entity": "orders"},
        {"type": "crud_create", "id": "b", "entity": "users"},
        {"type": "crud_create", "id": "c", "entity": "logs"},
    ]
    report = ParallelismAnalyzer().analyze(steps)
    # Все три шага не зависят друг от друга → одна группа.
    assert len(report.parallel_groups) == 1
    assert sorted(report.parallel_groups[0]) == ["a", "b", "c"]


def test_diamond_dependency() -> None:
    steps = [
        {"type": "get_setting", "id": "a", "to": "body.x"},
        {"type": "transform", "id": "b1", "input": "${body.x}", "to": "body.y1"},
        {"type": "transform", "id": "b2", "input": "${body.x}", "to": "body.y2"},
        {
            "type": "merge",
            "id": "c",
            "from1": "${body.y1}",
            "from2": "${body.y2}",
        },
    ]
    report = ParallelismAnalyzer().analyze(steps)
    # Уровни: [a], [b1, b2], [c].
    assert len(report.parallel_groups) == 3
    assert sorted(report.parallel_groups[1]) == ["b1", "b2"]


def test_hint_for_parallel_group() -> None:
    steps = [
        {"type": "crud_create", "id": "a"},
        {"type": "crud_create", "id": "b"},
    ]
    report = ParallelismAnalyzer().analyze(steps)
    hint_rules = {h.rule for h in report.suggested_optimizations}
    assert "LR-PAR-001" in hint_rules


def test_hint_for_linear_route() -> None:
    steps = [
        {"type": "get_setting", "id": "s1", "to": "body.x"},
        {"type": "proxy", "id": "s2", "url": "${body.x}", "to": "body.y"},
        {"type": "transform", "id": "s3", "input": "${body.y}", "to": "body.z"},
        {"type": "audit", "id": "s4", "data": "${body.z}"},
    ]
    report = ParallelismAnalyzer().analyze(steps)
    hint_rules = {h.rule for h in report.suggested_optimizations}
    assert "LR-PAR-002" in hint_rules


def test_speedup_estimate() -> None:
    # 4 шага в одной группе → speedup ~ 4.0
    steps = [{"type": "crud_create", "id": f"s{i}"} for i in range(4)]
    report = ParallelismAnalyzer().analyze(steps)
    assert report.estimated_speedup > 3.0  # ~4 / 1 уровень


def test_dependency_extraction() -> None:
    steps = [
        {"type": "get_setting", "id": "a", "to": "body.url"},
        {"type": "proxy", "id": "b", "dst": "${body.url}"},
    ]
    report = ParallelismAnalyzer().analyze(steps)
    deps = report.dependencies
    assert len(deps) == 1
    assert deps[0].from_step == "a"
    assert deps[0].to_step == "b"
    assert deps[0].via == "body.url"


def test_critical_path() -> None:
    steps = [
        {"type": "get_setting", "id": "a", "to": "body.x"},
        {"type": "transform", "id": "b", "input": "${body.x}", "to": "body.y"},
        {"type": "audit", "id": "c", "data": "${body.y}"},
    ]
    report = ParallelismAnalyzer().analyze(steps)
    # b и c зависят → они в critical path.
    assert "b" in report.critical_path
    assert "c" in report.critical_path
