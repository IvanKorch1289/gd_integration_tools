"""ADR-0419: pickle-формат marshal-EIP — только безопасная десериализация.

Дефект: ``PickleDataFormat.unmarshal`` вызывал ``pickle.loads`` — полный
RCE через подделанный payload (``__reduce__`` → ``os.system``). Формат
достижим из DSL (EIP ``marshal``/``unmarshal``), то есть payload мог прийти
извне.

Фикс: десериализация через ``core.security.restricted_unpickler.safe_loads``
(whitelist модулей) — неизвестный класс → ``pickle.UnpicklingError``.
"""

from __future__ import annotations

import datetime
import os
import pickle

import pytest

from src.backend.dsl.engine.processors.eip.marshal.formats import PickleDataFormat

pytestmark = pytest.mark.unit


class _Exploit:
    """Payload, эксплуатирующий ``__reduce__`` (классический pickle-RCE)."""

    def __reduce__(self) -> tuple[object, ...]:
        """Возвращает вызов, который выполнил бы произвольный код."""
        return (os.system, ("echo pwned",))  # noqa: S605 - намеренный payload


def test_unmarshal_rejects_unsafe_payload() -> None:
    """Небезопасный pickle-payload отвергается (без RCE)."""
    payload = pickle.dumps(_Exploit())

    with pytest.raises(pickle.UnpicklingError):
        PickleDataFormat().unmarshal(payload)


def test_unmarshal_allows_plain_data() -> None:
    """Обычные структуры (dict/list/str) десериализуются как раньше."""
    payload = pickle.dumps({"id": 1, "items": ["a", "b"]})

    assert PickleDataFormat().unmarshal(payload) == {"id": 1, "items": ["a", "b"]}


def test_unmarshal_allows_stdlib_types() -> None:
    """Whitelist restricted_unpickler покрывает базовые stdlib-типы."""
    payload = pickle.dumps({"when": datetime.datetime(2026, 1, 1)})

    restored = PickleDataFormat().unmarshal(payload)

    assert restored["when"].year == 2026


def test_marshal_roundtrip_still_works() -> None:
    """Сериализация (marshal) не изменилась."""
    fmt = PickleDataFormat()
    data = fmt.marshal({"a": 1})

    assert fmt.unmarshal(data) == {"a": 1}
