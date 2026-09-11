"""Contract test cases + results (Wave 1 P0 #7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ContractTestCase:
    """Один contract test.

    Attributes:
        name: Уникальное имя теста.
        input_payload: Входные данные (будут переданы в route_fn).
        expected_output_schema: JSON Schema для валидации output.
        expected_output: Точное expected output (опционально).
        expect_error: True для negative tests (ожидаем exception).
        error_type: Ожидаемый exception type (если expect_error=True).
        setup: Optional setup callable (для test fixtures).
        tags: произвольные теги.

    """

    name: str
    input_payload: Any = None
    expected_output_schema: dict[str, Any] = field(default_factory=dict)
    expected_output: Any = None
    expect_error: bool = False
    error_type: type[BaseException] | None = None
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ContractTestResult:
    """Результат contract test."""

    test_name: str
    passed: bool
    schema_errors: list[str] = field(default_factory=list)
    output_mismatch: bool = False
    expected_error: bool = False
    actual_error: str | None = None
    duration_ms: float = 0.0


@dataclass(slots=True)
class CompatibilityTest:
    """Backward-compatibility verification (old payload still works).

    Используется для проверки, что deprecated/legacy форматы
    входных данных продолжают работать после обновления.

    Attributes:
        name: Имя теста.
        old_payload: Legacy input.
        new_payload: Новый input (для сравнения структуры).
        contract_version: Версия контракта (например, "1.0", "2.0").

    """

    name: str
    old_payload: Any = None
    new_payload: Any = None
    contract_version: str = "1.0"


__all__ = ("CompatibilityTest", "ContractTestCase", "ContractTestResult")
