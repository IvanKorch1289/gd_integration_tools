# ADR-003: CORS policy с явным whitelist и запретом `*` в prod

* Статус: accepted
* Дата: 2026-04-21
* Автор: claude
* Решение связано с фазой: A2 (Security hardening)

## Контекст

В исходной конфигурации FastAPI в `setup_middlewares.py` отсутствовал
`CORSMiddleware`. Это одновременно:

1. Блокировало легитимные SPA-клиенты (`Access-Control-Allow-Origin` не
   выставлялся, браузер отбрасывал ответ).
2. Делало неочевидной политику: ручные заголовки встречались в отдельных
   эндпоинтах, единого источника правды не было.
3. Создавало соблазн быстрого `allow_origins=["*"]` в обход ревью.

Banking-профиль системы исключает `*` в prod: с `allow_credentials=True`
это напрямую противоречит CORS-спеке и RBAC-моделям.

## Решение

1. В `SecureSettings` введены поля:
   - `cors_origins: list[str]` — явный whitelist origin-ов.
   - `cors_allow_credentials: bool` (default `True`).
   - `cors_allow_methods: list[str]` (default безопасный набор).
   - `cors_allow_headers: list[str]` (default — `Authorization`,
     `Content-Type`, `X-Request-ID`, `X-API-Key`).
2. `field_validator("cors_origins")` **запрещает** `"*"`, если переменная
   окружения `APP_ENV`/`ENVIRONMENT` указывает на `prod`/`production`.
3. `CORSMiddleware` добавлен в `setup_middlewares.py` первым пользовательским
   middleware после `ExceptionHandlerMiddleware` — чтобы preflight-запросы
   не проходили излишние слои.
4. `expose_headers=["X-Request-ID"]` — клиент видит корреляцию без
   изменений API.
5. `max_age=600` — десятиминутный кеш preflight.

## Альтернативы

- `*` с `allow_credentials=False` — не подходит, cookie-auth нужны.
- Внешний reverse-proxy (nginx/traefik) для CORS — отвергнуто: политика
  должна быть версионирована вместе с кодом и проверяться в CI.
- Регекс-whitelist — сохранено на будущее (`allow_origin_regex`), но сейчас
  не требуется.

## Последствия

- Deploy в новую среду обязан явно указывать `SEC_CORS_ORIGINS`.
- `pydantic` валидация падает на `*` в prod — осечку невозможно скрыть.
- Тесты CORS вручную: `curl -i -H 'Origin: https://evil.example' .../readiness`
  (см. `docs/phases/PHASE_A2.md`).
