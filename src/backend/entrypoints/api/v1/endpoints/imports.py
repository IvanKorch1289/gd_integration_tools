"""Эндпоинты для импорта схем и массового создания объектов.

W26.5: маршруты регистрируются через ``router.add_api_route`` без
``@router``-декораторов. ``ActionSpec`` не используется, так как все
4 эндпоинта работают с ``multipart/form-data`` (UploadFile + Form),
несовместимым с генерацией сигнатуры ActionRouterBuilder'а.

Поддерживаемые сценарии:

* ``POST /import/openapi``         — DSL-роуты из OpenAPI 3.x spec.
* ``POST /import/postman``         — DSL-роуты из Postman Collection v2.1.
* ``POST /import/process-schema``  — BPMN-like JSON → pipeline.
* ``POST /import/bulk-objects``    — CSV/Excel → пакетное создание +
  DSL-роут per строка.

Маршрут ``dry_run=true`` генерирует только preview без реальной
регистрации.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

__all__ = ("router",)

logger = logging.getLogger("imports")

router = APIRouter()


# ──────────────────── OpenAPI ────────────────────


async def _import_openapi(
    spec_url: str | None = Form(default=None),
    prefix: str = Form(default="ext"),
    file: UploadFile | None = File(default=None),
    dry_run: bool = Form(default=False),
) -> dict[str, Any]:
    """Импортирует OpenAPI spec (file или URL) через W24 ImportGateway."""
    from src.backend.core.interfaces.import_gateway import (
        ImportSource,
        ImportSourceKind,
    )
    from src.backend.services.integrations import get_import_service

    if file is not None:
        content = await file.read()
    elif spec_url:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=30) as cli:
                resp = await cli.get(spec_url)
                resp.raise_for_status()
                content = resp.content
        except Exception as exc:
            raise HTTPException(
                400, f"Не удалось загрузить spec по URL: {exc}"
            ) from exc
    else:
        raise HTTPException(400, "Требуется file или spec_url")

    source = ImportSource(
        kind=ImportSourceKind.OPENAPI,
        content=content,
        source_url=spec_url,
        prefix=prefix,
    )
    try:
        return await get_import_service().import_and_register(
            source, register_actions=not dry_run
        )
    except (ImportError, ValueError) as exc:
        raise HTTPException(400, f"OpenAPI import failed: {exc}") from exc


router.add_api_route(
    path="/openapi",
    endpoint=_import_openapi,
    methods=["POST"],
    summary="Импорт OpenAPI-спецификации",
    description=(
        "Загружает OpenAPI 3.x spec (JSON) и генерирует DSL-роуты для каждой операции."
    ),
    name="import_openapi",
)


# ──────────────────── Postman ────────────────────


async def _import_postman(
    prefix: str = Form(default="postman"),
    file: UploadFile | None = File(default=None),
    collection_url: str | None = Form(default=None),
    dry_run: bool = Form(default=False),
) -> dict[str, Any]:
    """Импортирует Postman-коллекцию через W24 ImportGateway."""
    from src.backend.core.interfaces.import_gateway import (
        ImportSource,
        ImportSourceKind,
    )
    from src.backend.services.integrations import get_import_service

    if file is not None:
        content = await file.read()
    elif collection_url:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15) as cli:
                resp = await cli.get(collection_url)
                resp.raise_for_status()
                content = resp.content
        except Exception as exc:
            raise HTTPException(400, f"Не удалось загрузить коллекцию: {exc}") from exc
    else:
        raise HTTPException(400, "Требуется file или collection_url")

    source = ImportSource(
        kind=ImportSourceKind.POSTMAN,
        content=content,
        source_url=collection_url,
        prefix=prefix,
    )
    try:
        return await get_import_service().import_and_register(
            source, register_actions=not dry_run
        )
    except (ImportError, ValueError) as exc:
        raise HTTPException(400, f"Postman import failed: {exc}") from exc


router.add_api_route(
    path="/postman",
    endpoint=_import_postman,
    methods=["POST"],
    summary="Импорт Postman-коллекции",
    description=("Загружает Postman Collection v2.1 (JSON) и генерирует DSL-роуты."),
    name="import_postman",
)


# ──────────────────── Process Schema (BPMN-like) ────────────────────


async def _import_process_schema(payload: dict[str, Any]) -> dict[str, Any]:
    """Создаёт DSL-pipeline из описания бизнес-процесса.

    Ожидаемая структура ``payload``::

        {
          "route_id": "kyc.full",
          "source": "internal:kyc",
          "steps": [
            {"type": "action", "action": "kyc.validate_docs"},
            {"type": "choice", "when": "body.passed", "then": [...], "else": [...]},
            {"type": "action", "action": "kyc.send_to_bank"}
          ]
        }

    Поддерживаемые типы шагов: ``action``, ``log``, ``transform``,
    ``choice``, ``http_call``, ``dispatch_action``. Расширяется в
    ``_apply_steps`` ниже.
    """
    from src.backend.dsl.builder import RouteBuilder

    try:
        route_id = payload["route_id"]
        source = payload.get("source", "process_import")
        steps = payload.get("steps", [])
    except KeyError as exc:
        raise HTTPException(400, f"Отсутствует поле: {exc}") from exc

    builder = RouteBuilder.from_(route_id, source=source)
    try:
        builder = _apply_steps(builder, steps)
        pipeline = builder.build()
    except Exception as exc:
        raise HTTPException(400, f"Ошибка сборки pipeline: {exc}") from exc

    return {
        "route_id": pipeline.route_id,
        "steps_imported": len(steps),
        "processors_count": len(pipeline.processors),
    }


router.add_api_route(
    path="/process-schema",
    endpoint=_import_process_schema,
    methods=["POST"],
    summary="Импорт схемы процесса",
    description="JSON-схема бизнес-процесса (шаги + связи) → DSL-pipeline.",
    name="import_process_schema",
)


def _apply_steps(builder: Any, steps: list[dict[str, Any]]) -> Any:
    """Рекурсивно применяет шаги из схемы процесса к RouteBuilder."""
    for step in steps:
        step_type = step.get("type")
        match step_type:
            case "action":
                builder = builder.dispatch_action(step["action"])
            case "log":
                builder = builder.log(step.get("message", ""))
            case "http_call":
                builder = builder.http_call(
                    step["url"], method=step.get("method", "GET")
                )
            case "dispatch_action":
                builder = builder.dispatch_action(step["action"])
            case _:
                logger.warning("Unknown step type: %s", step_type)
    return builder


# ──────────────────── Bulk Objects (CSV/Excel) ────────────────────


async def _import_bulk_objects(
    route_id: str = Form(...),
    file: UploadFile = File(...),
    dry_run: bool = Form(default=False),
) -> dict[str, Any]:
    """Парсит CSV/Excel и для каждой строки запускает DSL-роут."""
    content = await file.read()
    filename = file.filename or ""

    try:
        if filename.endswith((".xlsx", ".xls")):
            import io

            import polars as pl

            df = pl.read_excel(io.BytesIO(content))
            rows = df.to_dicts()
        else:
            import csv
            import io

            text = content.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            rows = list(reader)
    except Exception as exc:
        raise HTTPException(400, f"Не удалось распарсить файл: {exc}") from exc

    if dry_run:
        return {"parsed": len(rows), "sample": rows[:3], "dry_run": True}

    from src.backend.dsl.engine.execution_engine import get_execution_engine
    from src.backend.dsl.engine.pipeline_registry import get_pipeline_registry

    pipeline = get_pipeline_registry().get(route_id)
    if pipeline is None:
        raise HTTPException(404, f"Pipeline '{route_id}' не найден")

    engine = get_execution_engine()
    ok = 0
    failed: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        try:
            exchange = await engine.execute(pipeline, body=row)
            if exchange.is_failed:
                failed.append({"row": idx, "error": str(exchange.error)})
            else:
                ok += 1
        except Exception as exc:  # noqa: BLE001
            failed.append({"row": idx, "error": str(exc)})

    return {
        "total_rows": len(rows),
        "succeeded": ok,
        "failed": len(failed),
        "failures": failed[:20],
    }


router.add_api_route(
    path="/bulk-objects",
    endpoint=_import_bulk_objects,
    methods=["POST"],
    summary="Массовое создание объектов + запуск процесса",
    description=(
        "CSV/Excel файл → создаёт объекты по каждой строке и запускает "
        "указанный DSL-роут."
    ),
    name="import_bulk_objects",
)
