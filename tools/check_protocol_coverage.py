"""Wave 1.5 — статическая проверка покрытия action унифицированным dispatch.

Цель: подтвердить, что entrypoint-адаптеры WS / SSE / Webhook / Express
проходят через единый мост ``src/entrypoints/_action_bridge.py``,
а не вызывают DSL напрямую (как было до Wave 1.5). Также проверяет,
что сам мост экспортирует ``dispatch_action_or_dsl`` и что у Tier 1
CRUD-actions действительно есть зарегистрированные ``ActionMetadata``
(минимальный smoke).

Запуск::

    python tools/check_protocol_coverage.py

Exit code 0 — все entrypoints используют ``dispatch_action_or_dsl``;
Exit code 1 — хотя бы один entrypoint не подключён.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINTS = ROOT / "src" / "entrypoints"
BRIDGE_FILE = ENTRYPOINTS / "_action_bridge.py"

# entrypoint → (файл, ожидаемый action-id источник для smoke).
_TARGETS: dict[str, Path] = {
    "ws": ENTRYPOINTS / "websocket" / "ws_handler.py",
    "webhook": ENTRYPOINTS / "webhook" / "handler.py",
    "express": ENTRYPOINTS / "express" / "router.py",
    "sse": ENTRYPOINTS / "sse" / "handler.py",
}

_BRIDGE_IMPORT_MARKER = "from src.backend.entrypoints._action_bridge import"  # noqa: S105
_BRIDGE_CALL_MARKER = "dispatch_action_or_dsl"  # noqa: S105


def _check_bridge_module() -> list[str]:
    """Проверяет, что сам мост существует и публикует API."""
    errors: list[str] = []
    if not BRIDGE_FILE.is_file():
        errors.append(f"missing bridge module: {BRIDGE_FILE.relative_to(ROOT)}")
        return errors
    text = BRIDGE_FILE.read_text(encoding="utf-8")
    if "def dispatch_action_or_dsl" not in text:
        errors.append(
            "_action_bridge.py не определяет async def dispatch_action_or_dsl"
        )
    if "BridgeResult" not in text:
        errors.append("_action_bridge.py не определяет BridgeResult")
    return errors


def _check_entrypoint(transport: str, path: Path) -> list[str]:
    """Возвращает список ошибок для конкретного транспорта."""
    errors: list[str] = []
    if not path.is_file():
        errors.append(f"{transport}: missing file {path.relative_to(ROOT)}")
        return errors
    text = path.read_text(encoding="utf-8")
    if _BRIDGE_IMPORT_MARKER not in text:
        errors.append(
            f"{transport}: {path.relative_to(ROOT)} — нет импорта {_BRIDGE_IMPORT_MARKER}"
        )
    if _BRIDGE_CALL_MARKER not in text:
        errors.append(
            f"{transport}: {path.relative_to(ROOT)} — нет вызова {_BRIDGE_CALL_MARKER}(...)"
        )
    return errors


def _check_actions_registered() -> list[str]:
    """Smoke: подтверждает, что setup.py регистрирует action-handlers.

    Без рантайма: парсим ``src/dsl/commands/setup.py`` на наличие хотя бы
    одного вызова ``action_handler_registry.register(...)``. Цель —
    отметить деградацию реестра, если кто-то снёс все регистрации.
    """
    setup_file = ROOT / "src" / "dsl" / "commands" / "setup.py"
    if not setup_file.is_file():
        return [f"missing {setup_file.relative_to(ROOT)} (Tier 1 setup)"]
    text = setup_file.read_text(encoding="utf-8")
    if "action_handler_registry.register" not in text:
        return [
            "src/backend/dsl/commands/setup.py — не найдено action_handler_registry.register(...)"
        ]
    return []


def main() -> int:
    """Точка входа: печатает сводку и возвращает exit code."""
    all_errors: list[str] = []
    all_errors.extend(_check_bridge_module())
    for transport, path in _TARGETS.items():
        all_errors.extend(_check_entrypoint(transport, path))
    all_errors.extend(_check_actions_registered())

    if all_errors:
        print("[protocol_coverage] FAIL")
        for line in all_errors:
            print(f"  - {line}")
        return 1

    print("[protocol_coverage] OK")
    print(f"  bridge: {BRIDGE_FILE.relative_to(ROOT)}")
    for transport, path in _TARGETS.items():
        print(f"  {transport:8s} → {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
