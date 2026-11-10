# ADR-0438 — Storage-операции по ключу (list/get/download)

* Статус: Accepted (2026-11-10, волна 29)
* Cycle: 188 (волна 29)
* Связан с: ADR-0425 (контракт путей портала)
* Затрагивает: `src/backend/entrypoints/api/v1/endpoints/files.py`, `src/frontend/streamlit_app/pages/57_Файлы_S3.py`

## Контекст

Панель «Файлы S3» работала с ключами объектов, а сервер отдавал только
операции по `file_uuid` (`/download_file/{uuid}`, `/get_file_base64/{uuid}`).

## Решение

Тонкие эндпоинты поверх существующей capability S3-сервиса (без новой
бизнес-логики): `GET /api/v1/storage/list` (`list_files`),
`GET /api/v1/storage/get` (`get_file_base64`),
`GET /api/v1/storage/download` (`generate_download_url`).

## Последствия

* Панель «Файлы S3» работает с ключами; uuid-операции сохранены.
