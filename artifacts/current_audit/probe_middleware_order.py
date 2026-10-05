"""Инструментация фактического порядка ASGI middleware (главная P0-проверка).

Цель: доказать ФАКТИЧЕСКИЙ порядок request/response, а не порядок в registry.

Метод:
  1. Перехватить ``Starlette.add_middleware`` ДО ``create_app()`` — это
     registration order (порядок вызовов в коде).
  2. Прочитать ``app.user_middleware`` после ``create_app()`` — фактический
     стек. В Starlette индекс 0 = **внешний** middleware (LIFO-семантика
     ``add_middleware``): приложение оборачивает новым middleware старый.
  3. Обернуть ``__call__`` каждого middleware-класса из ``user_middleware``:
     событие ``enter:<name>`` на входе, ``exit:<name>`` на выходе. Так
     фиксируется реальный проход запроса, а не предположение.
  4. Выполнить настоящий запрос через ASGI-транспорт.
  5. Сопоставить фактический порядок с ожидаемой security-цепочкой.

Запуск (из корня репозитория, Python 3.14):

    MONGO_ENABLED=false .venv/bin/python \\
        artifacts/current_audit/probe_middleware_order.py

Записывает ``middleware_actual_order.json`` рядом с собой и печатает
сводку. Ничего не мутирует в репозитории.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OUT_PATH = Path(__file__).resolve().parent / "middleware_actual_order.json"

#: Ожидаемая security-цепочка. Внешний middleware идёт ПЕРВЫМ по счёту
#: ``app.user_middleware``, поэтому ожидаемый порядок читается сверху вниз:
#: authentication раньше tenant, tenant раньше resource-isolation и т.д.
EXPECTED_SECURITY_CHAIN: list[str] = [
    "authentication",
    "tenant resolution",
    "tenant resource isolation",
    "authorization",
    "idempotency",
    "request body cache",
    "response cache",
    "logging",
]

#: ЯВНОЕ сопоставление стадии → имена middleware-классов. Сопоставление по
#: точным именам, а не по regex: иначе ``AIToolWhitelistMiddleware`` (idx=14)
#: ошибочно засчитывается как стадия authorization, и находка «стадии
#: authorization в стеке нет» была бы потеряна. Пустой список означает, что
#: выделенной стадии в стеке нет — это и есть измеряемый факт.
STAGE_CLASSES: dict[str, tuple[str, ...]] = {
    "authentication": (
        "AuthRequiredMiddleware",
        "AuthMethodHeaderMiddleware",
        "APIKeyMiddleware",
    ),
    "tenant resolution": ("TenantMiddleware",),
    "tenant resource isolation": ("TenantResourceIsolationMiddleware",),
    # Стадия authorization — отдельный слой принятия решений о доступе
    # (Casbin / RBAC / permission). В текущем стеке такого слоя нет.
    "authorization": (),
    "idempotency": ("IdempotencyHeaderMiddleware",),
    "request body cache": ("RequestBodyCacheMiddleware",),
    "response cache": ("ResponseCacheMiddleware",),
    "logging": ("AuditLogMiddleware", "InnerRequestLoggingMiddleware"),
}


def _install_enter_exit_instrumentation(events: list[str]) -> dict[str, int]:
    """Обернуть ``__call__`` у всех middleware-классов стека.

    Args:
        events: Список, в который пишутся ``enter:<name>`` / ``exit:<name>``.

    Returns:
        Словарь ``{имя класса: количество обёрнутых экземпляров}``.

    """
    seen: dict[str, int] = {}
    for entry in list(_APP.user_middleware):  # type: ignore[attr-defined]
        cls = entry.cls
        if cls in seen:
            continue
        original = cls.__call__
        label = cls.__name__

        def make(original_call: Any, name: str) -> Any:
            async def instrumented(
                self_: Any, scope: Any, receive: Any, send: Any
            ) -> Any:
                if scope.get("type") == "http":
                    events.append(f"enter:{name}")
                try:
                    return await original_call(self_, scope, receive, send)
                finally:
                    if scope.get("type") == "http":
                        events.append(f"exit:{name}")

            return instrumented

        cls.__call__ = make(original, label)  # type: ignore[method-assign]
        seen[label] = 1
    return seen


def main() -> int:
    """Собрать доказательство порядка middleware и записать JSON.

    Returns:
        Код возврата: ``0`` — замер выполнен (нарушения порядка не влияют на
        код возврата, они попадают в ``chain_violations``).

    """
    from starlette.applications import Starlette

    registration_order: list[str] = []
    original_add = Starlette.add_middleware

    def spy_add(self: Any, middleware_class: Any, *args: Any, **kwargs: Any) -> Any:
        """Записать класс до передачи в штатный ``add_middleware``."""
        registration_order.append(middleware_class.__name__)
        return original_add(self, middleware_class, *args, **kwargs)

    Starlette.add_middleware = spy_add  # type: ignore[method-assign]

    global _APP  # noqa: PLW0603 — приложение нужно хелперу-обёртке
    from src.backend.plugins.composition.app_factory import create_app

    _APP = create_app()
    Starlette.add_middleware = original_add  # type: ignore[method-assign]

    stack: list[str] = [entry.cls.__name__ for entry in _APP.user_middleware]
    events: list[str] = []
    _install_enter_exit_instrumentation(events)

    # Настоящий запрос через ASGI-транспорт httpx. В установленной версии
    # httpx ``ASGITransport`` — только асинхронный, поэтому клиент асинхронный.
    import asyncio

    import httpx

    async def _probe_request() -> Any:
        """Выполнить один GET /health через ASGI-транспорт.

        Returns:
            Объект ответа httpx.

        """
        transport = httpx.ASGITransport(app=_APP)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://probe"
        ) as client:
            return await client.get("/health", headers={"Host": "localhost"})

    response = asyncio.run(_probe_request())

    request_order = [
        name.split(":", 1)[1] for name in events if name.startswith("enter:")
    ]
    response_order = [
        name.split(":", 1)[1] for name in events if name.startswith("exit:")
    ]

    # Позиции стадий: индексы в user_middleware (0 = внешний).
    chain_positions: dict[str, dict[str, Any]] = {}
    for stage in EXPECTED_SECURITY_CHAIN:
        wanted = STAGE_CLASSES[stage]
        hits = [i for i, cls in enumerate(stack) if cls in wanted]
        chain_positions[stage] = {
            "indexes": hits,
            "classes": [stack[i] for i in hits],
            "matched": bool(hits),
        }

    matched_stages = sum(1 for v in chain_positions.values() if v["matched"])
    total_stages = len(EXPECTED_SECURITY_CHAIN)

    # Нарушения порядка: каждая стадия должна идти раньше следующей.
    ordered_present = [
        s for s in EXPECTED_SECURITY_CHAIN if chain_positions[s]["matched"]
    ]
    chain_violations: list[str] = []
    for earlier, later in zip(ordered_present, ordered_present[1:]):
        i_first = min(chain_positions[earlier]["indexes"])
        i_second = min(chain_positions[later]["indexes"])
        if i_first > i_second:
            chain_violations.append(
                f"{earlier}(idx={i_first}) не раньше {later}(idx={i_second}) — "
                "порядок инвертирован"
            )
    missing = [s for s in EXPECTED_SECURITY_CHAIN if not chain_positions[s]["matched"]]
    for stage in missing:
        chain_violations.append(f"стадия '{stage}' ОТСУТСТВУЕТ в стеке")

    payload = {
        "probe": {
            "method": "патч Starlette.add_middleware + обёртка __call__ каждого "
            "middleware-класса из app.user_middleware (enter/exit) + реальный "
            "HTTP-запрос через httpx.ASGITransport",
            "index_semantics": "app.user_middleware[0] = внешний middleware "
            "(LIFO-семантика add_middleware)",
            "request": "GET /health",
            "status_code": response.status_code,
        },
        "registration_order": registration_order,
        "app_user_middleware": stack,
        "actual_request_order": request_order,
        "actual_response_order": response_order,
        "raw_events": events,
        "expected_security_chain": EXPECTED_SECURITY_CHAIN,
        "chain_positions": chain_positions,
        "chain_violations": chain_violations,
        "matched_stages": matched_stages,
        "total_stages": total_stages,
    }

    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"registration order: {len(registration_order)}")
    print(f"user_middleware:    {len(stack)}")
    print(f"request order:      {len(request_order)}")
    print(f"response order:     {len(response_order)}")
    print(f"stages matched:     {matched_stages}/{total_stages}")
    print(f"chain violations:   {len(chain_violations)}")
    for line in chain_violations:
        print(f"  ! {line}")
    print(f"written -> {OUT_PATH}")
    return 0


_APP: Any = None

if __name__ == "__main__":
    raise SystemExit(main())
