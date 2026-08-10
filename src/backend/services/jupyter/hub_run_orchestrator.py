"""Jupyter Hub run orchestrator (S170 NEW).

Высокоуровневая функция для запуска notebooks на JupyterHub с параметрами.
Решает задачу: ``notebook_name`` + ``parameters`` → выполнение → outputs.

Pipeline:
  1. Резолв ``notebook_name`` → :class:`NotebookSpec` через реестр.
  2. Валидация ``parameters`` по spec.parameters_schema.
  3. (Опционально) Загрузка notebook contents через JupyterHub contents API.
  4. Выполнение через ``NotebookExecutionService.execute()`` (papermill-style
     parameter injection + Hub kernel execution).
  5. Возврат структурированного результата.

Public API:
    * :func:`run_hub_notebook` — async entrypoint.
    * :class:`HubRunError` — exceptions.

Безопасность:
    * Требует ``feature_flags.jupyter_hub_enabled = True`` (default OFF).
    * Капитализация через capability gate ``jupyter.hub.run``.
    * Все API tokens — через Vault (``JUPYTER_HUB_API_TOKEN``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.services.jupyter.execution_service import NotebookExecutionService
from src.backend.services.jupyter.execution_service.errors import (
    JupyterExecutionError as _JupyterExecutionError,
)
from src.backend.services.jupyter.notebook_registry import (
    NotebookRegistry,
    NotebookSpec,
    get_notebook_registry,
)

# Re-export для удобства callers
JupyterExecutionError = _JupyterExecutionError

_logger = get_logger("services.jupyter.hub_run")


class HubRunError(Exception):
    """Базовое исключение hub-run оркестратора."""


class NotebookNotFoundError(HubRunError):
    """Notebook name не зарегистрирован в :class:`NotebookRegistry`."""

    def __init__(self, name: str) -> None:
        super().__init__(f"notebook not found in registry: {name!r}")
        self.name = name


class NotebookParameterError(HubRunError):
    """Parameters не прошли валидацию."""

    def __init__(self, name: str, errors: list[str]) -> None:
        super().__init__(
            f"parameter validation failed for {name!r}: {'; '.join(errors)}"
        )
        self.name = name
        self.errors = errors


class JupyterHubNotEnabledError(HubRunError):
    """feature_flags.jupyter_hub_enabled = False."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or "JupyterHub integration disabled "
            "(feature_flags.jupyter_hub_enabled=False)"
        )


@dataclass
class HubRunResult:
    """Результат выполнения notebook через Hub.

    Attributes:
        notebook_name: Slug переданного notebook.
        notebook_path: Реальный путь на Hub.
        parameters: Применённые параметры (defaults + user inputs).
        outputs: Cell outputs из executed notebook.
        duration_seconds: Время выполнения.
        cells_executed: Число выполненных code-ячеек.
        errors: Список error-сообщений (пустой при успехе).
    """

    notebook_name: str
    notebook_path: str
    parameters: dict[str, Any]
    outputs: list[dict[str, Any]]
    duration_seconds: float
    cells_executed: int
    errors: list[str]


