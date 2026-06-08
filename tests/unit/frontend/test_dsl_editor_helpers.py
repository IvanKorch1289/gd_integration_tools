# ruff: noqa: S101
"""Unit-тесты для _editor/ helper-модулей DSL Visual Editor (S77 W3).

Покрывают pure-функции (constants, yaml_to_steps, build_yaml_from_steps,
default_yaml) — те, что не зависят от Streamlit runtime.

Streamlit-зависимые функции (``push_history``, ``undo``, ``redo``,
``sync_yaml``) покрываются integration-тестами когда streamlit
установлен (требует ``uv pip install gd_advanced_tools[frontend]``).

Wave: ``[wave:s77/w3-dsl-editor-split]``.
"""

from __future__ import annotations

import pytest

from src.frontend.streamlit_app.pages._editor.constants import (  # noqa: E402
    PROCESSOR_ICONS,
    STEP_PALETTE,
    VISUAL_PROCESSORS,
    default_yaml,
)
from src.frontend.streamlit_app.pages._editor.yaml_sync import (  # noqa: E402
    build_yaml_from_steps,
    try_load,
    yaml_to_steps,
)

# ──────────────────────────── constants.py ────────────────────────────


def test_step_palette_covers_core_processors() -> None:
    """STEP_PALETTE содержит 12 базовых процессоров для drag-drop sidebar."""
    expected = {
        "log",
        "validate",
        "transform",
        "dispatch_action",
        "retry",
        "redirect",
        "windowed_dedup",
        "windowed_collect",
        "multicast_routes",
        "express_send",
        "express_reply",
        "notify",
    }
    assert set(STEP_PALETTE) == expected
    # Каждый processor имеет title + desc.
    for key, info in STEP_PALETTE.items():
        assert "title" in info, f"{key} missing title"
        assert "desc" in info, f"{key} missing desc"
        assert info["title"], f"{key} empty title"
        assert info["desc"], f"{key} empty desc"


def test_processor_icons_aligned_with_palette() -> None:
    """PROCESSOR_ICONS keys совпадают с STEP_PALETTE keys (UI consistency)."""
    assert set(PROCESSOR_ICONS) == set(STEP_PALETTE)
    # Каждый icon — непустая строка.
    for key, icon in PROCESSOR_ICONS.items():
        assert icon, f"{key} empty icon"


def test_visual_processors_covers_core_parameters() -> None:
    """VISUAL_PROCESSORS содержит параметры для Canvas form-based UI."""
    expected = {
        "log",
        "validate",
        "transform",
        "dispatch_action",
        "retry",
        "redirect",
        "windowed_dedup",
        "windowed_collect",
        "multicast_routes",
        "express_send",
        "express_reply",
        "notify",
    }
    assert set(VISUAL_PROCESSORS) == expected
    # Каждый param — непустая строка.
    for key, params in VISUAL_PROCESSORS.items():
        for p in params:
            assert isinstance(p, str)
            assert p, f"{key} has empty param name"


def test_default_yaml_is_valid_minimal_pipeline() -> None:
    """``default_yaml()`` возвращает валидный минимальный pipeline."""
    yaml_str = default_yaml()
    # Содержит обязательные поля.
    assert "route_id:" in yaml_str
    assert "source:" in yaml_str
    assert "description:" in yaml_str
    assert "processors:" in yaml_str
    # Round-trip: парсится обратно в meta+steps.
    meta, steps = yaml_to_steps(yaml_str)
    assert meta["route_id"] == "my.route"
    assert meta["source"] == "internal:my"
    assert len(steps) == 1
    assert steps[0]["type"] == "log"


# ──────────────────────────── yaml_sync.py ────────────────────────────


def test_yaml_to_steps_empty_string_returns_empty() -> None:
    """Пустой YAML → ``({}, [])`` без exception."""
    meta, steps = yaml_to_steps("")
    assert meta == {"route_id": "", "source": "", "description": ""}
    assert steps == []


def test_yaml_to_steps_invalid_yaml_returns_empty() -> None:
    """Невалидный YAML → ``({}, [])`` без exception (UI-safe)."""
    meta, steps = yaml_to_steps("invalid: yaml: :\n  - not: closed: ")
    assert meta == {}
    assert steps == []


def test_yaml_to_steps_non_dict_yaml_returns_empty() -> None:
    """YAML с top-level list (не dict) → ``({}, [])``."""
    meta, steps = yaml_to_steps("- just\n- a\n- list\n")
    assert meta == {}
    assert steps == []


def test_yaml_to_steps_string_processor_form() -> None:
    """Процессор как строка ``- log`` → ``{type: log, params: {}}``."""
    yaml_str = "route_id: x\nprocessors:\n  - log\n  - validate\n"
    meta, steps = yaml_to_steps(yaml_str)
    assert meta["route_id"] == "x"
    assert len(steps) == 2
    assert steps[0] == {"type": "log", "params": {}}
    assert steps[1] == {"type": "validate", "params": {}}


