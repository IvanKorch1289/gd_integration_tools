"""Гейт «у action'а один владелец» (``tools/check_action_ownership.py``).

Класс дефекта: action зарегистрирован в двух местах (ядро + плагин) —
владелец не один; либо ``payload_model``/capability расходятся между
ядром и плагином (F-01e: адаптер плагина затирал модель валидации payload).

Сценарии:
* чистый набор → нет нарушений;
* дубль владельца (ядро + плагин) → ``duplicate_owner``;
* расхождение ``payload_model`` → ``payload_model_mismatch``;
* конфликт манифестов → ``manifest_conflict``;
* ``--json`` → машиночитаемый отчёт;
* ``--strict`` → мягкие находки блокируют;
* сломанный файл → fail-closed (exit 2);
* текущий репозиторий → 0 нарушений.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.check_action_ownership import main, scan_claims

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]

_CORE_SOURCE = """
from src.backend.dsl.commands.registry import ActionHandlerSpec, action_handler_registry


def _register_orders() -> None:
    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="orders.create_skb_order",
                service_getter=get_order_service,
                service_method="create_skb_order",
                payload_model=OrderIdQuerySchema,
            ),
        ]
    )
"""

_PLUGIN_SOURCE = """
from src.backend.core.api import BasePlugin


class DemoPlugin(BasePlugin):
    name = "demo"

    async def on_register_actions(self, registry) -> None:
        async def _handler(**kwargs):
            return kwargs

        registry.register("{action}", _handler)
"""

_MANIFEST_SOURCE = """
name = "demo"
version = "1.0.0"

[[capabilities]]
name = "db.write"
scope = "orders"

[provides]
actions = [{actions}]
"""


@pytest.fixture
def demo_repo(tmp_path: Path) -> Path:
    """Мини-репозиторий: ядро + одно расширение."""
    (tmp_path / "core").mkdir()
    (tmp_path / "ext" / "demo").mkdir(parents=True)
    return tmp_path


def _write_core(repo: Path, source: str = _CORE_SOURCE) -> None:
    """Записать модуль регистрации actions ядра."""
    (repo / "core" / "registers.py").write_text(source, encoding="utf-8")


def _write_plugin(
    repo: Path,
    action: str = "orders.create_skb_order",
    *,
    manifest: bool = True,
    manifest_actions: list[str] | None = None,
) -> None:
    """Записать плагин расширения (и его манифест)."""
    plugin_dir = repo / "ext" / "demo"
    (plugin_dir / "plugin.py").write_text(
        _PLUGIN_SOURCE.format(action=action), encoding="utf-8"
    )
    if manifest:
        actions = manifest_actions if manifest_actions is not None else [action]
        rendered = ", ".join(f'"{item}"' for item in actions)
        (plugin_dir / "plugin.toml").write_text(
            _MANIFEST_SOURCE.format(actions=rendered), encoding="utf-8"
        )


def _run(repo: Path, *extra: str) -> int:
    """Запустить гейт на demo-репозитории."""
    return main(
        [
            "--core-root",
            str(repo / "core"),
            "--extensions-root",
            str(repo / "ext"),
            *extra,
        ]
    )


class TestActionOwnershipGate:
    """Сценарии гейта владения actions."""

    def test_clean_repo_has_no_violations(
        self, demo_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Ядро и плагин регистрируют разные action'ы — нарушений нет."""
        _write_core(demo_repo)
        _write_plugin(demo_repo, action="orders.other")

        assert _run(demo_repo) == 0
        assert "Владение actions: OK" in capsys.readouterr().out

    def test_duplicate_owner_is_detected(
        self, demo_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Action, зарегистрированный в ядре и в плагине, — нарушение."""
        _write_core(demo_repo)
        _write_plugin(demo_repo)

        assert _run(demo_repo) == 1
        out = capsys.readouterr().out
        assert "duplicate_owner" in out
        assert "orders.create_skb_order" in out

    def test_payload_model_mismatch_is_detected(
        self, demo_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Плагин без payload_model затирает модель ядра — нарушение."""
        _write_core(demo_repo)
        _write_plugin(demo_repo)

        assert _run(demo_repo) == 1
        out = capsys.readouterr().out
        assert "payload_model_mismatch" in out
        assert "OrderIdQuerySchema" in out

    def test_manifest_conflict_is_detected(
        self, demo_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Один action объявлен в двух манифестах — нарушение."""
        _write_core(demo_repo)
        _write_plugin(demo_repo, action="orders.other")
        second = demo_repo / "ext" / "demo2"
        second.mkdir()
        (second / "plugin.toml").write_text(
            _MANIFEST_SOURCE.format(actions='"orders.other"'), encoding="utf-8"
        )

        assert _run(demo_repo) == 1
        out = capsys.readouterr().out
        assert "manifest_conflict" in out

    def test_json_output_contains_findings(
        self, demo_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--json`` отдаёт машиночитаемый отчёт."""
        _write_core(demo_repo)
        _write_plugin(demo_repo)

        assert _run(demo_repo, "--json") == 1
        payload = json.loads(capsys.readouterr().out)
        codes = {finding["code"] for finding in payload["violations"]}
        assert "duplicate_owner" in codes
        assert payload["owners"]["orders.create_skb_order"] == ["core", "demo"]

    def test_strict_blocks_inventory_gaps(
        self, demo_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Мягкая находка (action объявлен, но не зарегистрирован) блокирует в strict."""
        _write_core(demo_repo)
        _write_plugin(
            demo_repo, action="orders.other", manifest_actions=["orders.missing"]
        )

        assert _run(demo_repo) == 0
        assert "unregistered_action" in capsys.readouterr().out

        assert _run(demo_repo, "--strict") == 1
        assert "unregistered_action" in capsys.readouterr().out

    def test_broken_source_fails_closed(
        self, demo_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Нечитаемый AST → exit 2 (результат неполон → падать)."""
        _write_core(demo_repo, source="def broken(:\n")
        _write_plugin(demo_repo, action="orders.other")

        assert _run(demo_repo) == 2
        assert "FAIL-CLOSED" in capsys.readouterr().err

    def test_current_repository_is_clean(self) -> None:
        """Текущий репозиторий: 0 нарушений (и в strict-режиме)."""
        assert main([]) == 0
        assert main(["--strict"]) == 0

    def test_scan_claims_collects_core_and_plugin(self, demo_repo: Path) -> None:
        """Claims собираются из ядра и из плагина."""
        _write_core(demo_repo)
        _write_plugin(demo_repo, action="orders.other")

        claims, manifests, errors = scan_claims(demo_repo / "core", demo_repo / "ext")
        assert errors == []
        assert {claim.action for claim in claims} == {
            "orders.create_skb_order",
            "orders.other",
        }
        assert {claim.kind for claim in claims} == {"core", "plugin"}
        assert [manifest.name for manifest in manifests] == ["demo"]