async def run_hub_notebook(
    notebook_name: str,
    parameters: dict[str, Any] | None = None,
    *,
    user_name: str = "default",
    notebook_content: bytes | str | None = None,
    notebook_path_override: str | None = None,
    output_path: str | None = None,
    registry: NotebookRegistry | None = None,
    execution_service: NotebookExecutionService | None = None,
) -> HubRunResult:
    """Запустить notebook на JupyterHub с параметрами.

    Args:
        notebook_name: Slug зарегистрированного notebook (или произвольное
            имя при ``notebook_content`` / ``notebook_path_override``).
        parameters: Параметры для papermill-style injection.
        user_name: Пользователь JupyterHub.
        notebook_content: Inline ``.ipynb`` content (bytes или str).
            Используется когда notebook передаётся в теле запроса
            (REST multipart, GraphQL mutation, SOAP envelope) вместо
            обращения к зарегистрированному в реестре notebook.
        notebook_path_override: Прямой путь к ``.ipynb`` на Hub.
            Приоритетнее ``notebook_name`` из реестра.
        output_path: Кастомный путь для executed notebook
            (default — ``<stem>_executed.ipynb``).
        registry: Опц. инжекция реестра (для тестов).
        execution_service: Опц. инжекция execution service (для тестов).

    Returns:
        :class:`HubRunResult` с outputs.

    Raises:
        JupyterHubNotEnabledError: feature flag выключен.
        NotebookNotFoundError: notebook_name не зарегистрирован
            и не передан ``notebook_content``.
        NotebookParameterError: parameters не прошли валидацию.
        JupyterExecutionError: ошибка выполнения на Hub.
        JupyterHubError: ошибка API клиента.
    """
    import time

    user_params = dict(parameters or {})

    # 1. Feature flag gate
    try:
        from src.backend.core.config.features import feature_flags

        if not bool(getattr(feature_flags, "jupyter_hub_enabled", False)):
            raise JupyterHubNotEnabledError()
    except (ImportError, AttributeError):
        raise JupyterHubNotEnabledError() from None

    # 2. Resolve notebook spec — три источника в порядке приоритета:
    #    a) explicit notebook_path_override
    #    b) inline notebook_content (multipart/SOAP/GraphQL)
    #    c) notebook_name в реестре
    spec: NotebookSpec | None = None
    actual_path: str
    timeout: float = 300.0
    default_params: dict[str, Any] = {}
    is_temp_file: bool = False  # M7.2: cleanup inline-notebook temp after exec

    if notebook_path_override:
        # Явный путь — без обращения к реестру
        actual_path = notebook_path_override
    elif notebook_content is not None:
        # S204 retro-audit C-NEW-2: inline notebook (multipart upload, base64 в
        # SOAP/GraphQL) — выполняет произвольный Python в Hub kernel. Требуем
        # явного admin-opt-in через secure_settings.jupyter_inline_content_enabled.
        # Default False = deny (fail-closed). Registry-based notebooks остаются
        # доступны — они проходят ревью при регистрации в NotebookRegistry.
        from src.backend.core.config.security import secure_settings

        if not secure_settings.jupyter_inline_content_enabled:
            _logger.warning(
                "jupyter inline notebook rejected: feature disabled "
                "(notebook_name=%s, user=%s)",
                notebook_name,
                user_name,
            )
            raise JupyterHubNotEnabledError(
                "Inline notebook content disabled (secure.jupyter_inline_content_enabled=False). "
                "Use registry-based notebook or ask admin to enable."
            )

        # Audit-event: inline notebook use (даже при enabled — для traceability).
        try:
            from src.backend.core.audit.facade import emit_audit_safe

            await emit_audit_safe(
                action="jupyter.hub.run.inline",
                event="jupyter.hub.run.inline",
                outcome="success",
                extra={
                    "resource": notebook_name,
                    "principal": user_name,
                    "content_size": len(notebook_content),
                },
            )
        except (ImportError, RuntimeError, AttributeError, OSError, TypeError) as audit_exc:
            # cycle-9/D-AUDIT-905: narrow exceptions + observability.
            # Bare `except Exception` маскировал unrelated runtime errors
            # (KeyError, TypeError, ValueError). Audit emission — best-effort,
            # не блокируем notebook-run, но нужна visibility для диагностики.
            # TypeError включён т.к. emit_audit_safe() — defensive signature
            # (kwargs mismatch на audit schema evolution не должен ронять notebook-run).
            _logger.debug(
                "audit emit failed for jupyter.hub.run.inline: %s",
                audit_exc,
                exc_info=True,
            )

        # Сохраняем во временный файл и передаём как path.
        # M7.2: помечаем ``is_temp_file=True`` для post-execute cleanup
        # (раньше temp файл оставался в /tmp → утечка диска).
        actual_path = await _save_inline_notebook(
            notebook_name=notebook_name,
            content=notebook_content,
            output_path=output_path,
        )
        is_temp_file = output_path is None
    else:
        # Резолв через реестр
        reg = registry if registry is not None else get_notebook_registry()
        spec = reg.get(notebook_name)
        if spec is None:
            raise NotebookNotFoundError(notebook_name)
        actual_path = spec.path
        default_params = dict(spec.default_parameters)
        timeout = spec.timeout_seconds

    # 3. Apply defaults + validate
    merged_params = dict(default_params)
    merged_params.update(user_params)
    if spec is not None:
        validation_errors = spec.validate_parameters(merged_params)
        if validation_errors:
            raise NotebookParameterError(notebook_name, validation_errors)

    # 4. Execute через NotebookExecutionService (papermill param injection)
    svc = execution_service
    if svc is None:
        svc = _build_execution_service()

    start = time.monotonic()
    try:
        result = await svc.execute(
            notebook_path=actual_path,
            parameters=merged_params,
            user_name=user_name,
            timeout_seconds=timeout,
        )
    except _JupyterExecutionError as exc:
        _logger.error("Hub run failed: notebook=%s err=%s", notebook_name, exc)
        raise
    finally:
        # M7.2: best-effort cleanup inline temp файла (защита от /tmp
        # leak). Делаем unlink с поглощением OSError (файл уже мог быть
        # удалён или доступен только-read).
        if is_temp_file:
            try:
                os.unlink(actual_path)
            except OSError as cleanup_exc:
                _logger.warning(
                    "Hub inline temp cleanup failed for %s: %s",
                    actual_path,
                    cleanup_exc,
                )

    outputs = result.get("outputs", [])
    cells_executed = sum(1 for o in outputs if isinstance(o, dict) and o.get("outputs"))
    errors = _collect_errors(outputs)

    duration = time.monotonic() - start
    _logger.info(
        "Hub run ok: notebook=%s cells=%d duration=%.2fs errors=%d",
        notebook_name,
        cells_executed,
        duration,
        len(errors),
    )

    return HubRunResult(
        notebook_name=notebook_name,
        notebook_path=actual_path,
        parameters=merged_params,
        outputs=outputs,
        duration_seconds=duration,
        cells_executed=cells_executed,
        errors=errors,
    )