def test_yaml_to_steps_dict_processor_form() -> None:
    """Процессор как dict ``- log: {level: info}`` → ``{type: log, params}``."""
    yaml_str = "route_id: x\nprocessors:\n  - log:\n      level: info\n  - transform:\n      expression: .x\n"
    meta, steps = yaml_to_steps(yaml_str)
    assert len(steps) == 2
    assert steps[0] == {"type": "log", "params": {"level": "info"}}
    assert steps[1] == {"type": "transform", "params": {"expression": ".x"}}


def test_yaml_to_steps_dict_processor_non_dict_value() -> None:
    """Если значение processor'а не dict, params={} (default)."""
    yaml_str = "route_id: x\nprocessors:\n  - log: just_a_string\n"
    meta, steps = yaml_to_steps(yaml_str)
    assert steps[0] == {"type": "log", "params": {}}


def test_build_yaml_from_steps_minimal() -> None:
    """Минимальный case: только route_id + steps."""
    yaml_str = build_yaml_from_steps(
        {"route_id": "my.route"}, [{"type": "log", "params": {}}]
    )
    assert "route_id: my.route" in yaml_str
    assert "processors:" in yaml_str
    assert "log:" in yaml_str


def test_build_yaml_from_steps_empty_steps_omits_processors() -> None:
    """Пустой steps → ``processors:`` НЕ появляется в YAML."""
    yaml_str = build_yaml_from_steps(
        {"route_id": "my.route", "source": "internal:my"}, []
    )
    assert "processors" not in yaml_str
    assert "route_id: my.route" in yaml_str
    assert "source: internal:my" in yaml_str


def test_build_yaml_from_steps_default_route_id_when_empty() -> None:
    """Если route_id пустой → default ``my.route``."""
    yaml_str = build_yaml_from_steps({"route_id": ""}, [])
    assert "route_id: my.route" in yaml_str


def test_build_yaml_from_steps_unicode_support() -> None:
    """Unicode в description сохраняется (``allow_unicode=True``)."""
    yaml_str = build_yaml_from_steps(
        {"route_id": "x", "description": "Тестовый маршрут"}, []
    )
    assert "Тестовый маршрут" in yaml_str


@pytest.mark.parametrize(
    ("meta", "steps", "expected_substrings"),
    [
        # Case 1: full meta + 1 step.
        (
            {"route_id": "x", "source": "y", "description": "z"},
            [{"type": "log", "params": {"level": "info"}}],
            ["route_id: x", "source: y", "description: z", "log:", "level: info"],
        ),
        # Case 2: meta без description.
        ({"route_id": "x", "source": "y"}, [], ["route_id: x", "source: y"]),
        # Case 3: meta только route_id.
        ({"route_id": "x"}, [], ["route_id: x"]),
        # Case 4: step с empty params → empty dict в YAML.
        ({"route_id": "x"}, [{"type": "validate", "params": {}}], ["validate:", "{}"]),
    ],
)
def test_build_yaml_from_steps_parametrized(
    meta: dict, steps: list[dict], expected_substrings: list[str]
) -> None:
    """Параметризованный test: различные комбинации meta/steps."""
    yaml_str = build_yaml_from_steps(meta, steps)
    for substr in expected_substrings:
        assert substr in yaml_str, f"Missing {substr!r} in {yaml_str!r}"


def test_yaml_round_trip_lossless() -> None:
    """Build → parse → build должен дать тот же YAML (round-trip)."""
    original_meta = {"route_id": "test.route", "source": "internal:test"}
    original_steps = [
        {"type": "log", "params": {"level": "info"}},
        {"type": "validate", "params": {}},
        {"type": "transform", "params": {"expression": ".foo"}},
    ]
    yaml1 = build_yaml_from_steps(original_meta, original_steps)
    meta2, steps2 = yaml_to_steps(yaml1)
    assert meta2["route_id"] == original_meta["route_id"]
    assert meta2["source"] == original_meta["source"]
    assert steps2 == original_steps

    # Re-build → должен совпадать с yaml1.
    yaml2 = build_yaml_from_steps(meta2, steps2)
    assert yaml2 == yaml1


# ──────────────────────────── try_load ────────────────────────────


def test_try_load_valid_yaml_returns_pipeline() -> None:
    """``try_load(valid_yaml)`` → ``(Pipeline, None)`` без ошибки."""
    yaml_str = build_yaml_from_steps(
        {"route_id": "test.try_load", "source": "internal:test"},
        [{"type": "log", "params": {"level": "info"}}],
    )
    pipeline, err = try_load(yaml_str)
    assert err is None
    assert pipeline is not None
    assert pipeline.route_id == "test.try_load"


def test_try_load_invalid_yaml_returns_error() -> None:
    """``try_load(invalid_yaml)`` → ``(None, error_str)`` без exception."""
    pipeline, err = try_load("this: is: not: valid: yaml: :\n  - [unclosed")
    assert pipeline is None
    assert err is not None
    assert isinstance(err, str)
    assert err  # Non-empty error message.
