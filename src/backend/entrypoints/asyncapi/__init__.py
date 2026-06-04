"""AsyncAPI 3 export — публикация спецификации FastStream-источников.

Stream E.6 — экспорт AsyncAPI 3.0.0 спецификации через
:class:`faststream.specification.AsyncAPI` поверх routers, зарегистрированных
в :class:`StreamClient` (Redis / Rabbit / Kafka).

Публичный API:

* :func:`build_asyncapi_spec` — возвращает :class:`Specification` (имеет
  :meth:`to_yaml` / :meth:`to_json` / :meth:`to_jsonable`).
* :func:`build_asyncapi_yaml` — YAML-строка.
* :func:`build_asyncapi_json` — JSON-строка.

Эндпоинт `GET /api/v1/asyncapi.yaml` живёт в
``entrypoints/api/v1/endpoints/asyncapi.py``.
"""

from __future__ import annotations

from src.backend.entrypoints.asyncapi.exporter import (
    build_asyncapi_json,
    build_asyncapi_spec,
    build_asyncapi_yaml,
)

__all__ = ("build_asyncapi_json", "build_asyncapi_spec", "build_asyncapi_yaml")
