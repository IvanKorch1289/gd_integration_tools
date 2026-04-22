# ADR-006: Granian как prod ASGI-сервер

* Статус: accepted
* Дата: 2026-04-21
* Фазы: F1

## Контекст

Uvicorn (standard extras) — удобен в dev, но Granian (Rust-native)
показывает на banking workload примерно +15…25 % RPS на том же железе
и использует меньше памяти за счёт lock-free hyper-реактора.

## Решение

1. Production: `granian` (+ HTTP/2 native, HTTP/3 QUIC доступен).
2. Dev: uvicorn остаётся как дефолт (быстрый старт, hot-reload),
   переносится в dev-extras в H3.
3. Переключение через env-переменную или runtime-flag; настройки
   workers/threads/blocking auto-подстраиваются под CPU и cgroup limits.

## Альтернативы

- **Hypercorn**: медленнее Granian; нет mature HTTP/3.
- **Daphne**: main-loop на Twisted, сложнее интеграция с middleware.

## Последствия

- Dockerfile (prod) стартует `granian`.
- Совместимость с FastAPI — native ASGI, никаких wrapper-ов.
- uvicorn остаётся для `make dev`/local-тестов.
