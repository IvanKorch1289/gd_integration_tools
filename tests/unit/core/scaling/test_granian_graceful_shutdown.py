"""Sprint 183 W1.2 — D-AUDIT-95 regression tests.

Строгие ассерты per D-LESSON-11:
- pre-fix падают (нет --shutdown-timeout флага),
- post-fix проходят (флаг + валидация диапазона).
"""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import ValidationError


def _import_granian_tuning():
    from src.backend.core.scaling.granian_tuning import GranianTuning

    return GranianTuning


def test_graceful_shutdown_default_emits_flag() -> None:
    """Default graceful_shutdown_timeout=30 → --shutdown-timeout 30 в CLI."""
    GranianTuning = _import_granian_tuning()
    cfg = GranianTuning()

    with patch(
        "src.backend.core.config.features.feature_flags.granian_rsgi_mode_enabled",
        True,
    ):
        cmd = cfg.build_cli_command(app="src.main:app")

    assert "--shutdown-timeout" in cmd, (
        f"ожидался --shutdown-timeout в CLI, получено: {cmd!r}"
    )
    idx = cmd.index("--shutdown-timeout")
    assert cmd[idx + 1] == "30", (
        f"ожидалось значение 30, получено {cmd[idx + 1]!r}"
    )


def test_graceful_shutdown_explicit_value_emits_flag() -> None:
    """graceful_shutdown_timeout=300 → --shutdown-timeout 300 в CLI."""
    GranianTuning = _import_granian_tuning()
    cfg = GranianTuning(graceful_shutdown_timeout=300)

    with patch(
        "src.backend.core.config.features.feature_flags.granian_rsgi_mode_enabled",
        True,
    ):
        cmd = cfg.build_cli_command(app="src.main:app")

    assert "--shutdown-timeout" in cmd, (
        f"ожидался --shutdown-timeout в CLI, получено: {cmd!r}"
    )
    idx = cmd.index("--shutdown-timeout")
    assert cmd[idx + 1] == "300", (
        f"ожидалось значение 300, получено {cmd[idx + 1]!r}"
    )


def test_graceful_shutdown_zero_omits_flag() -> None:
    """graceful_shutdown_timeout=0 → флаг ОПУЩЕН (backward-compat escape hatch)."""
    GranianTuning = _import_granian_tuning()
    cfg = GranianTuning(graceful_shutdown_timeout=0)

    with patch(
        "src.backend.core.config.features.feature_flags.granian_rsgi_mode_enabled",
        True,
    ):
        cmd = cfg.build_cli_command(app="src.main:app")

    assert "--shutdown-timeout" not in cmd, (
        f"--shutdown-timeout НЕ должен эмититься при value=0, "
        f"получено: {cmd!r}"
    )


def test_graceful_shutdown_rejects_value_above_cap() -> None:
    """graceful_shutdown_timeout=400 (> 300 cap) → ValidationError."""
    GranianTuning = _import_granian_tuning()
    with pytest.raises(ValidationError) as exc_info:
        GranianTuning(graceful_shutdown_timeout=400)

    # Уточнение причины — должна упоминаться верхняя граница 300.
    assert "300" in str(exc_info.value) or "less_than_equal" in str(
        exc_info.value
    ), f"ожидалась ошибка про cap 300, получено: {exc_info.value!r}"


def test_graceful_shutdown_rejects_negative() -> None:
    """graceful_shutdown_timeout=-1 → ValidationError."""
    GranianTuning = _import_granian_tuning()
    with pytest.raises(ValidationError) as exc_info:
        GranianTuning(graceful_shutdown_timeout=-1)

    assert "greater_than_equal" in str(exc_info.value) or "0" in str(
        exc_info.value
    ), f"ожидалась ошибка про ge=0, получено: {exc_info.value!r}"


def test_graceful_shutdown_flag_positioned_before_app() -> None:
    """--shutdown-timeout эмитится ДО app (порядок аргументов важен для Granian)."""
    GranianTuning = _import_granian_tuning()
    cfg = GranianTuning(graceful_shutdown_timeout=15)

    with patch(
        "src.backend.core.config.features.feature_flags.granian_rsgi_mode_enabled",
        True,
    ):
        cmd = cfg.build_cli_command(app="src.main:app")

    idx_flag = cmd.index("--shutdown-timeout")
    idx_app = cmd.index("src.main:app")
    assert idx_flag < idx_app, (
        f"--shutdown-timeout (idx={idx_flag}) должен идти раньше "
        f"app (idx={idx_app}); полная команда: {cmd!r}"
    )
