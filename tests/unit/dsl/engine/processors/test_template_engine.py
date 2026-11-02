"""Unit-тесты TemplateEngine processors."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.template_engine import (
    RenderTemplateFileProcessor,
    RenderTemplateProcessor,
)


def _ex(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


@pytest.mark.asyncio
async def test_render_template_from_body() -> None:
    proc = RenderTemplateProcessor(
        template_string="Hello {{ name }}!", result_property="out"
    )
    exchange = _ex({"name": "Alice"})
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.properties["out"] == "Hello Alice!"


@pytest.mark.asyncio
async def test_render_template_from_body_field() -> None:
    proc = RenderTemplateProcessor(
        template_string="{{ greeting }}",
        context_from="body.context",
        result_property="out",
    )
    exchange = _ex({"context": {"greeting": "Hi"}})
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.properties["out"] == "Hi"


@pytest.mark.asyncio
async def test_render_template_from_properties() -> None:
    proc = RenderTemplateProcessor(
        template_string="Value: {{ val }}",
        context_from="properties.ctx",
        result_property="out",
    )
    exchange = _ex({})
    exchange.properties["ctx"] = {"val": 42}
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.properties["out"] == "Value: 42"


@pytest.mark.asyncio
async def test_render_template_non_dict_body() -> None:
    proc = RenderTemplateProcessor(
        template_string="Hello {{ name }}!", result_property="out"
    )
    exchange = _ex("text")
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.properties["out"] == "Hello !"


# ── ADR-0419: Jinja2 без sandbox = SSTI ─────────────────────────────


@pytest.mark.asyncio
async def test_render_template_blocks_ssti_dunder_access() -> None:
    """ADR-0419: sandbox не отдаёт ``__class__`` (обычный Jinja2 — отдаёт)."""
    proc = RenderTemplateProcessor(
        template_string="{{ ''.__class__ }}", result_property="out"
    )
    exchange = _ex({})
    await proc.process(exchange, None)  # type: ignore[arg-type]

    rendered = exchange.properties.get("out", "")
    assert "class" not in rendered
    assert "str" not in rendered


@pytest.mark.asyncio
async def test_render_template_blocks_ssti_mro_access() -> None:
    """ADR-0419: обход через ``__mro__`` блокируется (SecurityError → error)."""
    proc = RenderTemplateProcessor(
        template_string="{{ ''.__class__.__mro__ }}", result_property="out"
    )
    exchange = _ex({})
    await proc.process(exchange, None)  # type: ignore[arg-type]

    assert exchange.error is not None
    assert "out" not in exchange.properties


@pytest.mark.asyncio
async def test_render_template_blocks_ssti_globals_access() -> None:
    """ADR-0419: доступ к ``__globals__`` заблокирован."""
    proc = RenderTemplateProcessor(
        template_string="{{ self.__init__.__globals__ }}", result_property="out"
    )
    exchange = _ex({})
    await proc.process(exchange, None)  # type: ignore[arg-type]

    assert exchange.error is not None


@pytest.mark.asyncio
async def test_render_template_still_renders_normal_templates() -> None:
    """Sandbox не ломает обычные шаблоны."""
    proc = RenderTemplateProcessor(
        template_string="Hello {{ name }}!", result_property="out"
    )
    exchange = _ex({"name": "Alice"})
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.properties["out"] == "Hello Alice!"
    assert exchange.error is None


@pytest.mark.asyncio
async def test_render_template_file_blocks_ssti(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0419: файловый шаблон тоже рендерится в sandbox."""
    monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "evil.j2").write_text("{{ ''.__class__.__mro__ }}", encoding="utf-8")

    proc = RenderTemplateFileProcessor(path="evil.j2", result_property="out")
    exchange = _ex({})
    await proc.process(exchange, None)  # type: ignore[arg-type]

    assert exchange.error is not None
    assert "out" not in exchange.properties
