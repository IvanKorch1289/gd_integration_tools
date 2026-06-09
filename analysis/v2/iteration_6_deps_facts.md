# V2 Итерация 6: Зависимости — фактические находки

## Core dependencies
- pyproject.toml dependencies: **115 строк** (не 92 как в V1)
- `uv.lock`: 2026-06-07, `pyproject.toml`: 2026-06-08 — **устарел на 1 день**

## Дубли в манифесте
- `pendulum`: строка 48 (pinned) и 107 (без пина)
- `presidio-analyzer`: строки 106, 130, 157
- `aiosqlite`: в dev-light extra и dev группе

## Закомментированные extras
- `embeddings-fastembed-legacy`: строки 218-228 — конфликты с huggingface-hub
- `ai-voice`: строки 256-268 — конфликты с markitdown→numpy

## CVE и проблемные deps
- `diskcache>=5.6.3,<6.0.0`: строка 61 — комментарий «NO FIX for CVE-2025-69872; project mitigates via JSONDisk»
- `aiocache>=0.12.0,<1.0.0`: строка 94 — «async cache lib (v22 lib-table); S60+ migration plan в ADR-0086»

## Deps без прямых импортов
- `grpc-interceptor>=0.15.4`: строка 72
- `cloudevents>=1.10.0`: строка 86
- `uvloop`: возможно используется Granian напрямую
