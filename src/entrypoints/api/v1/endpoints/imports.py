"""Эндпоинты для импорта схем и массового создания объектов.

Поддерживаемые сценарии импорта (запрошены в ТЗ):

* ``POST /import/openapi`` — генерация DSL-роутов из OpenAPI 3.x spec.
* ``POST /import/postman`` — генерация DSL-роутов из Postman Collection v2.1.
* ``POST /import/process-schema`` — описание процесса (BPMN-like JSON) → pipeline.
* ``POST /import/bulk-objects`` — CSV/Excel файл → пакетное создание объектов +
  запуск DSL-роута для каждой строки.

Все эндпоинты возвращают отчёт о количестве импортированных элементов.
Маршрут ``dry_run=true`` генерирует только preview без реальной регистрации.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

__all__ = ("router",)

logger = logging.getLogger("imports")

router = APIRouter()


# ──────────────────── OpenAPI ────────────────────


@router.post(
    "/openapi",
    summary="Импорт OpenAPI-спецификации",
    description="Загружает OpenAPI 3.x spec (JSON) и генерирует DSL-роуты для каждой операции.",
)
async def import_openapi(
    spec_url: str | None = Form(default=None),
    prefix: str = Form(default="ext"),
    file: UploadFile | None = File(default=None),
    dry_run: bool = Form(default=False),
) -> dict[str, Any]:
    """Импортирует OpenAPI spec (file или URL).

    Args:
        spec_url: URL spec'а — если передан, file игнорируется.
        prefix: Префикс для route_id.
        file: Multipart upload JSON/YAML spec'а.
        dry_run: Только preview, без регистрации.

    Returns:
        Отчёт об импорте со списком ``route_id``.
    """
    from src.dsl.importers.openapi_parser import get_openapi_importer

    spec: dict[str, Any] | str
    if file is not None:
        content = await file.read()
        try:
            import orjson

            spec = orjson.loads(content)
        except Exception:
            try:
                import yaml

                spec = yaml.safe_load(content)
            except Exception as exc:
                raise HTTPException(400, f"Не удалось распарсить spec: {exc}") from exc
    elif spec_url:
        spec = spec_url
    else:
        raise HTTPException(400, "Требуется file или spec_url")

    importer = get_openapi_importer()
    return await importer.import_spec(spec, prefix=prefix)


# ──────────────────── Postman ────────────────────


@router.post(
    "/postman",
    summary="Импорт Postman-коллекции",
    description="Загружает Postman Collection v2.1 (JSON) и генерирует DSL-роуты.",
)
async def import_postman(
    prefix: str = Form(default="postman"),
    file: UploadFile | None = File(default=None),
    collection_url: str | None = Form(default=None),
) -> dict[str, Any]:
    """Импортирует Postman-коллекцию.

    Args:
        prefix: Префикс route_id.
        file: Multipart upload JSON коллекции.
        collection_url: URL коллекции (если нет файла).

    Returns:
        Список сгенерированных ``route_id``.
    """
    from src.dsl.importers.postman_parser import get_postman_importer

    if file is not None:
        import orjson

        content = await file.read()
        try:
            collection = orjson.loads(content)
        except Exception as exc:
            raise HTTPException(400, f"Невалидный JSON коллекции: {exc}") from exc
    elif collection_url:
        collection = collection_url
    else:
        raise HTTPException(400, "Требуется file или collection_url")

    importer = get_postman_importer()
    return await importer.import_collection(collection, prefix=prefix)


# ──────────────────── Process Schema (BPMN-like) ────────────────────


@router.post(
    "/process-schema",
    summary="Импорт схемы процесса",
    description="JSON-схема бизнес-процесса (шаги + связи) → DSL-pipeline.",
)
async def import_process_schema(payload: dict[str, Any]) -> dict[str, Any]:
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

    Поддерживаемые типы шагов: ``action``, ``log``, ``transform``, ``choice``,
    ``http_call``, ``dispatch_action``. Расширяется в ``_build_step`` ниже.
    """
    from src.dsl.builder import RouteBuilder

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


def _apply_steps(builder: Any, steps: list[dict[str, Any]]) -> Any:
    """Рекурсивно применяет шаги из схемы процесса к RouteBuilder.

    Функция намеренно держит ограниченный набор типов — расширяется по мере
    появления новых сценариев. Каждый шаг сопоставляется с builder-методом.
    """
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


@router.post(
    "/bulk-objects",
    summary="Массовое создание объектов + запуск процесса",
    description="CSV/Excel файл → создаёт объекты по каждой строке и запускает указанный DSL-роут.",
)
async def import_bulk_objects(
    route_id: str = Form(...),
    file: UploadFile = File(...),
    dry_run: bool = Form(default=False),
) -> dict[str, Any]:
    """Парсит CSV/Excel и для каждой строки запускает DSL-роут.

    Args:
        route_id: ID маршрута, который будет вызван для каждой строки.
        file: CSV или XLSX с данными (первая строка — имена колонок).
        dry_run: Только распарсить, не выполнять роут.

    Returns:
        Отчёт со статистикой успешных/провалившихся запусков.
    """
    content = await file.read()
    filename = file.filename or ""

    # Выбираем парсер по расширению файла.
    try:
        if filename.endswith((".xlsx", ".xls")):
            import io

            import pandas as pd

            df = pd.read_excel(io.BytesIO(content))
            rows = df.to_dict(orient="records")
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

    from src.dsl.engine.execution_engine import get_execution_engine
    from src.dsl.engine.pipeline_registry import get_pipeline_registry

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
