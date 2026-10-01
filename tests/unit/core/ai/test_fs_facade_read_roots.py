"""F-AL: ``AIFsFacade.read`` ограничен корнями независимо от capability-check.

Аудит 2026-10-01: MCP-инструмент ``documents_to_markdown`` конструировал
``AIFsFacade(capability_check=None)`` — единственный барьер ``fs.read`` был
отключён, ограничения по корню не было. Воспроизведено на живом рантайме:
``/etc/passwd`` читался целиком (3360 B).

Фикс добавляет ``allowed_read_roots`` — проверку **после** ``resolve()``,
независимую от наличия callback'а. R-V15-4 требует сохранить возможность
читать проект, поэтому корень по умолчанию для production-wiring — корень
репозитория, а не workspace агента.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.backend.core.ai.errors import FsForbiddenReadError
from src.backend.core.ai.fs_facade import AIFsFacade
from src.backend.core.ai.workspace_manager import AIWorkspaceManager

PROJECT_ROOT: Path = Path(__file__).resolve().parents[4]


@pytest.fixture
def workspace_manager(tmp_path: Path) -> AIWorkspaceManager:
    """Менеджер workspaces на временном каталоге.

    Args:
        tmp_path: Временный каталог pytest.

    Returns:
        Настроенный ``AIWorkspaceManager``.
    """
    return AIWorkspaceManager(root=tmp_path / "ai_ws")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Каталог, имитирующий корень проекта с читаемым файлом.

    Args:
        tmp_path: Временный каталог pytest.

    Returns:
        Корень «проекта» с файлом ``doc.md``.
    """
    root = tmp_path / "project"
    root.mkdir()
    (root / "doc.md").write_text("# project doc", encoding="utf-8")
    return root


def _facade(wm: AIWorkspaceManager, roots: list[Path] | None) -> AIFsFacade:
    """Собрать фасад с заданными корнями чтения.

    Args:
        wm: Менеджер workspaces.
        roots: Корни чтения либо ``None`` (legacy-режим).

    Returns:
        Сконструированный ``AIFsFacade``.
    """
    return AIFsFacade(
        workspace_manager=wm,
        capability_check=None,
        plugin="mcp",
        allowed_read_roots=roots,
    )


# ── Fail-closed: то, что было дырой ────────────────────────────────────


def test_system_file_denied(
    workspace_manager: AIWorkspaceManager, project: Path
) -> None:
    """``/etc/passwd`` не читается, даже когда capability-check выключен.

    Args:
        workspace_manager: Менеджер workspaces.
        project: Корень «проекта».
    """
    facade = _facade(workspace_manager, [project])
    with pytest.raises(FsForbiddenReadError):
        facade.read("/etc/passwd")


def test_traversal_denied(workspace_manager: AIWorkspaceManager, project: Path) -> None:
    """``..``-traversal за пределы корня запрещён.

    Args:
        workspace_manager: Менеджер workspaces.
        project: Корень «проекта».
    """
    facade = _facade(workspace_manager, [project])
    with pytest.raises(FsForbiddenReadError):
        facade.read(project / ".." / ".." / "etc" / "passwd")


def test_symlink_escape_denied(
    workspace_manager: AIWorkspaceManager, project: Path
) -> None:
    """Симлинк наружу из корня запрещён (проверка после ``resolve()``).

    Args:
        workspace_manager: Менеджер workspaces.
        project: Корень «проекта».
    """
    outside = project.parent / "secret.txt"
    outside.write_text("top-secret", encoding="utf-8")
    link = project / "link.txt"
    link.symlink_to(outside)
    facade = _facade(workspace_manager, [project])
    with pytest.raises(FsForbiddenReadError):
        facade.read(link)


def test_empty_roots_denies_everything(workspace_manager: AIWorkspaceManager) -> None:
    """Пустой список корней → fail-closed, а не «читать всё».

    Args:
        workspace_manager: Менеджер workspaces.
    """
    facade = _facade(workspace_manager, [])
    with pytest.raises(FsForbiddenReadError, match="пуст"):
        facade.read(__file__)


# ── R-V15-4 сохранён: проект читать можно ──────────────────────────────


def test_project_file_allowed(
    workspace_manager: AIWorkspaceManager, project: Path
) -> None:
    """Файл внутри корня читается — R-V15-4 не сломан.

    Args:
        workspace_manager: Менеджер workspaces.
        project: Корень «проекта».
    """
    facade = _facade(workspace_manager, [project])
    assert facade.read(project / "doc.md") == b"# project doc"


def test_read_as_markdown_confined(
    workspace_manager: AIWorkspaceManager, project: Path
) -> None:
    """``read_as_markdown`` (путь MCP-инструмента) тоже ограничен.

    Args:
        workspace_manager: Менеджер workspaces.
        project: Корень «проекта».
    """
    facade = _facade(workspace_manager, [project])
    assert facade.read(project / "doc.md")
    with pytest.raises(FsForbiddenReadError):
        facade.read("/etc/hostname")


# ── Legacy-режим сохранён явно, а не молча ─────────────────────────────


def test_roots_not_declared_keeps_legacy_behaviour(
    workspace_manager: AIWorkspaceManager, tmp_path: Path
) -> None:
    """``allowed_read_roots=None`` — старое поведение (backward compatibility).

    Args:
        workspace_manager: Менеджер workspaces.
        tmp_path: Временный каталог pytest.
    """
    target = tmp_path / "data.txt"
    target.write_text("hello", encoding="utf-8")
    facade = AIFsFacade(workspace_manager=workspace_manager, capability_check=None)
    assert facade.read(target) == b"hello"


# ── Production-wiring не должен обходить ограничение ───────────────────


def _kwargs_of_call(path: Path, func_name: str) -> set[str]:
    """Извлечь имена keyword-аргументов вызова ``AIFsFacade(...)`` по AST.

    Args:
        path: Путь к исходнику.
        func_name: Имя функции-фабрики, внутри которой искать вызов.

    Returns:
        Множество переданных keyword-аргументов.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function_types = (ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, function_types) or node.name != func_name:
            continue
        for call in ast.walk(node):
            if (
                isinstance(call, ast.Call)
                and getattr(call.func, "id", "") == "AIFsFacade"
            ):
                return {kw.arg for kw in call.keywords if kw.arg}
    return set()


def test_mcp_document_tool_sets_read_roots() -> None:
    """``tools_document.py`` обязан передать ``allowed_read_roots``.

    Регрессия F-AL: возврат ``capability_check=None`` без корней.
    """
    source = (
        PROJECT_ROOT
        / "src"
        / "backend"
        / "entrypoints"
        / "mcp"
        / "mcp_server"
        / "tools_document.py"
    )
    assert "allowed_read_roots" in _kwargs_of_call(source, "documents_to_markdown")


def test_ai_safety_setup_sets_read_roots() -> None:
    """DI-factory ``AIFsFacade`` также обязан передать ``allowed_read_roots``.

    Регрессия F-AL: ``except Exception → capability_check = None``.
    """
    source = (
        PROJECT_ROOT
        / "src"
        / "backend"
        / "plugins"
        / "composition"
        / "ai_safety_setup.py"
    )
    assert "allowed_read_roots" in _kwargs_of_call(source, "_build_fs_facade")
