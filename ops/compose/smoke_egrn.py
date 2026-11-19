"""Функциональный smoke-тест: запрос workflow'а на получение выписки ЕГРН (СКБ-Техно).

Запуск (из корня репозитория)::

    docker compose -f ops/compose/docker-compose.yml \
        -f ops/compose/docker-compose.prod.yml \
        exec -T app python /app/ops/compose/smoke_egrn.py

Скрипт выполняется ВНУТРИ контейнера приложения: ключ API берётся из
настроек самого приложения (секрет не покидает контейнер).

Проверяется сквозной путь workflow-запроса: routing → авторизация по
X-API-Key → валидация тела → диспетчеризация action'а → вызов внешнего
сервиса СКБ-Техно → структурированный ответ с correlation_id.

Замечание: внешний сервис в стенде — .NET-мок; он возвращает бизнес-сообщения
(например «Нельзя создать запрос с указанным типом запроса»), если
идентификатор вида запроса не из справочника ``orderkinds.skb_uuid``.
"""
import asyncio
import json
import uuid

import httpx

from src.backend.core.config.settings import settings

HOST_HEADER = "api.prod.local"
BASE = "http://localhost:8000"


def key_headers() -> dict[str, str]:
    raw = settings.secure.api_key
    key = raw.get_secret_value() if raw is not None else ""
    return {"X-API-Key": key, "Host": HOST_HEADER, "Content-Type": "application/json"}


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=30.0) as client:
        # 1) liveness
        r = await client.get("/health", headers={"Host": HOST_HEADER})
        print(f"[1] GET /health → {r.status_code} {r.text.strip()[:80]}")

        # 2) поиск объекта недвижимости по адресу (первый шаг выписки ЕГРН)
        r = await client.post(
            "/api/v1/skb/get-objects-by-address",
            params={"query": "Москва, ул. Тверская, д. 1", "comment": "functional-test"},
            headers=key_headers(),
        )
        print(f"[2] POST /api/v1/skb/get-objects-by-address → {r.status_code}")
        print("    " + r.text.strip()[:300])

        # 3) создание запроса на выписку ЕГРН (основной workflow-запрос)
        order = {
            "Id": str(uuid.uuid4()),
            "OrderId": str(uuid.uuid4()),
            "Number": "77:01:0100001:1234",
            "Priority": 80,
            "RequestType": "00000000-0000-0000-0000-000000000002",  # skb_uuid вида «cadastral_passport» (выписка ЕГРН)
        }
        r = await client.post(
            "/api/v1/skb/create-request", json=order, headers=key_headers()
        )
        print(f"[3] POST /api/v1/skb/create-request → {r.status_code}")
        print("    " + r.text.strip()[:400])
        order_uuid = None
        try:
            payload = r.json()
            if isinstance(payload, dict):
                order_uuid = payload.get("order_uuid") or payload.get("OrderId")
        except Exception:
            pass

        # 4) получение результата по заказу (второй шаг workflow'а)
        if order_uuid:
            r = await client.get(
                "/api/v1/skb/get-result",
                params={"order_uuid": str(order_uuid), "response_type": "json"},
                headers=key_headers(),
            )
            print(f"[4] GET /api/v1/skb/get-result → {r.status_code}")
            print("    " + r.text.strip()[:300])
        else:
            print("[4] GET /api/v1/skb/get-result → пропущен (нет order_uuid)")

        # 5) справочник видов запросов СКБ (проверка read-пути)
        r = await client.get("/api/v1/skb/get-kinds", headers=key_headers())
        print(f"[5] GET /api/v1/skb/get-kinds → {r.status_code}")
        print("    " + r.text.strip()[:200])


asyncio.run(main())
