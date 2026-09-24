"""Workflow sub-app для ``manage.py``.

P1 CLI decomposition W6 (v4 §10 P1, 2026-09-24): извлечено из ``manage.py``
для bounded maintainability. ``workflow`` — Typer sub-app с 4 subcommands
для workflow DSL management (import/dryrun/version/cancel).

Per v4 §10 P1 «CLI decomposition»: «декомпозировать manage.py малыми
командами на уже используемом Typer/Rich, сохраняя CLI contract и help
snapshots. Не создавать второй CLI».

CLI contract (preserved 100%):
- ``python manage.py workflow import --file <path> [--format bpmn|yaml] [--name ...] [--show]``
  — импорт BPMN/YAML → WorkflowCompilerRegistry.
- ``python manage.py workflow dryrun --file <path> [--format ...] [--input ...] [--record] [--replay ...] [--out ...]``
  — симуляция выполнения без Temporal.
- ``python manage.py workflow version <name> [--all]`` — workflow версии.
- ``python manage.py workflow cancel <workflow_id> [--reason ...] [--namespace ...]``
  — отменить running workflow.

Typer sub-app pattern (consistent с W5 scaffold):
- ``workflow_app = typer.Typer(help="Workflow DSL management (Sprint 4).")``
- ``app.add_typer(workflow_app, name="workflow")`` в manage.py
- Команды регистрируются через ``@workflow_app.command("name")``
"""

from __future__ import annotations

from pathlib import Path

import typer

workflow_app = typer.Typer(help="Workflow DSL management (Sprint 4).")


@workflow_app.command("import")
def workflow_import(
    file: Path = typer.Option(..., "--file", help="Путь до BPMN/YAML файла."),
    fmt: str = typer.Option(
        "bpmn", "--format", help="Формат входного файла: bpmn | yaml."
    ),
    name: str | None = typer.Option(None, "--name", help="Имя workflow (override)."),
    show: bool = typer.Option(
        False, "--show", help="Вывести JSON-представление workflow в stdout."
    ),
) -> None:
    """Импорт workflow из BPMN 2.0 или YAML в WorkflowCompilerRegistry (Sprint 4 Wave B).

    Поддерживает форматы:
        * ``bpmn`` — BPMN 2.0 XML через :mod:`dsl.workflow.bpmn_importer`.
        * ``yaml`` — YAML-декларация через :mod:`dsl.workflow.yaml_io`.

    Args:
        file: Путь к файлу.
        fmt: Формат (bpmn | yaml).
        name: Опц. имя workflow (override default).
        show: Если True — печатает model_dump в stdout.
    """
    if not file.exists():
        typer.echo(f"ERR: файл не найден: {file}", err=True)
        raise typer.Exit(code=2)

    content = file.read_text(encoding="utf-8")

    if fmt == "bpmn":
        from src.backend.dsl.workflow.bpmn_importer import import_bpmn

        declaration = import_bpmn(content, name=name, check_feature_flag=False)
    elif fmt == "yaml":
        from src.backend.dsl.workflow.yaml_io import from_yaml

        declaration = from_yaml(content)
        if name is not None:
            declaration = declaration.model_copy(update={"name": name})
    else:
        typer.echo(f"ERR: неизвестный формат: {fmt!r} (ожидалось bpmn|yaml)", err=True)
        raise typer.Exit(code=2)

    typer.echo(
        f"Workflow импортирован: name={declaration.name!r}, "
        f"steps={len(declaration.steps)}, version={declaration.version}"
    )
    if show:
        import json

        typer.echo(
            json.dumps(
                declaration.model_dump(mode="json"), indent=2, ensure_ascii=False
            )
        )


@workflow_app.command("dryrun")
def workflow_dryrun(
    file: Path = typer.Option(..., "--file", help="Путь до BPMN/YAML файла workflow."),
    fmt: str = typer.Option(
        "yaml", "--format", help="Формат входного файла: bpmn | yaml."
    ),
    input: str | None = typer.Option(  # noqa: A002
        None, "--input", help="JSON входные данные для workflow."
    ),
    record: bool = typer.Option(
        False, "--record", help="Записать trace в .dryrun_trace.json."
    ),
    replay: Path | None = typer.Option(
        None, "--replay", help="Путь до .dryrun_trace.json для replay-режима."
    ),
    out: Path | None = typer.Option(
        None, "--out", help="Сохранить JSON-отчёт в файл (default — stdout)."
    ),
) -> None:
    """K3 S5 W10 — workflow dryrun: симуляция выполнения без подключения к Temporal.

    Возвращает JSON-отчёт со списком activities + signals + timer-fires + state
    transitions. Поддерживает три режима:

    * нормальный: симуляция с input через детерминированный fake-runtime;
    * ``--record``: записывает trace в ``.dryrun_trace.json`` для regression-тестов;
    * ``--replay <file>``: повторяет ранее записанный trace (fail-on-mismatch).

    Под feature flag ``feature_flags.workflow_dryrun_enabled`` (default-OFF).

    Args:
        file: Путь до workflow YAML/BPMN.
        fmt: Формат (bpmn|yaml).
        input: JSON-payload входа.
        record: Записать trace.
        replay: Replay из существующего trace.
        out: Куда сохранить отчёт.
    """
    import json

    try:
        from src.backend.core.config.features import feature_flags

        if not feature_flags.workflow_dryrun_enabled:
            typer.echo(
                "WARN: feature_flags.workflow_dryrun_enabled = False; "
                "выполняется в read-only режиме (без записи trace).",
                err=True,
            )
    except Exception:  # noqa: BLE001, S110  # silent fallback (best-effort cleanup, non-critical)
        pass

    if not file.exists():
        typer.echo(f"ERR: файл не найден: {file}", err=True)
        raise typer.Exit(code=2)

    content = file.read_text(encoding="utf-8")

    if fmt == "bpmn":
        from src.backend.dsl.workflow.bpmn_importer import import_bpmn

        declaration = import_bpmn(content, check_feature_flag=False)
    elif fmt == "yaml":
        from src.backend.dsl.workflow.yaml_io import from_yaml

        declaration = from_yaml(content)
    else:
        typer.echo(f"ERR: неизвестный формат: {fmt!r}", err=True)
        raise typer.Exit(code=2)

    input_data: dict = {}
    if input:
        try:
            input_data = json.loads(input)
        except json.JSONDecodeError as exc:
            typer.echo(f"ERR: --input не валидный JSON: {exc}", err=True)
            raise typer.Exit(code=2)

    # Запуск симуляции (lazy-import чтобы не подтягивать temporal SDK).
    from src.backend.dsl.workflow.dryrun import run_workflow_dryrun

    report = run_workflow_dryrun(declaration=declaration, input_data=input_data)

    if record:
        trace_path = Path(".dryrun_trace.json")
        trace_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        typer.echo(f"Trace записан в {trace_path}")

    if replay is not None:
        if not replay.exists():
            typer.echo(f"ERR: replay-файл не найден: {replay}", err=True)
            raise typer.Exit(code=2)
        expected = json.loads(replay.read_text(encoding="utf-8"))
        if expected.get("activities") != report.get("activities"):
            typer.echo(
                f"FAIL: replay mismatch! activities differ:\n"
                f"  expected: {expected.get('activities')}\n"
                f"  got:      {report.get('activities')}",
                err=True,
            )
            raise typer.Exit(code=1)
        typer.echo("OK: replay matches recorded trace")

    output = json.dumps(report, indent=2, ensure_ascii=False, default=str)
    if out is not None:
        out.write_text(output, encoding="utf-8")
        typer.echo(f"Отчёт сохранён в {out}")
    else:
        typer.echo(output)


