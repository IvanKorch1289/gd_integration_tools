"""Plugin sub-app для ``manage.py``.

P1 CLI decomposition W9 (v4 §10 P1, 2026-09-24): извлечено из ``manage.py``
для bounded maintainability. ``plugin`` — Typer sub-app с 4 subcommands
для plugin runtime operations (hot-swap/new/serve/publish).

Per v4 §10 P1 «CLI decomposition»: «декомпозировать manage.py малыми
командами на уже используемом Typer/Rich, сохраняя CLI contract и help
snapshots. Не создавать второй CLI».

CLI contract (preserved 100%):
- ``python manage.py plugin hot-swap <name>`` — hot-reload плагина без рестарта.
- ``python manage.py plugin new <name>`` — scaffold V11 плагина в extensions/.
- ``python manage.py plugin serve --name <n> [--port 8001] [--watch]`` —
  запуск local dev-сервера с одним плагином.
- ``python manage.py plugin publish --plugin <n> --version <semver>
  [--cosign-key PATH] [--marketplace-url URL] [--dry-run] [--skip-sbom]
  [--skip-cosign] [--skip-upload]`` — bundle + SBOM + cosign + upload.

Typer sub-app pattern (consistent с W5/W6/W8):
- ``plugin_app = typer.Typer(help="Plugin runtime operations (hot-swap, scaffold).")``
- ``app.add_typer(plugin_app, name="plugin")`` в manage.py
- Команды регистрируются через ``@plugin_app.command("name")``
"""

from __future__ import annotations

from pathlib import Path

import typer

plugin_app = typer.Typer(help="Plugin runtime operations (hot-swap, scaffold).")


@plugin_app.command("hot-swap")
def plugin_hot_swap(
    name: str = typer.Argument(..., help="Имя плагина (из plugin.toml)"),
) -> None:
    """Hot-swap (reload без рестарта) одного in-tree плагина.

    Перечитывает ``extensions/<name>/plugin.toml``, перезагружает Python-
    модуль ``entry_class`` через :func:`importlib.reload`, заново выполняет
    capability allocation и lifecycle. Audit-event ``plugin.hot_swap``
    логируется через CapabilityGate.

    Пример::

        python manage.py plugin hot-swap example_plugin
    """
    import asyncio

    async def _run() -> int:
        try:
            # Lazy-import, чтобы CLI стартовал быстро.
            from src.backend.core.plugin_runtime.hot_swap import HotSwapError, hot_swap
        except ImportError as exc:
            typer.echo(f"ERR: hot_swap unavailable: {exc}", err=True)
            return 1

        # PluginLoaderV11 живёт в app.state — поднимаем минимальное
        # bootstrap-окружение, чтобы CLI мог дотянуться до loader.
        # В Sprint 7 — stub: ищем app.state.plugin_loader_v11, если
        # приложение уже запущено. Иначе создаём свежий loader для
        # in-tree скана.
        loader = None
        try:
            from src.backend.main import app as fastapi_app  # noqa: PLC0415

            loader = getattr(fastapi_app.state, "plugin_loader_v11", None)
        except Exception:  # noqa: BLE001 — best-effort lookup
            loader = None

        if loader is None:
            typer.echo(
                "ERR: PluginLoader не инициализирован (app.state.plugin_loader_v11). "
                "Запустите приложение с FEATURE_PLUGIN_LOADER_ENABLED=true.",
                err=True,
            )
            return 1

        try:
            result = await hot_swap(name, loader)
        except HotSwapError as exc:
            typer.echo(f"Plugin not found / hot-swap failed: {exc}", err=True)
            return 1

        typer.echo(
            f"Plugin {result.plugin_name}: {result.old_version} → "
            f"{result.new_version} ({result.status})"
        )
        if result.reason:
            typer.echo(f"  reason: {result.reason}")
        return 0 if result.status == "reloaded" else 1

    raise typer.Exit(asyncio.run(_run()))


@plugin_app.command("new")
def plugin_new(name: str = typer.Argument(..., help="snake_case имя плагина")) -> None:
    """Создать каркас V11 плагина в ``extensions/<name>/``.

    Эквивалент ``make new-plugin NAME=<name>``.
    """
    try:
        from tools.codegen_plugin import scaffold_plugin
    except ImportError as exc:
        typer.echo(f"ERR: codegen_plugin недоступен: {exc}", err=True)
        raise typer.Exit(1) from exc

    try:
        plugin_root = scaffold_plugin(name)
    except (FileExistsError, ValueError) as exc:
        typer.echo(f"ERR: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"Created plugin: {plugin_root}")
    typer.echo(f"Next: edit {plugin_root}/plugin.toml and {plugin_root}/plugin.py")


@plugin_app.command("serve")
def plugin_serve(
    name: str = typer.Option(..., "--name", help="Имя плагина (extensions/<name>)"),
    port: int = typer.Option(8001, "--port", help="Порт backend dev-сервера"),
    watch: bool = typer.Option(False, "--watch", help="Hot-reload через watchfiles"),
) -> None:
    """Sprint 14 K5 W4: запуск local dev-сервера с одним плагином."""
    from importlib import util as _util  # noqa: PLC0415

    pds_path = Path(__file__).resolve().parent / "tools" / "plugin_dev_server.py"
    spec = _util.spec_from_file_location("_gdit_plugin_dev_server", pds_path)
    if spec is None or spec.loader is None:
        typer.echo(f"ERR: plugin_dev_server недоступен: {pds_path}", err=True)
        raise typer.Exit(1)
    module = _util.module_from_spec(spec)
    spec.loader.exec_module(module)
    argv = ["--name", name, "--port", str(port)]
    if watch:
        argv.append("--watch")
    raise typer.Exit(module.main(argv))


@plugin_app.command("publish")
def plugin_publish(
    name: str = typer.Option(..., "--plugin", help="Имя плагина (extensions/<name>)"),
    version: str = typer.Option(..., "--version", help="SemVer плагина"),
    cosign_key: Path | None = typer.Option(
        None, "--cosign-key", help="Путь к приватному ключу cosign"
    ),
    marketplace_url: str | None = typer.Option(
        None, "--marketplace-url", envvar="MARKETPLACE_URL"
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
    skip_sbom: bool = typer.Option(False, "--skip-sbom"),
    skip_cosign: bool = typer.Option(False, "--skip-cosign"),
    skip_upload: bool = typer.Option(False, "--skip-upload"),
) -> None:
    """Sprint 14 W3: bundle + SBOM + cosign + upload плагина."""
    from tools.publish_plugin import PublishConfig  # noqa: PLC0415
    from tools.publish_plugin import run as publish_run

    plugin_dir = Path("extensions") / name
    cfg = PublishConfig(
        plugin=name,
        version=version,
        plugin_dir=plugin_dir,
        cosign_key=cosign_key,
        marketplace_url=marketplace_url,
        dry_run=dry_run,
        skip_sbom=skip_sbom,
        skip_cosign=skip_cosign,
        skip_upload=skip_upload,
    )
    result = publish_run(cfg)
    for msg in result.messages:
        typer.echo(f"[publish-plugin] {msg}")
    raise typer.Exit(0)


__all__ = ("plugin_app",)
