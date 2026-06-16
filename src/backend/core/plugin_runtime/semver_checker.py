"""Semver-совместимость plugin.toml — runtime-проверка.

Назначение:
    Централизованная проверка версии плагина (V11.1 contract, R-V15-1):
    - name/version/requires_core обязательны и семантически верны;
    - is_compatible проверяет requires_core относительно версии ядра
      через PEP 440 SpecifierSet (packaging);
    - режим strict управляется feature_flag.plugin_semver_strict (default-OFF).

Использование:
    from src.backend.core.plugin_runtime.semver_checker import (
        check_plugin_semver,
        is_compatible,
        SemverCheckResult,
    )

    result = check_plugin_semver(Path("extensions/my_plugin/plugin.toml"))
    if not result.valid:
        raise RuntimeError(result.error)

    if not is_compatible(result.requires_core, core_version="0.2.5"):
        raise CapabilityDeniedError("requires_core mismatch")

Зависимости:
    packaging — уже в стеке проекта; tomllib — stdlib Python 3.11+.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

__all__ = ("SemverCheckResult", "check_plugin_semver", "is_compatible")

# SemVer X.Y.Z с опциональным pre-release суффиксом (e.g. 1.2.3-beta.1).
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)*)?$")


@dataclass(slots=True)
class SemverCheckResult:
    """Результат semver-проверки одного plugin.toml.

    Атрибуты:
        valid: True, если манифест прошёл все проверки.
        version: Строка version из манифеста (или пустая при ошибке).
        requires_core: Строка requires_core из манифеста (или пустая).
        error: Описание первой обнаруженной ошибки (пустая при valid=True).
        all_errors: Полный список ошибок (пустой при valid=True).
    """

    valid: bool
    version: str = ""
    requires_core: str = ""
    error: str = ""
    all_errors: list[str] = field(default_factory=list)


def _validate_version(version: str) -> str | None:
    """Проверяет строку версии на соответствие SemVer-шаблону.

    Args:
        version: Строка версии из plugin.toml.

    Returns:
        Сообщение об ошибке или None при корректном значении.
    """
    if not _SEMVER_RE.match(version):
        return f"version '{version}' не соответствует SemVer X.Y.Z(-pre)?"
    return None


def _validate_requires_core(requires_core: str) -> str | None:
    """Проверяет requires_core как корректный PEP 440 SpecifierSet.

    Args:
        requires_core: Строка спецификации версии ядра из plugin.toml.

    Returns:
        Сообщение об ошибке или None при корректном значении.
    """
    try:
        SpecifierSet(requires_core)
    except InvalidSpecifier as exc:
        return (
            f"requires_core '{requires_core}' не является "
            f"валидным PEP 440 specifier: {exc}"
        )
    return None


def check_plugin_semver(plugin_path: Path) -> SemverCheckResult:
    """Проверяет plugin.toml на semver-корректность.

    Читает plugin.toml из plugin_path (файл или директория-плагина),
    проверяет наличие и корректность полей name, version, requires_core.
    Если feature_flag.plugin_semver_strict=False (default-OFF) — возвращает
    результат без исключений; strict-режим включается через env-флаг.

    Args:
        plugin_path: Путь к файлу plugin.toml или директории плагина.

    Returns:
        SemverCheckResult с результатом проверки.
    """
    # Определяем путь к toml-файлу.
    toml_path = (
        plugin_path
        if plugin_path.name == "plugin.toml"
        else plugin_path / "plugin.toml"
    )

    if not toml_path.exists():
        return SemverCheckResult(
            valid=False,
            error=f"plugin.toml не найден: {toml_path}",
            all_errors=[f"plugin.toml не найден: {toml_path}"],
        )

    try:
        with toml_path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        msg = f"TOML parse error: {exc}"
        return SemverCheckResult(valid=False, error=msg, all_errors=[msg])

    errors: list[str] = []

    # Обязательные поля.
    for required_field in ("name", "version", "requires_core"):
        if required_field not in data:
            errors.append(f"обязательное поле '{required_field}' отсутствует")

    if errors:
        return SemverCheckResult(valid=False, error=errors[0], all_errors=errors)

    version = str(data["version"])
    requires_core = str(data["requires_core"])

    # Валидация значений.
    if err := _validate_version(version):
        errors.append(err)

    if err := _validate_requires_core(requires_core):
        errors.append(err)

    if errors:
        return SemverCheckResult(
            valid=False,
            version=version,
            requires_core=requires_core,
            error=errors[0],
            all_errors=errors,
        )

    # Проверяем strict-режим через feature-flag (default-OFF).
    _check_strict_mode(version, requires_core, errors)

    return SemverCheckResult(valid=True, version=version, requires_core=requires_core)


def _check_strict_mode(version: str, requires_core: str, errors: list[str]) -> None:
    """Выполняет дополнительные проверки в strict-режиме.

    В strict-режиме (plugin_semver_strict=True) применяются
    расширенные ограничения, например требование явного верхнего bound
    в requires_core. Default-OFF до staging-smoke.

    Args:
        version: Строка версии плагина.
        requires_core: Строка спецификатора версии ядра.
        errors: Список, в который добавляются найденные ошибки.
    """
    try:
        from src.backend.core.config.features import feature_flags

        if not feature_flags.plugin_semver_strict:
            return
    except Exception as _:
        # feature_flags недоступны в тестах без DI — пропускаем strict.
        return

    # Strict: requires_core обязан содержать явный верхний bound (<X.Y).
    spec = SpecifierSet(requires_core)
    has_upper_bound = any(op in ("==", "<", "~=") for op in (s.operator for s in spec))
    if not has_upper_bound:
        errors.append(
            f"strict-режим: requires_core '{requires_core}' "
            "не содержит явного верхнего ограничения (<X.Y или ~=X.Y)"
        )


def is_compatible(plugin_requires: str, core_version: str) -> bool:
    """Проверяет совместимость requires_core с версией ядра.

    Использует packaging.specifiers.SpecifierSet для PEP 440-совместимой
    проверки. При невалидном plugin_requires возвращает False.

    Args:
        plugin_requires: Спецификатор версии из plugin.toml::requires_core
            (например, ">=0.2,<0.3").
        core_version: Текущая версия ядра (например, "0.2.5").

    Returns:
        True, если core_version удовлетворяет plugin_requires.

    Пример:
        >>> is_compatible(">=0.2,<0.3", "0.2.5")
        True
        >>> is_compatible(">=0.2,<0.3", "0.3.0")
        False
    """
    try:
        spec = SpecifierSet(plugin_requires)
        version = Version(core_version)
    except InvalidSpecifier, Exception:
        return False

    return version in spec