@workflow_app.command("version")
def workflow_version(
    name: str = typer.Argument(..., help="Имя workflow (workflow_id)."),
    show_all: bool = typer.Option(
        False, "--all", help="Показать все workflow_id в реестре."
    ),
) -> None:
    """Sprint 7 K3 — current + history workflow версий из WorkflowVersionRegistry.

    Выводит default-версию (current) и полную history по semver. Реестр
    заполняется через декоратор ``@workflow_versioned("X.Y.Z")`` при
    импорте workflow-модулей. Под feature flag
    ``feature_flags.workflow_versioning_strict`` (default-OFF).

    Args:
        name: workflow_id (или любая строка при ``--all``).
        show_all: Вывести все workflow_id, зарегистрированные в реестре.
    """
    from src.backend.dsl.workflow.versioning import get_global_registry

    registry = get_global_registry()

    if show_all:
        ids = registry.all_workflow_ids()
        if not ids:
            typer.echo("Реестр workflow версий пуст.")
            return
        typer.echo(f"Registered workflows ({len(ids)}):")
        for wf_id in ids:
            current = registry.get_default(wf_id)
            current_str = f"v{current.semver}" if current else "(no default)"
            typer.echo(f"  - {wf_id}: current={current_str}")
        return

    current = registry.get_default(name)
    history = registry.history(name)

    if not history:
        typer.echo(f"Workflow {name!r} не найден в реестре.", err=True)
        raise typer.Exit(code=1)

    if current is not None:
        typer.echo(f"Current default: {name} v{current.semver}")
    else:
        typer.echo(f"Workflow {name}: default-версия не назначена.")

    typer.echo(f"History ({len(history)}):")
    for v in history:
        marker = " (default)" if v.default_version else ""
        typer.echo(f"  - v{v.semver}{marker}")


@workflow_app.command("cancel")
def workflow_cancel(
    workflow_id: str = typer.Argument(..., help="Workflow ID (Temporal)."),
    reason: str = typer.Option("", "--reason", help="Причина отмены."),
    namespace: str = typer.Option("default", "--namespace", help="Workflow namespace."),
) -> None:
    """Sprint 12 K3 W7 — отменить running workflow по ID.

    Использует :class:`WorkflowBackend.cancel_workflow` и эмитит
    audit-event ``workflow.cancel`` через
    :class:`WorkflowAuditSink` (если зарегистрирован).

    Пример::

        python manage.py workflow cancel wf-abc-123 --reason "user_requested"
    """
    import asyncio

    async def _run() -> int:
        from src.backend.core.workflow.backend import WorkflowHandle
        from src.backend.infrastructure.workflow.factory import create_workflow_backend

        backend = await create_workflow_backend(kind="auto")
        handle = WorkflowHandle(
            workflow_id=workflow_id, run_id=workflow_id, namespace=namespace
        )
        try:
            await backend.cancel_workflow(handle=handle)
        except Exception as exc:  # noqa: BLE001
            typer.echo(f"ERR: cancel failed: {exc}", err=True)
            return 1

        try:
            from src.backend.services.audit.workflow_audit_sink import (
                get_workflow_audit_sink,
            )

            sink = get_workflow_audit_sink()
            if sink is not None:
                await sink.emit(
                    event_type="workflow.cancel",
                    workflow_id=workflow_id,
                    tenant_id=None,
                    payload={
                        "reason": reason,
                        "caller": "manage.py",
                        "namespace": namespace,
                    },
                )
        except Exception:  # noqa: BLE001, S110  # silent fallback (best-effort cleanup, non-critical)
            pass

        typer.echo(f"OK: cancelled workflow {workflow_id!r} (reason={reason!r})")
        return 0

    exit_code = asyncio.run(_run())
    raise typer.Exit(code=exit_code)


__all__ = ("workflow_app",)
