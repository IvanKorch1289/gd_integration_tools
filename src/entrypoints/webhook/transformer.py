"""Webhook Relay + Transformations — JMESPath трансформации + retry queue + DLQ.

Outbound webhook:

1. Применяет JMESPath трансформацию к payload перед отправкой.
2. Фильтрует по условию (отправлять или нет).
3. Retry с exponential backoff при ошибках.
4. DLQ для сообщений, превысивших max retries. Хранится **в Redis** —
   переживает рестарт приложения и доступна всем инстансам. Fallback на
   in-memory (если Redis недоступен) — сохраняет хотя бы текущие записи
   до восстановления.

Actions: webhook.relay, webhook.transform, webhook.dlq_list, webhook.dlq_retry.

Ключи Redis:

* ``webhook:dlq`` — LPUSH/LRANGE/LREM JSON-сериализованных :class:`DLQEntry`.

Структура DLQEntry сериализуется через orjson; выбрана сквозная идентификация
по UUID для атомарного LREM по ID.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

import orjson

__all__ = ("WebhookRelay", "RelayRule", "DLQEntry", "get_webhook_relay")

logger = logging.getLogger(__name__)

# Redis-ключ DLQ. Список: LPUSH на добавление, LRANGE на чтение, LREM на удаление.
_DLQ_KEY = "webhook:dlq"
# Максимальная длина DLQ в Redis (LTRIM) — защита от неограниченного роста.
_DLQ_MAX_LEN = 10_000


@dataclass(slots=True)
class RelayRule:
    """Правило трансформации + маршрутизации webhook."""

    id: str = field(default_factory=lambda: uuid4().hex[:12])
    event_type: str = "*"
    target_url: str = ""
    jmespath_expression: str | None = None
    condition: str | None = None
    secret: str | None = None
    max_retries: int = 3
    enabled: bool = True


@dataclass(slots=True)
class DLQEntry:
    """Запись в dead-letter queue."""

    id: str = field(default_factory=lambda: uuid4().hex[:12])
    rule_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    attempts: int = 0
    timestamp: float = field(default_factory=time.time)


async def _redis_raw() -> Any:
    """Возвращает raw redis-клиент (или ``None`` если Redis недоступен)."""
    try:
        from app.infrastructure.clients.storage.redis import redis_client
        return getattr(redis_client, "_raw_client", None) or redis_client
    except Exception as exc:  # noqa: BLE001
        logger.debug("Redis недоступен для DLQ: %s", exc)
        return None


class WebhookRelay:
    """Relay webhook с трансформациями, retry и Redis-backed DLQ.

    Rules хранятся in-memory (предполагается что они перечитываются из БД
    при старте). DLQ хранится в Redis — переживает рестарты и shared между
    инстансами приложения.
    """

    def __init__(self) -> None:
        self._rules: dict[str, RelayRule] = {}
        # Fallback-storage на случай недоступности Redis.
        self._memory_dlq: list[DLQEntry] = []

    # ── Rules management ──

    def add_rule(self, rule: RelayRule) -> str:
        self._rules[rule.id] = rule
        return rule.id

    def remove_rule(self, rule_id: str) -> bool:
        return self._rules.pop(rule_id, None) is not None

    def list_rules(self) -> list[dict[str, Any]]:
        return [
            {
                "id": r.id,
                "event_type": r.event_type,
                "target_url": r.target_url,
                "jmespath": r.jmespath_expression,
                "enabled": r.enabled,
            }
            for r in self._rules.values()
        ]

    # ── Relay pipeline ──

    async def relay(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Рассылает payload по matching rules с трансформацией."""
        matching = [
            r for r in self._rules.values()
            if r.enabled and (r.event_type == "*" or r.event_type == event_type)
        ]
        if not matching:
            return {"status": "no_rules", "event_type": event_type}

        results = []
        for rule in matching:
            transformed = self._transform(payload, rule)
            if transformed is None:
                results.append({"rule_id": rule.id, "status": "filtered_out"})
                continue
            results.append(await self._send_with_retry(rule, transformed))

        sent = sum(1 for r in results if r.get("status") == "sent")
        return {"status": "relayed", "sent": sent, "total": len(matching), "results": results}

    async def transform(self, payload: dict[str, Any], expression: str) -> Any:
        """Применяет JMESPath к payload (для диагностики)."""
        try:
            import jmespath
            return jmespath.search(expression, payload)
        except ImportError:
            return payload
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    def _transform(self, payload: dict[str, Any], rule: RelayRule) -> dict[str, Any] | None:
        if rule.condition:
            try:
                import jmespath
                if not jmespath.search(rule.condition, payload):
                    return None
            except Exception:  # noqa: BLE001
                pass

        if rule.jmespath_expression:
            try:
                import jmespath
                return jmespath.search(rule.jmespath_expression, payload) or payload
            except ImportError:
                return payload
        return payload

    async def _send_with_retry(
        self, rule: RelayRule, payload: dict[str, Any],
    ) -> dict[str, Any]:
        import httpx

        headers = {"Content-Type": "application/json"}
        if rule.secret:
            from app.entrypoints.webhook.signatures import build_signature_headers
            headers.update(build_signature_headers(payload, rule.secret))

        last_error = ""
        for attempt in range(rule.max_retries):
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(rule.target_url, json=payload, headers=headers)
                    if resp.is_success:
                        return {
                            "rule_id": rule.id, "status": "sent",
                            "status_code": resp.status_code,
                        }
                    last_error = f"HTTP {resp.status_code}"
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)

            if attempt < rule.max_retries - 1:
                await asyncio.sleep(2 ** attempt)

        entry = DLQEntry(
            rule_id=rule.id, payload=payload, error=last_error, attempts=rule.max_retries,
        )
        await self._dlq_push(entry)
        return {"rule_id": rule.id, "status": "dlq", "error": last_error}

    # ── DLQ storage (Redis-backed) ──

    async def _dlq_push(self, entry: DLQEntry) -> None:
        """Сохраняет запись в DLQ. Redis-first, fallback на in-memory."""
        raw = await _redis_raw()
        if raw is not None:
            try:
                await raw.lpush(_DLQ_KEY, orjson.dumps(asdict(entry)).decode())
                # LTRIM ограничивает длину — защита от неограниченного роста.
                await raw.ltrim(_DLQ_KEY, 0, _DLQ_MAX_LEN - 1)
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("DLQ Redis push failed: %s, fallback to memory", exc)
        self._memory_dlq.append(entry)

    async def _dlq_all(self) -> list[DLQEntry]:
        """Читает все записи DLQ. Redis-first, memory-fallback."""
        raw = await _redis_raw()
        if raw is None:
            return list(self._memory_dlq)
        try:
            items = await raw.lrange(_DLQ_KEY, 0, -1)
        except Exception as exc:  # noqa: BLE001
            logger.warning("DLQ Redis read failed: %s, fallback to memory", exc)
            return list(self._memory_dlq)

        entries: list[DLQEntry] = []
        for item in items:
            try:
                data = orjson.loads(item)
                entries.append(DLQEntry(**data))
            except Exception:  # noqa: BLE001
                continue
        return entries

    async def _dlq_remove(self, entry_id: str, entry_raw: bytes | str | None = None) -> None:
        """Удаляет одну запись DLQ по id (находит raw через полный обход)."""
        raw = await _redis_raw()
        if raw is None:
            self._memory_dlq = [e for e in self._memory_dlq if e.id != entry_id]
            return
        try:
            items = await raw.lrange(_DLQ_KEY, 0, -1)
            for item in items:
                try:
                    data = orjson.loads(item)
                    if data.get("id") == entry_id:
                        await raw.lrem(_DLQ_KEY, 1, item)
                        return
                except Exception:  # noqa: BLE001
                    continue
        except Exception as exc:  # noqa: BLE001
            logger.warning("DLQ Redis remove failed: %s", exc)

    async def dlq_list(self, limit: int = 50) -> dict[str, Any]:
        """Список DLQ записей (последние ``limit``)."""
        all_entries = await self._dlq_all()
        entries = all_entries[-limit:]
        return {
            "total": len(all_entries),
            "entries": [
                {"id": e.id, "rule_id": e.rule_id, "error": e.error,
                 "attempts": e.attempts, "timestamp": e.timestamp}
                for e in entries
            ],
        }

    async def dlq_retry(self, entry_id: str | None = None) -> dict[str, Any]:
        """Повторная отправка из DLQ.

        Если ``entry_id`` передан — ретраим только эту запись; иначе все.
        """
        all_entries = await self._dlq_all()
        targets = (
            [e for e in all_entries if e.id == entry_id] if entry_id else all_entries
        )

        results = []
        for entry in targets:
            rule = self._rules.get(entry.rule_id)
            if rule is None:
                results.append({"id": entry.id, "status": "rule_not_found"})
                continue
            r = await self._send_with_retry(rule, entry.payload)
            if r.get("status") == "sent":
                await self._dlq_remove(entry.id)
            results.append({"id": entry.id, **r})

        retried = sum(1 for r in results if r.get("status") == "sent")
        return {"retried": retried, "total": len(targets), "results": results}


_webhook_relay = WebhookRelay()


def get_webhook_relay() -> WebhookRelay:
    """Возвращает singleton-инстанс relay'я (module-level)."""
    return _webhook_relay
