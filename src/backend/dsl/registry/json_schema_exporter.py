"""Экспортёр JSON-Schema для DSL-процессоров (ADR-0058).

Пишет JSON-Schema draft-07 файлы в указанную директорию:
* ``{name}.schema.json`` — схема одного процессора (``namespace/name``);
* ``index.json`` — агрегированный индекс (aggregate snapshot для LSP).

Используется из:
* ``tools/dsl_export_schemas.py`` — CLI-точка входа;
* ``make schemas`` — CI gate;
* предкоммитный hook (Sprint 5, ADR-0058 §CI gates).

Пример::

    from pathlib import Path
    from src.backend.dsl.registry.json_schema_exporter import export_processors_schema

    n = export_processors_schema(Path("docs/reference/schemas/processors"))
    print(f"Экспортировано {n} процессоров")

"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.backend.dsl.registry.processor import ProcessorSpec, get_processor_registry

__all__ = ("export_processors_schema",)

logger = logging.getLogger(__name__)


def _schema_filename(spec: ProcessorSpec) -> str:
    """Формирует имя файла схемы для процессора.

    Ядерные процессоры (namespace=``core``) сохраняются как ``{name}.schema.json``.
    Плагинные — как ``{namespace}__{name}.schema.json`` чтобы избежать коллизий.

    Args:
        spec: Спецификация процессора.

    Returns:
        Строка имени файла без пути.
    """

    if spec.namespace == "core":
        return f"{spec.name}.schema.json"
    return f"{spec.namespace}__{spec.name}.schema.json"


def export_processors_schema(output_dir: Path) -> int:
    """Экспортирует JSON-Schema всех зарегистрированных процессоров в директорию.

    Алгоритм:
    1. Читает глобальный :func:`get_processor_registry` singleton.
    2. Для каждого ``ProcessorSpec`` вызывает
       :meth:`ProcessorRegistry.export_schemas` (Pydantic reflection или
       явный ``spec_schema`` или минимальный open-schema).
    3. Пишет ``{filename}.schema.json`` + агрегированный ``index.json``.

    Args:
        output_dir: Директория для записи файлов (создаётся при отсутствии).

    Returns:
        Количество экспортированных процессоров (не считая ``index.json``).

    Raises:
        OSError: При проблемах с созданием директории или записью файлов.
    """

    output_dir.mkdir(parents=True, exist_ok=True)
    registry = get_processor_registry()
    schemas: dict[str, dict[str, Any]] = registry.export_schemas()

    count = 0
    index: dict[str, Any] = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": "https://gd-integration-tools/schemas/processors/index",
        "title": "GD Integration Tools — DSL Processor Index",
        "description": (
            "Агрегированный индекс всех зарегистрированных DSL-процессоров. "
            "Генерируется автоматически через export_processors_schema() (ADR-0058)."
        ),
        "processors": [],
    }

    specs_by_fqn: dict[str, ProcessorSpec] = {
        spec.fqn: spec for spec in registry.list_all()
    }

    for fqn, schema in schemas.items():
        spec = specs_by_fqn[fqn]
        filename = _schema_filename(spec)
        schema_path = output_dir / filename

        schema_path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.debug("Записан %s → %s", fqn, schema_path)

        index["processors"].append(
            {
                "fqn": fqn,
                "name": spec.name,
                "namespace": spec.namespace,
                "version": spec.version,
                "tags": list(spec.tags),
                "file": filename,
                "$ref": f"./{filename}",
            }
        )
        count += 1

    # Запись агрегированного индекса
    index_path = output_dir / "index.json"
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("JSON-Schema export завершён: %d процессоров → %s", count, output_dir)

    return count
