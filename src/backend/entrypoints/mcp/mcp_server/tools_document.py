"""MCP-сервер на базе FastMCP.

Автоматически экспортирует все зарегистрированные actions
из ActionHandlerRegistry как MCP tools. Дополнительно предоставляет
инструментальные tools для управления маршрутами, конвертации
форматов, шаблонов и мониторинга.

Категории tools:
- Action tools: автогенерация из ActionHandlerRegistry (50+)
- Route tools: list/execute/inspect DSL маршруты
- Template tools: list/instantiate шаблоны Pipeline
- Convert tools: конвертация форматов (JSON↔XML/YAML/CSV/MsgPack)
- System tools: health check, metrics, feature flags
"""

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.core.serialization.msgspec_hotpath import encode_json

logger = get_logger(__name__)


# ── document tools (_register_document_tools) ──


def _register_document_tools(mcp: Any) -> None:
    """Tools для работы с файловыми документами (Sprint S5 hotfix).

    ``documents_to_markdown`` — конвертирует файл (PDF/DOCX/PPTX/XLSX/
    HTML/CSV/JSON) в Markdown через markitdown-engine (с legacy
    fallback). Используется AI-агентами для подачи структурированного
    контекста в LLM.
    """

    @mcp.tool(
        name="documents_to_markdown",
        description=(
            "Конвертирует файл в Markdown через markitdown (PDF/DOCX/PPTX/"
            "XLSX/HTML/CSV/JSON/MD/TXT). Возвращает JSON: "
            "{markdown, engine, mime, size_bytes, warnings, filename}. "
            "При недоступности markitdown — fallback на legacy plain-text."
        ),
    )
    async def documents_to_markdown(path: str, mime: str | None = None) -> str:
        from pathlib import Path as _Path

        from src.backend.core.ai.fs_facade import AIFsFacade
        from src.backend.core.ai.workspace_manager import AIWorkspaceManager
        from src.backend.core.config.ai import ai_workspace_settings

        try:
            target = _Path(path)
            if not target.exists():
                return encode_json({"error": f"File not found: {path}"}).decode("utf-8")

            wm = AIWorkspaceManager(root=ai_workspace_settings.workspace_root)
            facade = AIFsFacade(
                workspace_manager=wm, capability_check=None, plugin="mcp"
            )
            text, meta = await facade.read_as_markdown(target, mime=mime)
            return encode_json(
                {
                    "markdown": text,
                    "engine": meta.get("engine"),
                    "mime": meta.get("mime"),
                    "size_bytes": meta.get("size_bytes"),
                    "warnings": list(meta.get("warnings") or []),
                    "filename": meta.get("filename"),
                }
            ).decode("utf-8")
        except Exception as exc:
            return encode_json({"error": str(exc)}).decode("utf-8")
