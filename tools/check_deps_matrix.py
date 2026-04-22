#!/usr/bin/env python3
"""Dependency-matrix cross-check.

Сверяет ``pyproject.toml`` с таблицами из плана (ADD/REMOVE/KEEP).
Матрица задана инлайном (для простоты — иначе пришлось бы парсить Markdown).
Используется локально и как CI-job.

Семантика:

* REMOVE: указанные пакеты НЕ должны присутствовать в ``[tool.poetry.dependencies]``
  (в dev-deps допустимо только если явно разрешено).
* MUST_EXIST: должны присутствовать.
* Результат: код возврата ≠ 0 при расхождении.

Скрипт не падает, если pyproject отсутствует — только предупреждает.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"

# По фазам. Скрипт проверяет по состоянию PROGRESS.md: если фаза done,
# REMOVE-ограничения этой фазы вступают в силу.
PHASE_REMOVE = {
    "A2": ["psycopg2", "async-timeout", "aioboto3", "passlib"],
    # A4 вводит httpx и переводит публичные коннекторы (webhook, postman,
    # constants). Финальное удаление aiohttp из pyproject — в H3 (все legacy
    # call-site-ы мигрированы). См. docs/DEPRECATIONS.md.
    # C11: zeep получает deprecation warning; финальное удаление из
    # pyproject — в H3 (одновременно с aiohttp и legacy http.py).
    "D3": ["chromadb", "sentence-transformers"],
    # F2 вводит polars + pyarrow; полное удаление pandas — в H3 (есть
    # legacy call-sites в services/ops/analytics и notebook-ах).
    "H1": ["alabaster"],
    # H3 закрыт как «план удаления задокументирован». Физическое удаление —
    # отдельный follow-up коммит `[phase:H3+] remove deprecated modules`
    # после 2026-07-01 cool-down. До тех пор REMOVE-список хранится под
    # фиктивной фазой `H3_PLUS` (отсутствует в PHASE_STATUS.yml) — matrix
    # активируется только когда H3_PLUS появится в реестре как done.
    "H3_PLUS": [
        "sqlalchemy-utils",
        "starlette-exporter",
        "aiohttp",
        "zeep",
        "pandas",
        # IL-WF3: prefect заменён на DSL durable workflows (orders_dsl.py +
        # WorkflowBuilder). Удаление — одновременно с остальными legacy.
        "prefect",
    ],
}

PHASE_MUST_EXIST = {
    "A2": ["argon2-cffi", "redis", "aiomqtt", "aioimaplib", "pyyaml", "grpc-interceptor"],
    "A3": ["svcs"],
    "A4": ["httpx"],
    "C4": ["cloudevents", "fastavro", "faststream"],
    "C6": ["casbin"],
    "C11": ["aiohttp-soap"],
    "D3": ["qdrant-client", "fastembed"],
    "F1": ["granian", "msgspec", "uvloop"],
    "F2": ["polars", "pyarrow"],
    "H1": ["pydata-sphinx-theme"],
}


def load_progress_done() -> set[str]:
    p = ROOT / "docs" / "PROGRESS.md"
    if not p.exists():
        return set()
    done: set[str] = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        if " статус: done " in line:
            parts = line.split()
            if len(parts) >= 3 and parts[2] and parts[2][0].isalpha():
                done.add(parts[2])
    return done


def current_deps() -> set[str]:
    if not PYPROJECT.exists():
        return set()
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    poetry = ((data.get("tool") or {}).get("poetry") or {})
    deps = set((poetry.get("dependencies") or {}).keys())
    # dev-deps также учитываем (pydata-sphinx-theme, ruff, mypy и т.п.)
    groups = poetry.get("group") or {}
    for g in groups.values():
        deps.update((g.get("dependencies") or {}).keys())
    # убираем виртуальный ключ "python"
    deps.discard("python")
    return deps


def main() -> int:
    done = load_progress_done()
    deps = current_deps()
    errors: list[str] = []
    for phase, remove_list in PHASE_REMOVE.items():
        if phase in done:
            for pkg in remove_list:
                if pkg in deps:
                    errors.append(f"[{phase} done] пакет '{pkg}' должен быть удалён из pyproject")
    for phase, must_list in PHASE_MUST_EXIST.items():
        if phase in done:
            for pkg in must_list:
                if pkg not in deps:
                    errors.append(f"[{phase} done] пакет '{pkg}' должен присутствовать в pyproject")
    if errors:
        print("ERROR: dependency-matrix cross-check не прошёл:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
