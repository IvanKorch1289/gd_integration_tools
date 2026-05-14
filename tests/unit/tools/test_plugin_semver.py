"""Smoke-тесты для проверки semver plugin.toml манифестов.

K1 Sprint-3 Wave 5 (S3-W5): проверяет базовую работоспособность
tools/checks/check_plugin_semver.py и
src/backend/core/plugin_runtime/semver_checker.py.

Покрывает:
    1. Валидный plugin.toml — SemverCheckResult.valid=True.
    2. Отсутствующее поле version → valid=False с описанием ошибки.
    3. Невалидный SemVer (x.y без patch) → valid=False.
    4. Невалидный requires_core (мусор) → valid=False.
    5. is_compatible: корректный и некорректный диапазоны.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from src.backend.core.plugin_runtime.semver_checker import (
    SemverCheckResult,
    check_plugin_semver,
    is_compatible,
)

# ─── Фикстуры ──────────────────────────────────────────────────────────────


def _write_toml(tmp_path: Path, content: str) -> Path:
    """Записывает plugin.toml в tmp_path и возвращает путь к файлу.

    Args:
        tmp_path: Временная директория из pytest.
        content: Содержимое TOML-файла.

    Returns:
        Путь к созданному plugin.toml.
    """
    toml_file = tmp_path / "plugin.toml"
    toml_file.write_text(textwrap.dedent(content), encoding="utf-8")
    return toml_file


# ─── Тесты ─────────────────────────────────────────────────────────────────


def test_valid_manifest(tmp_path: Path) -> None:
    """Валидный plugin.toml проходит все проверки с valid=True."""
    toml_file = _write_toml(
        tmp_path,
        """
        name = "my_plugin"
        version = "1.2.3"
        requires_core = ">=0.2,<0.3"
        """,
    )

    result: SemverCheckResult = check_plugin_semver(toml_file)

    assert result.valid is True, f"Ожидался valid=True, ошибка: {result.error}"
    assert result.version == "1.2.3"
    assert result.requires_core == ">=0.2,<0.3"
    assert result.error == ""


def test_missing_version_field(tmp_path: Path) -> None:
    """plugin.toml без поля version возвращает valid=False с описанием ошибки."""
    toml_file = _write_toml(
        tmp_path,
        """
        name = "broken_plugin"
        requires_core = ">=0.1"
        """,
    )

    result: SemverCheckResult = check_plugin_semver(toml_file)

    assert result.valid is False
    assert "version" in result.error, f"Ошибка должна упоминать 'version', получено: {result.error}"


def test_invalid_semver_format(tmp_path: Path) -> None:
    """version 'x.y' (без patch) не соответствует SemVer → valid=False."""
    toml_file = _write_toml(
        tmp_path,
        """
        name = "bad_version_plugin"
        version = "1.2"
        requires_core = ">=0.2,<0.3"
        """,
    )

    result: SemverCheckResult = check_plugin_semver(toml_file)

    assert result.valid is False
    assert "SemVer" in result.error or "version" in result.error.lower(), (
        f"Ошибка должна упоминать SemVer или version: {result.error}"
    )


def test_invalid_requires_core(tmp_path: Path) -> None:
    """requires_core с синтаксическим мусором → valid=False."""
    toml_file = _write_toml(
        tmp_path,
        """
        name = "bad_requires_plugin"
        version = "0.1.0"
        requires_core = "not-a-valid-specifier!!!"
        """,
    )

    result: SemverCheckResult = check_plugin_semver(toml_file)

    assert result.valid is False
    assert "requires_core" in result.error.lower() or "specifier" in result.error.lower(), (
        f"Ошибка должна упоминать requires_core или specifier: {result.error}"
    )


def test_is_compatible_ranges() -> None:
    """is_compatible корректно проверяет несколько диапазонов requires_core."""
    # Совместимая версия ядра.
    assert is_compatible(">=0.2,<0.3", "0.2.5") is True
    assert is_compatible(">=1.0.0", "1.0.0") is True
    assert is_compatible("~=0.2.1", "0.2.5") is True

    # Несовместимая версия ядра.
    assert is_compatible(">=0.2,<0.3", "0.3.0") is False
    assert is_compatible(">=1.0.0", "0.9.9") is False

    # Невалидный specifier — должен вернуть False без исключения.
    assert is_compatible("!!! invalid !!!", "1.0.0") is False
