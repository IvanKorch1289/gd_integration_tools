"""Wave 4 DoD smoke-проверка plugin-системы.

Загружает `plugins/example_plugin` через `PluginLoader.load_from_path`
и проверяет:

1. action `example.echo` зарегистрирован в `ActionHandlerRegistry`.
2. hook `orders.before_create` появляется в `RepositoryHookRegistry`.
3. override `orders.get_by_id` зарегистрирован.
4. shutdown идёт без ошибок.

Запуск: ``uv run python tools/check_plugin_system.py``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from src.backend.dsl.commands.action_registry import ActionHandlerRegistry
from src.backend.dsl.engine.plugin_registry import ProcessorPluginRegistry
from src.backend.services.plugins import PluginLoader, RepositoryHookRegistry

ROOT = Path(__file__).resolve().parents[1]


def _check(condition: bool, message: str) -> None:
    """raise RuntimeError, если ``condition`` ложно — для DoD-скрипта."""
    if not condition:
        raise RuntimeError(f"DoD check failed: {message}")


async def main() -> int:
    """DoD: загрузить example_plugin и проверить регистрации."""
    action_reg = ActionHandlerRegistry()
    proc_reg = ProcessorPluginRegistry()
    repo_hooks = RepositoryHookRegistry()
    loader = PluginLoader(
        action_registry=action_reg,
        processor_registry=proc_reg,
        repo_hook_registry=repo_hooks,
    )

    info = await loader.load_from_path(ROOT / "plugins" / "example_plugin")
    _check(info is not None, "plugin not loaded")
    if info is None:
        raise RuntimeError("info is None after _check")
    _check(info.name == "example_plugin", f"name mismatch: {info.name}")
    _check(info.version == "0.1.0", f"version mismatch: {info.version}")

    actions = action_reg.list_actions()
    _check("example.echo" in actions, f"example.echo missing in {actions}")
    _check(action_reg.is_registered("example.echo"), "example.echo not registered")

    hooks = list(repo_hooks.hooks_for("orders", "before_create"))
    _check(len(hooks) == 1, f"expected 1 hook, got {len(hooks)}")

    override = repo_hooks.get_override("orders", "get_by_id")
    _check(override is not None, "override missing")
    if override is None:
        raise RuntimeError("override is None after _check")

    result = await override(None, "ord-42")
    expected = {"id": "ord-42", "stub": True, "source": "example_plugin v0.1.0"}
    _check(result == expected, f"override behaviour wrong: {result}")

    spec = action_reg._handlers["example.echo"]
    carrier = spec.service_getter()
    echo_payload = await carrier.call(payload={"hi": "there"})
    _check(
        echo_payload["echo"] == {"hi": "there"},
        f"echo handler returned {echo_payload!r}",
    )

    await loader.shutdown_all()
    stats = repo_hooks.stats()
    print(
        f"OK plugin_system: name={info.name} version={info.version} "
        f"hooks={stats['hooks']} overrides={stats['overrides']} "
        f"actions={len(actions)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