def _collect_errors(outputs: list[dict[str, Any]]) -> list[str]:
    """Собрать список cell-level errors из outputs."""
    errors: list[str] = []
    for cell_result in outputs:
        if not isinstance(cell_result, dict):
            continue
        for out in cell_result.get("outputs", []) or []:
            if isinstance(out, dict) and out.get("output_type") == "error":
                errors.append(
                    f"cell {cell_result.get('cell_index', '?')}: "
                    f"{out.get('ename', '?')}: {out.get('evalue', '')}"
                )
    return errors


async def _save_inline_notebook(
    notebook_name: str, content: bytes | str, output_path: str | None = None
) -> str:
    """Сохранить inline notebook (.ipynb) во временный файл и вернуть путь.

    Используется для multipart uploads, GraphQL base64, SOAP attachments.

    Args:
        notebook_name: Имя для slug (используется в имени файла).
        content: bytes или str (.ipynb JSON).
        output_path: Опц. явный путь.

    Returns:
        Путь к сохранённому файлу.
    """
    import json
    import os
    import tempfile

    # Если str — парсим как JSON чтобы валидировать структуру
    if isinstance(content, str):
        try:
            json.loads(content)  # validate JSON
        except json.JSONDecodeError as exc:
            raise HubRunError(
                f"notebook_content (str) is not valid JSON: {exc}"
            ) from exc
        content_bytes = content.encode("utf-8")
    else:
        # Validate bytes are valid JSON before writing
        try:
            json.loads(content.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HubRunError(
                f"notebook_content (bytes) is not valid JSON .ipynb: {exc}"
            ) from exc
        content_bytes = content

    if output_path:
        target = output_path
    else:
        # Создаём temp файл в /tmp или $JUPYTER_TMPDIR
        tmpdir = os.environ.get("JUPYTER_TMPDIR", tempfile.gettempdir())
        safe_name = "".join(
            c if c.isalnum() or c in "-_." else "_" for c in notebook_name
        )
        if not safe_name.endswith(".ipynb"):
            safe_name = f"{safe_name}.ipynb"
        target = os.path.join(tmpdir, f"hub_inline_{safe_name}")

    # Async write через to_thread (file IO не блокирует event loop)
    import asyncio

    def _write() -> None:
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "wb") as fh:
            fh.write(content_bytes)

    await asyncio.to_thread(_write)
    _logger.info("Saved inline notebook: path=%s bytes=%d", target, len(content_bytes))
    return target


def _build_execution_service() -> NotebookExecutionService:
    """Lazy-resolve execution service через DI singleton."""
    try:
        from src.backend.core.di.providers.jupyter import (
            get_notebook_execution_service_provider,
        )

        return get_notebook_execution_service_provider()
    except ImportError as exc:
        raise HubRunError(
            f"NotebookExecutionService provider not available: {exc}"
        ) from exc


__all__ = (
    "HubRunError",
    "HubRunResult",
    "JupyterHubNotEnabledError",
    "NotebookNotFoundError",
    "NotebookParameterError",
    "run_hub_notebook",
)
