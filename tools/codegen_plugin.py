"""Sprint 7 Team T5 — Scaffolder для in-tree V11 плагина.

Запуск::

    uv run python tools/codegen_plugin.py --name my_plugin

Или через Makefile::

    make new-plugin NAME=my_plugin

Создаёт каркас::

    extensions/<name>/
    ├── __init__.py
    ├── plugin.toml          (manifest V11)
    ├── plugin.py            (BasePlugin наследник)
    ├── README.md
    ├── functions/
    │   └── __init__.py
    ├── routes/
    ├── workflows/
    ├── tests/
    │   └── __init__.py
    └── frontend/
        └── pages/

Не модифицирует существующие файлы (FileExistsError, если плагин уже есть).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

__all__ = ("main", "scaffold_plugin")

ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS_DIR = ROOT / "extensions"


def _validate_name(name: str) -> str:
    """Проверяет, что имя плагина соответствует snake_case и не зарезервировано."""
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", name):
        raise ValueError(
            f"invalid plugin name {name!r}: must be snake_case "
            "(lowercase + digits + underscore, 2-64 chars, start with letter)"
        )
    if name in {"core", "core_entities", "test", "tests"}:
        raise ValueError(f"plugin name {name!r} is reserved")
    return name


def _to_pascal(name: str) -> str:
    """``my_plugin`` → ``MyPlugin``."""
    return "".join(p.capitalize() for p in name.split("_"))


def scaffold_plugin(
    name: str,
    *,
    target_dir: Path | None = None,
    features: list[str] | None = None,
    capabilities: list[str] | None = None,
    with_frontend: bool = False,
    overwrite: bool = False,
) -> Path:
    """Создаёт каркас V11 плагина в ``extensions/<name>/``.

    Args:
        name: snake_case имя плагина.
        target_dir: Корень extensions/ (по умолчанию — ROOT/extensions/).
        features: Список actions для добавления в provides (``['ping','echo']``).
        capabilities: Список capability в виде ``"name:scope"`` или просто
            ``"name"``. Будет записан в plugin.toml как ``[[capabilities]]``.
        with_frontend: Если True — создаёт frontend/pages/ (default — да).
        overwrite: Если True — перезатирает существующий каталог.

    Returns:
        Путь к созданному каталогу плагина.

    Raises:
        FileExistsError: Если каталог плагина уже существует и overwrite=False.
        ValueError: Если имя невалидно.
    """
    _validate_name(name)
    extensions_root = target_dir or EXTENSIONS_DIR
    plugin_root = extensions_root / name
    if plugin_root.exists() and not overwrite:
        raise FileExistsError(f"plugin already exists: {plugin_root}")
    if plugin_root.exists() and overwrite:
        import shutil

        shutil.rmtree(plugin_root)

    plugin_root.mkdir(parents=True)
    (plugin_root / "functions").mkdir()
    (plugin_root / "routes").mkdir()
    (plugin_root / "workflows").mkdir()
    (plugin_root / "tests").mkdir()
    if with_frontend:
        (plugin_root / "frontend").mkdir()
        (plugin_root / "frontend" / "pages").mkdir()

    class_name = _to_pascal(name) + "Plugin"

    # Готовим actions list (provides + handler-stubs).
    actions_list = [f"{name}.{f}" for f in (features or [])]
    actions_toml = ", ".join(f'"{a}"' for a in actions_list)

    # Готовим capability-блок.
    caps_blocks: list[str] = []
    for cap in capabilities or []:
        if ":" in cap:
            cap_name, cap_scope = cap.split(":", 1)
        else:
            cap_name, cap_scope = cap, ""
        block = f"""
[[capabilities]]
name = "{cap_name}"
"""
        if cap_scope:
            block += f'scope = "{cap_scope}"\n'
        caps_blocks.append(block)
    caps_toml = (
        "".join(caps_blocks)
        if caps_blocks
        else """
# [[capabilities]]
# name = "mq.publish"
# scope = "{name}.events.*"
""".replace("{name}", name)
    )

    # plugin.toml (V11 manifest)
    (plugin_root / "plugin.toml").write_text(
        f"""# V11 plugin manifest для {name}.
# Описание формата — docs/adr/ADR-042-plugin-toml-schema.md.
# Каталог capabilities — docs/adr/ADR-044-capability-vocabulary.md.

name = "{name}"
version = "0.1.0"
requires_core = ">=0.2,<0.3"
entry_class = "extensions.{name}.plugin.{class_name}"
tenant_aware = false
description = "TODO: краткое описание плагина {name}"

# ─── Runtime capabilities (sandbox gate) ──────────────────────────
{caps_toml}
# ─── Декларативный inventory ──────────────────────────────────────
[provides]
actions = [{actions_toml}]
repositories = []
processors = []
sources = []
sinks = []
schemas = []
""",
        encoding="utf-8",
    )

    # plugin.py
    (plugin_root / "plugin.py").write_text(
        f'''"""Reference V11 plugin: {name}.

