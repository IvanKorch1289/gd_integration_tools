"""Unit-тесты RestrictedUnpickler для безопасной десериализации pickle.

Note: ``pickle.dumps`` сохраняет qualified name класса в поток. По дизайну
RestrictedUnpickler разрешает только stdlib-модули, поэтому round-trip тесты
используют **только** whitelisted типы (datetime, decimal, collections, uuid,
ipaddress, builtins). Тесты с project-классами (dataclass/Enum из этого
тестового файла) намеренно НЕ включены — они бы потребовали расширения
allowlist, что снижает security boundary. Round-trip уже покрыт
``collections``/``datetime``/``decimal``/``uuid``/``ipaddress``/``builtins``.
"""

from __future__ import annotations

import collections
import collections.abc
import datetime
import decimal
import pickle
import uuid
from ipaddress import IPv4Address

import pytest

from src.backend.core.security.restricted_unpickler import (
    DEFAULT_ALLOWLIST,
    RestrictedUnpickler,
    safe_loads,
)


@pytest.mark.unit
class TestRestrictedUnpickler:
    """Проверяет whitelist + fail-closed поведение RestrictedUnpickler."""

    def test_default_allowlist_is_immutable_frozenset(self) -> None:
        """DEFAULT_ALLOWLIST — frozenset (неизменяемый, O(1) lookup)."""
        assert isinstance(DEFAULT_ALLOWLIST, frozenset)
        assert "builtins" in DEFAULT_ALLOWLIST
        assert "collections" in DEFAULT_ALLOWLIST
        assert "datetime" in DEFAULT_ALLOWLIST
        assert "dataclasses" in DEFAULT_ALLOWLIST

    def test_safe_loads_roundtrip_primitives(self) -> None:
        """safe_loads round-trip для builtins (int/str/list/dict/tuple/set)."""
        for original in [
            42,
            3.14,
            "hello",
            b"bytes",
            True,
            None,
            [1, 2, 3],
            {"a": 1, "b": 2},
            (1, 2, 3),
            {1, 2, 3},
            frozenset({1, 2, 3}),
        ]:
            restored = safe_loads(pickle.dumps(original))
            assert restored == original

    def test_safe_loads_roundtrip_collections(self) -> None:
        """safe_loads корректно десериализует collections.OrderedDict."""
        original = collections.OrderedDict([("a", 1), ("b", 2)])
        blob = pickle.dumps(original)
        restored = safe_loads(blob)
        assert restored == original
        assert isinstance(restored, collections.OrderedDict)

    def test_safe_loads_roundtrip_datetime(self) -> None:
        """safe_loads корректно десериализует datetime (sub-module whitelist)."""
        original = datetime.datetime(2026, 8, 31, 12, 0, 0)
        blob = pickle.dumps(original)
        restored = safe_loads(blob)
        assert restored == original

    def test_safe_loads_roundtrip_uuid(self) -> None:
        """safe_loads корректно десериализует uuid.UUID."""
        original = uuid.UUID("12345678-1234-5678-1234-567812345678")
        blob = pickle.dumps(original)
        restored = safe_loads(blob)
        assert restored == original

    def test_safe_loads_roundtrip_decimal(self) -> None:
        """safe_loads корректно десериализует decimal.Decimal (stdlib)."""
        original = decimal.Decimal("3.14159265358979323846")
        blob = pickle.dumps(original)
        restored = safe_loads(blob)
        assert restored == original

    def test_safe_loads_roundtrip_ipaddress(self) -> None:
        """safe_loads корректно десериализует ipaddress.IPv4Address."""
        original = IPv4Address("10.0.0.1")
        blob = pickle.dumps(original)
        restored = safe_loads(blob)
        assert restored == original

    def test_safe_loads_roundtrip_nested_collections(self) -> None:
        """safe_loads round-trip для вложенных collections + datetime."""
        original = [
            {"ts": datetime.date(2026, 1, 1), "tags": ("x", "y")},
            {"ts": datetime.date(2026, 2, 1), "tags": ("z",)},
        ]
        blob = pickle.dumps(original)
        restored = safe_loads(blob)
        assert restored == original

    def test_safe_loads_rejects_os_system_pickle(self) -> None:
        """safe_loads fail-closed на RCE-vector через ``os.system``."""
        # pickle opcode: ``c`` = GLOBAL = ``module.name`` lookup.
        blob = b"\x80\x04cos\nsystem\n(S'echo pwned'\ntR."
        with pytest.raises(pickle.UnpicklingError, match="not in allowlist"):
            safe_loads(blob)

    def test_safe_loads_rejects_subprocess_call(self) -> None:
        """safe_loads fail-closed на ``subprocess`` модуль."""
        blob = b"\x80\x04csubprocess\ncall\n(S'ls'\ntR."
        with pytest.raises(pickle.UnpicklingError, match="not in allowlist"):
            safe_loads(blob)

    def test_safe_loads_rejects_forbidden_name_in_whitelisted_module(self) -> None:
        """safe_loads fail-closed на ``eval``/``exec``/``__import__`` имена.

        ``builtins`` в whitelist, но ``eval``/``exec``/``__import__`` — RCE vectors.
        """
        # Pickle GLOBAL для ``builtins.eval``.
        blob = b"\x80\x04cbuiltins\neval\n(S'1+1'\ntR."
        with pytest.raises(pickle.UnpicklingError, match="forbidden"):
            safe_loads(blob)

    def test_custom_allowlist_allows_specific_module(self) -> None:
        """Кастомный allowlist расширяет дефолт."""
        custom = DEFAULT_ALLOWLIST | {"os"}
        blob = pickle.dumps((1, 2, 3))
        restored = safe_loads(blob, allowlist=custom)
        assert restored == (1, 2, 3)

    def test_custom_allowlist_can_strict_default(self) -> None:
        """Кастомный allowlist может сузить DEFAULT_ALLOWLIST."""
        strict = frozenset({"builtins"})  # только builtins
        blob = pickle.dumps(datetime.date(2026, 1, 1))
        with pytest.raises(pickle.UnpicklingError, match="not in allowlist"):
            safe_loads(blob, allowlist=strict)

    def test_safe_loads_returns_none_for_none(self) -> None:
        """safe_loads(None bytes) обрабатывает корректно (builtins.NoneType)."""
        blob = pickle.dumps(None)
        assert safe_loads(blob) is None

    def test_restricted_unpickler_class_exported(self) -> None:
        """RestrictedUnpickler доступен через ``core.security.__init__``."""
        from src.backend.core.security import RestrictedUnpickler as ReExported
        from src.backend.core.security import safe_loads as safe_re

        assert ReExported is RestrictedUnpickler
        assert safe_re is safe_loads

    def test_safe_loads_rejects_malformed_pickle(self) -> None:
        """safe_loads пробрасывает pickle.UnpicklingError на malformed input."""
        bad_blob = b"not a valid pickle"
        with pytest.raises(pickle.UnpicklingError):
            safe_loads(bad_blob)

    def test_default_allowlist_excludes_dangerous_modules(self) -> None:
        """DEFAULT_ALLOWLIST не содержит ``os``/``subprocess``/``sys``."""
        forbidden = {"os", "subprocess", "sys", "shutil", "importlib"}
        for mod in forbidden:
            assert mod not in DEFAULT_ALLOWLIST, (
                f"{mod} must NOT be in DEFAULT_ALLOWLIST (RCE vector)"
            )

    def test_restricted_unpickler_via_io_bytes(self) -> None:
        """RestrictedUnpickler принимает любой file-like с bytes."""
        import io as _io

        blob = pickle.dumps([1, 2, 3])
        unpickler = RestrictedUnpickler(_io.BytesIO(blob))
        assert unpickler.load() == [1, 2, 3]
