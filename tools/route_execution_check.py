#!/usr/bin/env python
"""Функциональная проверка исполнения V11-роутов из ``routes/<name>/``.

Регистрация роута — это ещё не исполнение. ``RouteLoader`` только наполняет
``route_registry``; реальный код роута выполняется через
:meth:`DslService.dispatch`. Этот скрипт проходит полный путь:

    RouteLoader.discover_and_load() → route_registry → DslService.dispatch

и печатает, что именно вернул каждый шаг пайплайна.

Запуск::

    SEC_API_KEY=test-functional-key-1234567890 MONGO_ENABLED=false \
        .venv/bin/python tools/route_execution_check.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

#: route_id (как он зарегистрирован в ``route_registry``) → (тело, ожидание).
#:
#: Роутов с внешними зависимостями (Perplexity API, Jupyter Hub) здесь нет
#: намеренно: они выключены собственными флагами и требуют инфраструктуры,
#: которой в функциональной проверке нет.
#:
#: Обратите внимание: ``composition_demo`` регистрируется как
#: ``composition.demo`` — route_id берётся из YAML, а имя каталога может
#: отличаться. Реестр — единственный источник истины, поэтому кейсы адресуются
#: именно по нему.
#:
#: Ожидания намеренно различаются. YAML-шаг ``feature_flag:`` НЕ создаёт
#: процессор — он выставляет ``Pipeline.feature_flag``, который проверяется
#: как route-level гейт в ``execution_engine._check_feature_flag()`` и
#: останавливает pipeline целиком (см. FeatureMixin.feature_flag). Поэтому
#: ``external_health_proxy_enabled=False`` даёт «skipped»: ``out_message``
#: остаётся ``None``. Это ожидаемое поведение, а не сбой.
EXECUTION_CASES: dict[str, tuple[Any, str]] = {
    # demo_routes_enabled=True → пайплайн исполняется, JMESPath-transform
    # обязан переписать body (это и есть главная проверка).
    "echo_demo": ({"message": "привет"}, "transform_applied"),
    # Флаг включён → пайплайн исполняется и возвращает body без transform.
    "composition.demo": ({"message": "привет"}, "passthrough"),
    # external_health_proxy_enabled=False → route-level гейт останавливает
    # пайплайн до proxy-шага, out_message=None.
    "health_proxy_demo": ({"message": "привет"}, "skipped_by_flag"),
}


async def _main() -> int:
    """Поднять приложение штатным lifespan, выполнить кейсы, вернуть код возврата."""
    # Импорт после настройки пути — пакет живёт в src/.
    sys.path.insert(0, str(REPO_ROOT))

    from src.backend.dsl.registry import route_registry  # noqa: PLC0415
    from src.backend.dsl.service.facade import DslService  # noqa: PLC0415
    from src.backend.main import app  # noqa: PLC0415

    # Штатный lifespan — он же поднимает RouteLoader в реальном bootstrap.
    # Собирать RouteLoader вручную нельзя: у конструктора 6 keyword-only
    # аргументов (routes_dir, capability_gate, vocabulary, core_version,
    # installed_plugins, pipeline_registrar), и только bootstrap знает,
    # какими значениями их наполнить.
    async with app.router.lifespan_context(app):
        print(f"Загружено роутов: {len(route_registry.list_routes())}")
        for route_id in sorted(route_registry.list_routes()):
            print(f"  + {route_id}")

        service = DslService()
        failures: list[str] = []

        for route_id, (body, expect) in EXECUTION_CASES.items():
            print(f"\n=== dispatch {route_id!r} (ожидание: {expect}) ===")
            if route_registry.get(route_id) is None:
                print("  ПРОПУЩЕН: роут не зарегистрирован (status != enabled)")
                failures.append(f"{route_id}: не зарегистрирован")
                continue
            try:
                exchange = await service.dispatch(route_id, body=body)
            except Exception as exc:  # noqa: BLE001 — диагностический скрипт
                print(f"  ОШИБКА {type(exc).__name__}: {exc}")
                failures.append(f"{route_id}: {type(exc).__name__}: {exc}")
                continue

            out = exchange.out_message
            body_out = None if out is None else out.body
            print(
                f"  out.body = {json.dumps(body_out, ensure_ascii=False, default=str)}"
            )

            if expect == "skipped_by_flag":
                # Route-level гейт останавливает pipeline до шагов: out_message
                # не создаётся. Убеждаемся, что это именно «пропуск по флагу»,
                # а не тихий сбой шага.
                if out is None:
                    print("  OK: pipeline остановлен route-level feature_flag")
                else:
                    failures.append(
                        f"{route_id}: ожидался skip по feature_flag, получен ответ"
                    )
                    print("  НЕУСПЕХ: флаг выключен, но ответ сформирован")
                continue

            if out is None:
                failures.append(f"{route_id}: out_message=None, а ожидался результат")
                print("  НЕУСПЕХ: out_message не создан")
                continue

            if exchange.stopped:
                failures.append(f"{route_id}: exchange помечен как остановленный")
                print("  НЕУСПЕХ: exchange.stopped=True")
                continue

            # echo_demo объявляет transform с JMESPath — результат обязан быть
            # переписанным body, а не исходным. Это проверяет, что шаг исполнился,
            # а не был молча пропущен.
            if expect == "transform_applied":
                if not isinstance(body_out, dict) or "echoed" not in body_out:
                    failures.append(f"{route_id}: transform не применился")
                    print("  НЕУСПЕХ: ключ 'echoed' отсутствует — шаг не выполнен")
                    continue
                print(f"  OK: transform применился (echoed={body_out['echoed']!r})")
            elif expect == "passthrough":
                print("  OK: пайплайн исполнился и вернул body")

    print("\n" + "=" * 60)
    if failures:
        print(f"ПРОВАЛЕНО кейсов: {len(failures)}")
        for item in failures:
            print(f"  - {item}")
        return 1
    print(f"ВСЕ КЕЙСЫ ПРОШЛИ: {len(EXECUTION_CASES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