Зарегистрирован в ``extensions/{name}/plugin.toml`` как ``entry_class``.
Lifecycle: on_load → on_register_actions → on_shutdown.
"""

from __future__ import annotations

import logging

from src.backend.core.interfaces.plugin import (
    ActionRegistryProtocol,
    BasePlugin,
    PluginContext,
)

__all__ = ("{class_name}",)

_logger = logging.getLogger("extensions.{name}.plugin")


class {class_name}(BasePlugin):
    """Базовый класс плагина {name}."""

    name = "{name}"
    version = "0.1.0"

    async def on_load(self, ctx: PluginContext) -> None:
        """Инициализация ресурсов плагина."""
        _logger.info("Plugin {name} loaded (v%s)", self.version)

    async def on_register_actions(
        self, registry: ActionRegistryProtocol
    ) -> None:
        """Регистрация HTTP/CLI actions плагина.

        Пример::

            registry.register("{name}.echo", self._echo)
        """
        # TODO: зарегистрировать actions плагина

    async def on_shutdown(self) -> None:
        """Graceful shutdown."""
        _logger.info("Plugin {name} shutdown")
''',
        encoding="utf-8",
    )

    # __init__.py
    (plugin_root / "__init__.py").write_text(
        f'"""Plugin {name} (V11 in-tree)."""\n', encoding="utf-8"
    )
    (plugin_root / "functions" / "__init__.py").write_text(
        f'"""Бизнес-функции плагина {name} для call_function()."""\n', encoding="utf-8"
    )
    (plugin_root / "tests" / "__init__.py").write_text("", encoding="utf-8")

    # README.md
    (plugin_root / "README.md").write_text(
        f"""# Plugin: {name}

Reference V11 plugin (Sprint 7 scaffold).

## Структура

- `plugin.toml` — V11 manifest (name/version/requires_core/capabilities/provides)
- `plugin.py` — entry_class (BasePlugin наследник)
- `functions/` — бизнес-функции для call_function()
- `routes/` — DSL routes (route.toml + *.dsl.yaml)
- `workflows/` — workflow YAML
- `tests/` — unit-тесты плагина
- `frontend/pages/` — Streamlit pages плагина

## Запуск

1. Добавить capabilities в `plugin.toml`.
2. Зарегистрировать actions в `plugin.py::on_register_actions`.
3. `make plugin-schema` — проверить manifest.
4. Hot-swap: `python manage.py plugin hot-swap {name}`.

## TODO

- [ ] Описание бизнес-логики в README
- [ ] Capability list
- [ ] Actions / routes / workflows
""",
        encoding="utf-8",
    )

    return plugin_root


class PluginCodegen:
    """OO-обёртка над :func:`scaffold_plugin` (Sprint 9 K5 W3).

    Закрывает A-5 техдолг ("PluginCodegen class missing"). Используется
    как импортируемый API из ``Makefile.codegen`` и для интеграционных
    тестов:

    .. code-block:: python

        codegen = PluginCodegen(target_dir=Path("/tmp/extensions"))
        plugin_dir = codegen.scaffold(
            name="kyc_verify",
            capabilities=["net.outbound.compliance:external"],
            features=["score", "verify"],
        )

    Args:
        target_dir: каталог extensions/; если None — берётся ``EXTENSIONS_DIR``.
        default_with_frontend: scaffold с frontend/pages/ по умолчанию.
        default_overwrite: разрешить overwrite по умолчанию.
    """

    def __init__(
        self,
        *,
        target_dir: Path | None = None,
        default_with_frontend: bool = False,
        default_overwrite: bool = False,
    ) -> None:
        self._target_dir = target_dir
        self._default_with_frontend = default_with_frontend
        self._default_overwrite = default_overwrite

    def scaffold(
        self,
        name: str,
        *,
        features: list[str] | None = None,
        capabilities: list[str] | None = None,
        with_frontend: bool | None = None,
        overwrite: bool | None = None,
    ) -> Path:
        """Создаёт каркас плагина.

        Args:
            name: snake_case имя плагина.
            features: список action'ов (provides).
            capabilities: список capability spec'ов.
            with_frontend: override default_with_frontend.
            overwrite: override default_overwrite.

        Returns:
            Путь к созданному каталогу.

        Raises:
            FileExistsError: если плагин уже есть и overwrite=False.
            ValueError: невалидное имя.
        """
        return scaffold_plugin(
            name,
            target_dir=self._target_dir,
            features=features or [],
            capabilities=capabilities or [],
            with_frontend=(
                with_frontend
                if with_frontend is not None
                else self._default_with_frontend
            ),
            overwrite=(overwrite if overwrite is not None else self._default_overwrite),
        )

    def list_existing(self) -> list[str]:
        """Список уже scaffolded плагинов в target_dir."""
        root = self._target_dir or EXTENSIONS_DIR
        if not root.exists():
            return []
        return sorted(
            entry.name
            for entry in root.iterdir()
            if entry.is_dir()
            and not entry.name.startswith(("_", "."))
            and (entry / "plugin.toml").exists()
        )


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI."""
    parser = argparse.ArgumentParser(description="Codegen V11 plugin skeleton.")
    parser.add_argument("--name", required=True, help="snake_case имя плагина")
    parser.add_argument(
        "--features",
        default="",
        help="comma-separated actions to register, e.g. 'ping,echo'",
    )
    parser.add_argument(
        "--capabilities",
        default="",
        help="comma-separated capabilities, e.g. 'mq.publish:topic.*,http.outbound'",
    )
    parser.add_argument(
        "--with-frontend",
        action="store_true",
        help="создать frontend/pages/ для Streamlit pages",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="перезаписать существующий каталог плагина",
    )
    args = parser.parse_args(argv)

    features = [f.strip() for f in args.features.split(",") if f.strip()]
    capabilities = [c.strip() for c in args.capabilities.split(",") if c.strip()]

    try:
        plugin_root = scaffold_plugin(
            args.name,
            features=features,
            capabilities=capabilities,
            with_frontend=args.with_frontend,
            overwrite=args.overwrite,
        )
    except (FileExistsError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Created plugin: {plugin_root}")
    print(f"Next: edit {plugin_root}/plugin.toml and {plugin_root}/plugin.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
