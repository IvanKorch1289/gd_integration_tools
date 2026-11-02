"""Исполнение AI-сгенерированного кода в изолированном sandbox'е (ADR-0409).

Закрывает «e2b-sandbox» из workflow ``code_interpreter_loop``: шаг
исполнения кода ссылался на ``ai.run_agent`` (обычный LLM-вызов), который
ничего не исполнял. Здесь — честная реализация поверх core-контракта
:class:`src.backend.core.ai.sandbox.CodeSandbox`:

* ``E2BSandbox`` — реальный облачный sandbox (e2b.dev), если в процессе
  зарегистрирован ``CodeSandbox``-сервис (``E2B_API_KEY`` + extra ``[ai]``);
* ``NoOpSandbox`` — явный отказ (fail-closed), без ``subprocess``-fallback
  (V15 R-V15-4).

Расширение импортирует только ``src.backend.core.*`` — слой-правило
``extensions → core`` (ADR-042). Capability ``code.execute`` проверяется
внутри ``E2BSandbox`` (fail-closed, ADR-0393).

Связанные ADR: ADR-0409 (волна 22), ADR-0403 (activity-имена workflow).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger

__all__ = ("evaluate_result", "execute_code")

logger = get_logger("extensions.credit_pipeline.sandbox")

#: Таймаут исполнения кода по умолчанию (секунды).
_DEFAULT_TIMEOUT_S = 60.0


def _resolve_sandbox() -> Any:
    """Получить core-сервис ``CodeSandbox`` из DI-контейнера.

    Returns:
        Экземпляр ``CodeSandbox`` (E2B или NoOp).

    Raises:
        RuntimeError: Сервис не зарегистрирован (fail-closed — код не
            исполняется и не подменяется локальным запуском).

    """
    from src.backend.core.ai.sandbox import CodeSandbox
    from src.backend.core.api import get_service

    try:
        return get_service(CodeSandbox)
    except KeyError as exc:
        raise RuntimeError(
            "execute_code: сервис CodeSandbox не зарегистрирован — "
            "исполнение кода недоступно (E2B_API_KEY / extra [ai])"
        ) from exc


async def execute_code(payload: dict[str, Any]) -> dict[str, Any]:
    """Исполнить предложенный LLM-код в изолированном sandbox'е.

    Args:
        payload: Словарь с полем ``code`` (Python-код) и опциональным
            ``timeout_s`` (таймаут исполнения, по умолчанию 60 секунд).

    Returns:
        Словарь с полями ``stdout``, ``stderr``, ``exit_code`` и
        ``artifacts`` (имена артефактов — байты не сериализуются в
        Temporal-payload).

    Raises:
        ValueError: Код не передан.
        RuntimeError: Sandbox недоступен (не зарегистрирован / NoOp) или
            исполнение не удалось.

    """
    code = payload.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("execute_code: payload должен содержать непустой 'code'")

    timeout_s = float(payload.get("timeout_s") or _DEFAULT_TIMEOUT_S)
    sandbox = _resolve_sandbox()

    try:
        result = await sandbox.run(code, timeout_s=timeout_s)
    except RuntimeError:
        # NoOpSandbox / провайдер без SDK — пробрасываем как есть (fail-closed).
        raise
    except Exception as exc:
        raise RuntimeError(f"execute_code: исполнение кода упало: {exc}") from exc

    artifacts = getattr(result, "artifacts", {}) or {}
    logger.info(
        "execute_code: код исполнен (exit_code=%s, stdout=%d симв.)",
        getattr(result, "exit_code", -1),
        len(getattr(result, "stdout", "") or ""),
    )
    return {
        "stdout": getattr(result, "stdout", "") or "",
        "stderr": getattr(result, "stderr", "") or "",
        "exit_code": int(getattr(result, "exit_code", 1)),
        "artifacts": sorted(str(name) for name in artifacts),
    }


async def evaluate_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Оценить результат исполнения кода в sandbox'е.

    Критерий завершённости: код завершился без ошибки (``exit_code == 0``)
    и выдал непустой stdout. Используется workflow'ом как шаг «eval»
    перед сигналом продолжения цикла.

    Args:
        payload: Результат :func:`execute_code` (или его подмножество).

    Returns:
        Словарь с полями ``done`` (bool), ``exit_code``, ``stdout``,
        ``stderr`` и ``summary`` (человекочитаемый вердикт).

    """
    exit_code = int(payload.get("exit_code", 1) or 0)
    stdout = str(payload.get("stdout") or "")
    stderr = str(payload.get("stderr") or "")
    done = exit_code == 0 and bool(stdout.strip())
    summary = (
        "код исполнен успешно" if done else "код не дал результата — требуется итерация"
    )
    return {
        "done": done,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "summary": summary,
    }
