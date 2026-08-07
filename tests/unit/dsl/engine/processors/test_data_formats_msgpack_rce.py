"""cycle-6/D-AUDIT-603 — regression-тесты для Pickle RCE в msgpack fallback.

Сценарий атаки до фикса (DSL-P0-002 / cycle-4 DOMAIN-P0-003 зеркало):

    1. Злоумышленник поставляет bytes-payload через untrusted-источник
       (HTTP webhook, MQ message, S3-stored blob).
    2. ``FormatConvertProcessor(direction="from_msgpack")`` ловит payload
       через ``_from_msgpack``.
    3. В HEAD до фикса: ``except ImportError`` → ``pickle.loads(raw)``
       выполняет произвольный код из pickle opcode.
    4. RCE на узле.

После фикса:

    * ``_from_msgpack`` жёстко требует ``msgpack``. При его отсутствии
      поднимается ``ImportError`` с понятным сообщением (паттерн
      совпадает с ``_from_parquet``).
    * ``pickle.loads`` больше НЕ вызывается ни в одном пути
      format_convert — payload не достигает ``pickle``.
    * ``FormatConvertProcessor.process`` ловит ``ImportError`` в общем
      ``except Exception`` и делает ``exchange.fail(...)`` (DSL convention).

Тесты::

    test_pickle_payload_rejected_when_msgpack_unavailable
        pickle.dumps(...) → _from_msgpack → НЕ pickle.loads, ImportError.
    test_to_msgpack_raises_without_msgpack
        Симулируем ImportError msgpack → ImportError (не pickle fallback).
    test_format_convert_processor_rejects_when_msgpack_missing
        Process-level: msgpack missing → exchange.fail (не тихий pickle).
    test_format_convert_msgpack_roundtrip_with_msgpack_available
        Smoke: msgpack present → нормальный round-trip.
    test_msgpack_payload_unaffected_by_pickle_removal
        Sanity: валидный msgpack-payload не трогается pickle-логикой.

Используем ``monkeypatch`` для контроля видимости ``msgpack`` без удаления
зависимости из venv (минимальный риск для порядка тестов).
"""

from __future__ import annotations

import importlib
import pickle
import sys
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.format_convert.data_formats import (
    DataFormatsMixin,
)
from src.backend.dsl.engine.processors.format_convert import FormatConvertProcessor


def _make_exchange(body: Any) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


class _MsgPickleHost(DataFormatsMixin):
    """Минимальный хост с DataFormatsMixin — для прямого вызова _from_msgpack."""

    pass


@pytest.fixture
def mixin_host() -> _MsgPickleHost:
    """Хост с DataFormatsMixin для unit-уровневого тестирования."""
    return _MsgPickleHost()


@pytest.fixture
def hide_msgpack(monkeypatch: pytest.MonkeyPatch) -> None:
    """Скрываем ``msgpack`` в sys.modules → ``import msgpack`` падает ImportError.

    Используется для проверки, что НЕ происходит pickle fallback.
    """
    saved = sys.modules.pop("msgpack", None)
    # Блокируем re-import через meta-path hack: создаём loader, который
    # выбрасывает ImportError при попытке найти spec для msgpack.
    import importlib.abc
    import importlib.machinery

    class _BlockedMetaFinder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path, target=None):  # type: ignore[no-untyped-def]
            if fullname == "msgpack" or fullname.startswith("msgpack."):
                raise ImportError(
                    f"[cycle-6/D-AUDIT-603] msgpack blocked for test: {fullname}"
                )
            return None

    blocker = _BlockedMetaFinder()
    sys.meta_path.insert(0, blocker)
    # Также чистим кэш уже импортированного msgpack
    importlib.invalidate_caches()
    try:
        yield
    finally:
        sys.meta_path.remove(blocker)
        if saved is not None:
            sys.modules["msgpack"] = saved
        importlib.invalidate_caches()


class TestPickleRceRejected:
    """cycle-6/D-AUDIT-603 — pickle payload НЕ должен выполняться."""

    def test_pickle_payload_rejected_when_msgpack_unavailable(
        self, mixin_host: _MsgPickleHost, hide_msgpack: None
    ) -> None:
        """Pickle-payload → ImportError, а НЕ pickle.loads (RCE)."""
        # Злонамеренный pickle-payload: при unpickling выполняет ``os.system``.
        # В production это был бы RCE; в тесте достаточно проверить, что код
        # НЕ выполняется и поднимается ImportError.
        import os

        class _RcePayload:
            def __reduce__(self):  # noqa: D401
                return (os.system, ("echo PWNED > /tmp/should_not_exist",))

        malicious = pickle.dumps(_RcePayload())

        # sanity check: если бы pickle.loads вызвался — файл бы создался.
        # (Это нужно очистить после теста.)
        rce_marker = "/tmp/cycle6_d_audit_603_rce_marker"
        if os.path.exists(rce_marker):
            os.unlink(rce_marker)
        try:
            with pytest.raises(ImportError) as excinfo:
                mixin_host._from_msgpack(malicious)
            # Сообщение должно указывать на msgpack, не на pickle.
            assert "msgpack" in str(excinfo.value), (
                f"expected msgpack error, got: {excinfo.value}"
            )
            assert "pickle" not in str(excinfo.value), (
                "ImportError message MUST NOT mention pickle (fallback убран)"
            )
        finally:
            assert not os.path.exists(rce_marker), (
                f"RCE executed — pickle payload unpickled: {rce_marker}"
            )

    def test_to_msgpack_raises_without_msgpack(
        self, mixin_host: _MsgPickleHost, hide_msgpack: None
    ) -> None:
        """_to_msgpack без msgpack → ImportError, не pickle fallback."""
        with pytest.raises(ImportError) as excinfo:
            mixin_host._to_msgpack({"k": "v"})
        assert "msgpack" in str(excinfo.value)
        assert "pickle" not in str(excinfo.value)

    def test_from_msgpack_normalizes_input_types(
        self, mixin_host: _MsgPickleHost
    ) -> None:
        """Sanity: msgpack доступен → bytes/str input дают нормальный объект."""
        pytest.importorskip("msgpack")
        import msgpack as _msgpack

        payload = _msgpack.packb({"a": 1, "b": [1, 2, 3]}, use_bin_type=True)
        result = mixin_host._from_msgpack(payload)
        assert result == {"a": 1, "b": [1, 2, 3]}

        # bytearray input → нормально работает
        result_ba = mixin_host._from_msgpack(bytearray(payload))
        assert result_ba == {"a": 1, "b": [1, 2, 3]}


