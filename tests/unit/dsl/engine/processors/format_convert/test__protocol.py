"""Tests for dsl/engine/processors/format_convert/_protocol.py (cycle 237).

Per CYCLE-220 analysis, coverage target 77% → 80% (analyst #12).
`_protocol.py` (10 LOC, 503 bytes) — small Protocol без тестов.
"""

from __future__ import annotations


def test_format_convert_protocol_has_four_attrs() -> None:
    """Protocol имеет 4 аннотированных атрибута."""
    from src.backend.dsl.engine.processors.format_convert._protocol import _FormatConvertProtocol
    annotations = _FormatConvertProtocol.__annotations__
    expected = {"secret", "algorithm", "claims", "schema"}
    assert expected.issubset(set(annotations.keys()))


def test_format_convert_protocol_secret_optional() -> None:
    """secret — Optional (str | None)."""
    from src.backend.dsl.engine.processors.format_convert._protocol import _FormatConvertProtocol
    annotations = _FormatConvertProtocol.__annotations__
    assert "str | None" in str(annotations["secret"])


def test_format_convert_protocol_algorithm_optional() -> None:
    """algorithm — Optional (str | None)."""
    from src.backend.dsl.engine.processors.format_convert._protocol import _FormatConvertProtocol
    annotations = _FormatConvertProtocol.__annotations__
    assert "str | None" in str(annotations["algorithm"])


def test_format_convert_protocol_name() -> None:
    """Класс называется \`_FormatConvertProtocol\`."""
    from src.backend.dsl.engine.processors.format_convert._protocol import _FormatConvertProtocol
    assert _FormatConvertProtocol.__name__ == "_FormatConvertProtocol"
