"""B-11 regression test (cycle 33): ClickHouseAuditService использует facade, не importlib.

Проверяет что:
1. ``service.py`` НЕ импортирует ``importlib`` (static-source check).
2. ``service.py`` ссылается на ``src.backend.core.audit.facade.get_jsonl_backend``
   (capability-checked путь).
3. ``get_jsonl_backend`` живёт в facade и возвращает настоящий
   ``JsonlAuditBackend`` instance (lazy import внутри функции).
4. End-to-end: ClickHouse fail → DLQ-запись через facade без raise.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.audit.facade import get_jsonl_backend
from src.backend.services.audit.clickhouse_audit_service import (
    AuditEvent,
    ClickHouseAuditService,
)

# tests/unit/services/audit/test_xxx.py → parents[4] = project root.
SERVICE_PATH = (
    Path(__file__).resolve().parents[4]
    / "src"
    / "backend"
    / "services"
    / "audit"
    / "clickhouse_audit_service"
    / "service.py"
)


def _make_event(**kwargs: Any) -> AuditEvent:
    """Строит минимальный AuditEvent для тестов."""
    defaults: dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc),
        "event_type": "test.dlq.facade",
        "tenant_id": "tenant-b11",
        "user_id": "user-b11",
        "route_name": "/api/v1/cycle33",
        "payload": {"cycle": 33},
        "severity": "info",
    }
    defaults.update(kwargs)
    return AuditEvent(**defaults)


def _make_failing_client() -> AsyncMock:
    """AsyncMock-клиент ClickHouse, ``insert()`` всегда кидает."""
    client = AsyncMock()
    client.insert = AsyncMock(
        side_effect=RuntimeError("ClickHouse unavailable: connection refused")
    )
    return client


def _flags_on() -> MagicMock:
    """feature_flags с audit_clickhouse_enabled=True."""
    mock_flags = MagicMock()
    mock_flags.audit_clickhouse_enabled = True
    return mock_flags


# ─── Тест 1: static-source check — нет importlib в service.py ──────────────────


def test_service_does_not_use_importlib() -> None:
    """``service.py`` НЕ должен использовать ``importlib.import_module``.

    Bypass через ``importlib`` обходит ``check_layers.py`` и должен быть
    заменён на явный capability-checked facade. Проверяем AST, не
    docstring (комментарии могут упоминать ``importlib``).
    """
    import ast

    tree = ast.parse(SERVICE_PATH.read_text(encoding="utf-8"))
    importlib_imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "importlib":
                    importlib_imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "importlib":
                importlib_imports.append(node.module or "")

    assert not importlib_imports, (
        f"service.py содержит importlib-bypass ({importlib_imports}); "
        f"заменить на facade get_jsonl_backend"
    )

    # Также проверим, что нет прямого импорта infrastructure.
    infra_imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith(
                "src.backend.infrastructure.audit"
            ):
                infra_imports.append(node.module)
    assert not infra_imports, (
        f"service.py содержит прямой импорт из infrastructure: "
        f"{infra_imports} — должен идти через facade"
    )


# ─── Тест 2: static-source check — facade вызывается ───────────────────────────


def test_service_uses_facade_get_jsonl_backend() -> None:
    """``service.py`` должен вызывать ``get_jsonl_backend`` из facade."""
    source = SERVICE_PATH.read_text(encoding="utf-8")

    assert "from src.backend.core.audit.facade import" in source, (
        "service.py должен импортировать get_jsonl_backend из "
        "src.backend.core.audit.facade"
    )
    # Конкретный символ присутствует в import-строке.
    assert re.search(
        r"from\s+src\.backend\.core\.audit\.facade\s+import\s+[^#\n]*\bget_jsonl_backend\b",
        source,
    ), "service.py должен явно импортировать get_jsonl_backend из facade"


# ─── Тест 3: facade возвращает настоящий JsonlAuditBackend ─────────────────────


def test_facade_get_jsonl_backend_returns_real_instance(tmp_path: Path) -> None:
    """``get_jsonl_backend`` должен вернуть рабочий ``JsonlAuditBackend``."""
    target = tmp_path / "facade_dlq.jsonl"

    backend = get_jsonl_backend(target)

    # Реальный instance, не Mock/proxy.
    from src.backend.infrastructure.audit.jsonl_audit import JsonlAuditBackend

    assert isinstance(backend, JsonlAuditBackend), (
        f"get_jsonl_backend должен вернуть JsonlAuditBackend, "
        f"got {type(backend).__name__}"
    )
    assert backend._path == target


@pytest.mark.asyncio
async def test_facade_backend_appends_records(tmp_path: Path) -> None:
    """Backend из facade реально пишет записи в JSONL."""
    target = tmp_path / "facade_write.jsonl"
    backend = get_jsonl_backend(target)

    from src.backend.core.interfaces.audit import AuditRecord

    record: AuditRecord = AuditRecord(
        {"event": "facade.test", "action": "write", "entity_id": "e-1"}
    )
    await backend.append(record)

    assert target.exists()
    lines = target.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event"] == "facade.test"
    assert payload["entity_id"] == "e-1"


# ─── Тест 4: end-to-end — ClickHouse fail → DLQ через facade ──────────────────


@pytest.mark.asyncio
async def test_clickhouse_failure_routes_to_facade_dlq(tmp_path: Path) -> None:
    """Сбой ClickHouse + dlq_path → DLQ-запись через facade (без importlib).

    Финальный proof: ``service._get_dlq_backend()`` создаёт backend через
    ``get_jsonl_backend``, и downstream ``_send_to_dlq`` корректно пишет
    в JSONL без raise.
    """
    dlq_path = tmp_path / "e2e.jsonl"
    service = ClickHouseAuditService(
        client=_make_failing_client(), dlq_path=dlq_path
    )
    event = _make_event(event_id="cycle33-e2e", event_type="b11.event")

    with patch("src.backend.core.config.features.feature_flags", _flags_on()):
        # Fire-and-forget: исключения не пробрасываются.
        await service.emit(event)

    assert dlq_path.exists()
    record = json.loads(dlq_path.read_text(encoding="utf-8").strip())
    assert record["event"] == "b11.event"
    assert record["entity_id"] == "cycle33-e2e"
    assert record["action"] == "clickhouse_emit_failed"
    assert record["metadata"]["dlq_reason"] == "clickhouse_unavailable"


# ─── Тест 5: backend создаётся один раз (singleton в DLQ-lock) ─────────────────


@pytest.mark.asyncio
async def test_dlq_backend_is_singleton_via_facade(tmp_path: Path) -> None:
    """Повторные вызовы ``_get_dlq_backend`` возвращают один и тот же instance."""
    dlq_path = tmp_path / "singleton.jsonl"
    service = ClickHouseAuditService(
        client=_make_failing_client(), dlq_path=dlq_path
    )

    backend_a = service._get_dlq_backend()
    backend_b = service._get_dlq_backend()

    assert backend_a is backend_b, (
        "_get_dlq_backend должен вернуть cached instance (double-checked lock)"
    )


# ─── Тест 6: dlq_path=None → backend None (legacy silent-loss) ─────────────────


def test_no_dlq_path_returns_none() -> None:
    """``dlq_path=None`` → ``_get_dlq_backend`` возвращает None без facade-вызова."""
    service = ClickHouseAuditService(client=_make_failing_client())

    assert service._get_dlq_backend() is None
