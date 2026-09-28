"""Compatibility shim для legacy migration tests (W2 P0-3).

Canonical: ``src.backend.dsl.engine.processors.idp_pipeline_processor.pipeline_mixin``.

Раньше здесь был полный дубликат ``PipelineMixin``, импортировавший
legacy-``helpers``/``state``/``_protocol``. После удаления этих модулей
(W5 dead-code wave) реализация осталась только одна — каноническая,
поэтому shim реэкспортирует её и держит legacy-путь импорта работоспособным.
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.idp_pipeline_processor.pipeline_mixin import (
    PipelineMixin as PipelineMixin,
)

__all__ = ("PipelineMixin",)