class TestFormatConvertProcessorFailsClosed:
    """cycle-6/D-AUDIT-603 — process-level fail-closed при отсутствии msgpack."""

    @pytest.mark.asyncio
    async def test_format_convert_to_msgpack_fails_without_msgpack(
        self, hide_msgpack: None
    ) -> None:
        proc = FormatConvertProcessor(direction="to_msgpack", fmt="msgpack")
        ex = _make_exchange({"k": "v"})
        await proc.process(ex, MagicMock())
        assert ex.status == ExchangeStatus.failed, (
            f"exchange should fail when msgpack missing, got status={ex.status}"
        )
        assert "msgpack" in (ex.error or ""), (
            f"error should mention msgpack, got: {ex.error!r}"
        )

    @pytest.mark.asyncio
    async def test_format_convert_from_msgpack_fails_without_msgpack(
        self, hide_msgpack: None
    ) -> None:
        proc = FormatConvertProcessor(direction="from_msgpack", fmt="msgpack")
        ex = _make_exchange(b"\x80\x00")  # любая bytes
        await proc.process(ex, MagicMock())
        assert ex.status == ExchangeStatus.failed
        assert "msgpack" in (ex.error or "")

    @pytest.mark.asyncio
    async def test_format_convert_pickle_payload_does_not_execute(
        self, hide_msgpack: None
    ) -> None:
        """End-to-end: pickle-payload через FormatConvertProcessor.process
        → exchange.fail (не RCE)."""
        import os

        class _RcePayload:
            def __reduce__(self):  # noqa: D401
                return (os.system, ("touch /tmp/cycle6_d_audit_603_e2e_rce",))

        malicious = pickle.dumps(_RcePayload())
        marker = "/tmp/cycle6_d_audit_603_e2e_rce"
        if os.path.exists(marker):
            os.unlink(marker)
        try:
            proc = FormatConvertProcessor(direction="from_msgpack", fmt="msgpack")
            ex = _make_exchange(malicious)
            await proc.process(ex, MagicMock())
            assert ex.status == ExchangeStatus.failed
            assert not os.path.exists(marker), (
                "RCE executed via FormatConvertProcessor.process — fallback НЕ удалён"
            )
        finally:
            if os.path.exists(marker):
                os.unlink(marker)


class TestMsgpackRoundtripSmoke:
    """Sanity-тесты: при доступном msgpack поведение не изменилось."""

    @pytest.mark.asyncio
    async def test_format_convert_msgpack_roundtrip(self) -> None:
        """Smoke: to_msgpack → from_msgpack round-trip с реальным msgpack."""
        pytest.importorskip("msgpack")
        proc_to = FormatConvertProcessor(direction="to_msgpack", fmt="msgpack")
        ex1 = _make_exchange({"hello": "world", "n": 42})
        await proc_to.process(ex1, MagicMock())
        assert ex1.status != ExchangeStatus.failed, ex1.error
        encoded = ex1.out_message.body
        assert isinstance(encoded, bytes)

        proc_from = FormatConvertProcessor(direction="from_msgpack", fmt="msgpack")
        ex2 = _make_exchange(encoded)
        await proc_from.process(ex2, MagicMock())
        assert ex2.status != ExchangeStatus.failed, ex2.error
        assert ex2.out_message.body == {"hello": "world", "n": 42}

    def test_data_formats_mixin_has_no_pickle_call(self) -> None:
        """AST check: в data_formats.py НЕТ вызовов pickle.{loads,dumps}.

        Защита от регрессии: если кто-то добавит pickle fallback обратно,
        этот тест сломается.
        """
        import ast
        from pathlib import Path

        # Находим data_formats.py через модуль (надёжнее чем __file__)
        import src.backend.dsl.engine.processors.format_convert.data_formats as _mod

        src_path = Path(_mod.__file__)
        if src_path is None:
            pytest.skip("module __file__ unavailable")
        tree = ast.parse(src_path.read_text(encoding="utf-8"), filename=str(src_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                # pickle.loads / pickle.dumps — qualified call
                if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                    if func.value.id == "pickle" and func.attr in {"loads", "load", "dumps", "dump"}:
                        pytest.fail(
                            f"regression: pickle.{func.attr} call found "
                            f"at line {node.lineno} — cycle-6/D-AUDIT-603"
                        )
