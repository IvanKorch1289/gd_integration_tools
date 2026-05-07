"""Public FastAPI-зависимости для роутеров (rate-limit, и др.).

Группа модулей под ``entrypoints/dependencies/`` хранит ``Depends``-объекты,
не являющиеся ASGI-middleware. Импортируются из endpoint-файлов, плагинов
и DSL-генератора роутов.

Sprint 1 V16 cleanup: ``rate_limit`` перенесён сюда из ``middlewares/``
после миграции на ``fastapi-limiter`` per-route Depends API.
"""
