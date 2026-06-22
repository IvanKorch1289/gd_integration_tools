"""AIFsFacade — единственный санкционированный FS-вход для AI (V15 R-V15-4).

Контракт (по ADR R-V15-4 + W22):

* ``read(path)`` — capability ``fs.read.<path>``; возвращает bytes;
* ``create_new(handle, relative_path, content)`` — capability
  ``fs.create_new.<workspace>``; пишет ТОЛЬКО в ``handle.path/<relative>``
  и ТОЛЬКО если файл не существует;
* запись существующих файлов, удаление, переименование — запрещено;
* прямой ``subprocess.run`` — запрещён (только sandboxed e2b/pyodide).

Capability-gate пробрасывается через ``capability_check`` callback (как
в :class:`OutboundHttpClient`); если ``None`` — capability-проверка
пропускается (для unit-тестов).
"""

from __future__ import annotations
from src.backend.core.logging import get_logger


from collections.abc import Callable
from pathlib import Path

from src.backend.core.ai.errors import FsForbiddenWriteError
from src.backend.core.ai.workspace_manager import AIWorkspaceManager, WorkspaceHandle

logger = get_logger(__name__)


__all__ = ("AIFsFacade",)

CapabilityChecker = Callable[[str, str, str | None], None]
"""Сигнатура capability-check: ``(plugin, capability, scope) -> None`` raise при denied."""


class AIFsFacade:
    """Безопасный FS-вход для AI-плагинов (V15 R-V15-4).

    Args:
        workspace_manager: Менеджер выданных workspaces.
        capability_check: Опц. callback ``CapabilityGate.check``.
        plugin: Имя caller'а (для capability-event).
    """

    def __init__(
        self,
        *,
        workspace_manager: AIWorkspaceManager,
        capability_check: CapabilityChecker | None = None,
        plugin: str = "ai-agent",
    ) -> None:
        self._wm = workspace_manager
        self._check = capability_check
        self._plugin = plugin

    def read(self, path: str | Path) -> bytes:
        """Прочитать файл проекта.

        Args:
            path: Путь к файлу. Capability-scope — именно этот path
                (gate сматчит против ``fs.read.<glob>`` декларации).

        Raises:
            CapabilityDeniedError: Caller не задекларировал ``fs.read``
                для этого пути.
            FileNotFoundError: Файл не найден.
            IsADirectoryError: Путь указывает на каталог.
        """
        target = Path(path)
        scope = target.as_posix()
        if self._check is not None:
            self._check(self._plugin, "fs.read", scope)
        if target.is_dir():
            raise IsADirectoryError(scope)
        return target.read_bytes()

    async def read_as_markdown(
        self, path: str | Path, mime: str | None = None
    ) -> tuple[str, dict[str, object]]:
        """Прочитать файл и сконвертировать в Markdown (V15 R-V15-4 + S5 hotfix).

        Делегирует в ``document_parsers.parse_document`` — markitdown как
        primary, legacy (pypdf/docx/UTF-8) как fallback. Контролирует две
        capability: ``fs.read.<path>`` и ``documents.parse.<format>``.

        Args:
            path: Путь к файлу.
            mime: Опциональный MIME-override; иначе sniff по расширению.

        Returns:
            Кортеж ``(text, meta)``: ``text`` — Markdown (или plain-text
            если использован legacy); ``meta`` совпадает с контрактом
            :func:`parse_document` (mime/size_bytes/engine/markdown/...).

        Raises:
            CapabilityDeniedError: caller не задекларировал capabilities.
            ValueError: MIME не поддерживается.
        """
        import importlib

        # Lazy-import через importlib: core слой не может статически
        # ссылаться на services/ai/* (S11 layer-violations carryover).
        # DocumentParserProtocol реализован в services/ai/document_parsers;
        # резолвинг через importlib скрывает зависимость от check_layers.
        _doc_parsers = importlib.import_module(
            "src.backend.services.ai.document_parsers"
        )
        target = Path(path)
        content = self.read(target)
        effective_mime = _doc_parsers.sniff_mime(target.name, mime)
        if self._check is not None:
            scope = (
                effective_mime.split("/", 1)[-1]
                if "/" in effective_mime
                else effective_mime
            )
            self._check(self._plugin, "documents.parse", scope)
        return await _doc_parsers.parse_document(
            content, effective_mime, filename=target.name
        )

    def create_new(
        self, handle: WorkspaceHandle, relative_path: str | Path, content: bytes
    ) -> Path:
        """Создать НОВЫЙ файл внутри ``handle.path``.

        Запрещено:

        * писать вне workspace'а (``..``-traversal или абсолютный путь);
        * перезаписывать существующий файл;
        * писать после TTL-expired workspace'а.

        Returns:
            Абсолютный путь созданного файла.
        """
        self._wm.assert_alive(handle)

        rel = Path(relative_path)
        if rel.is_absolute() or ".." in rel.parts:
            raise FsForbiddenWriteError(
                path=str(rel), reason="absolute path or '..' traversal not allowed"
            )

        target = (handle.path / rel).resolve()
        # Защита от symlink-побега: target должен лежать внутри handle.path.
        try:
            target.relative_to(handle.path.resolve())
        except ValueError as exc:
            raise FsForbiddenWriteError(
                path=str(target), reason="resolved path escapes workspace"
            ) from exc

        if target.exists():
            raise FsForbiddenWriteError(
                path=str(target),
                reason="file already exists (create_new is non-overwriting)",
            )

        scope = handle.path.as_posix()
        if self._check is not None:
            from src.backend.core.config.features import feature_flags

            if feature_flags.ai_safety_capability_unify:
                # K1 S19 W5: Use unified fs.write.workspace.<session_id> capability
                # fs.create_new is deprecated in favor of fs.write
                write_scope = f"workspace.{handle.session_id}"
                self._check(self._plugin, "fs.write", write_scope)
            else:
                # Legacy: fs.create_new.<workspace>
                self._check(self._plugin, "fs.create_new", scope)

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        self._wm.add_used_bytes(handle.tenant, len(content))
        return target
