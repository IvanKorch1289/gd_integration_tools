"""Webhook Relay + Transformations — JMESPath трансформации + retry queue + DLQ.

Outbound webhook:
1. Применяет JMESPath трансформацию к payload перед отправкой
2. Фильтрует по условию (отправлять или нет)
3. Retry с exponential backoff при ошибках
4. DLQ для сообщений, превысивших max retries

Actions: webhook.relay, webhook.transform, webhook.dlq_list, webhook.dlq_retry
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from app.core.decorators.singleton import singleton

__all__ = ("WebhookRelay", "RelayRule", "get_webhook_relay")

logger = logging.getLogger(__name__)


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
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    rule_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    attempts: int = 0
    timestamp: float = field(default_factory=time.time)


@singleton
class WebhookRelay:
    """Relay webhook с трансформациями, retry и DLQ."""

    def __init__(self) -> None:
        self._rules: dict[str, RelayRule] = {}
        self._dlq: list[DLQEntry] = []

    def add_rule(self, rule: RelayRule) -> str:
        self._rules[rule.id] = rule
        return rule.id

    def remove_rule(self, rule_id: str) -> bool:
        return self._rules.pop(rule_id, None) is not None

    def list_rules(self) -> list[dict[str, Any]]:
        return [
            {"id": r.id, "event_type": r.event_type, "target_url": r.target_url,
             "jmespath": r.jmespath_expression, "enabled": r.enabled}
            for r in self._rules.values()
        ]

    async def relay(
        self, event_type: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
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
            r = await self._send_with_retry(rule, transformed)
            results.append(r)

        sent = sum(1 for r in results if r.get("status") == "sent")
        return {"status": "relayed", "sent": sent, "total": len(matching), "results": results}

    async def transform(self, payload: dict[str, Any], expression: str) -> Any:
        """Применяет JMESPath к payload. Для тестирования трансформаций."""
        try:
            import jmespath
            return jmespath.search(expression, payload)
        except ImportError:
            return payload
        except Exception as exc:
            return {"error": str(exc)}

    def _transform(self, payload: dict[str, Any], rule: RelayRule) -> dict[str, Any] | None:
        if rule.condition:
            try:
                import jmespath
                if not jmespath.search(rule.condition, payload):
                    return None
            except Exception:
                pass

        if rule.jmespath_expression:
            try:
                import jmespath
                return jmespath.search(rule.jmespath_expression, payload) or payload
            except ImportError:
                return payload
        return payload

    async def _send_with_retry(
        self, rule: RelayRule, payload: dict[str, Any]
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
                        return {"rule_id": rule.id, "status": "sent", "status_code": resp.status_code}
                    last_error = f"HTTP {resp.status_code}"
            except Exception as exc:
                last_error = str(exc)

            if attempt < rule.max_retries - 1:
                await asyncio.sleep(2 ** attempt)

        self._dlq.append(DLQEntry(
            rule_id=rule.id, payload=payload, error=last_error, attempts=rule.max_retries,
        ))
        return {"rule_id": rule.id, "status": "dlq", "error": last_error}

    async def dlq_list(self, limit: int = 50) -> dict[str, Any]:
        """Список DLQ записей."""
        entries = self._dlq[-limit:]
        return {
            "total": len(self._dlq),
            "entries": [
                {"id": e.id, "rule_id": e.rule_id, "error": e.error,
                 "attempts": e.attempts, "timestamp": e.timestamp}
                for e in entries
            ],
        }

    async def dlq_retry(self, entry_id: str | None = None) -> dict[str, Any]:
        """Повторная отправка из DLQ."""
        if entry_id:
            targets = [e for e in self._dlq if e.id == entry_id]
        else:
            targets = list(self._dlq)

        results = []
        for entry in targets:
            rule = self._rules.get(entry.rule_id)
            if not rule:
                results.append({"id": entry.id, "status": "rule_not_found"})
                continue
            r = await self._send_with_retry(rule, entry.payload)
            if r.get("status") == "sent":
                self._dlq = [e for e in self._dlq if e.id != entry.id]
            results.append({"id": entry.id, **r})

        retried = sum(1 for r in results if r.get("status") == "sent")
        return {"retried": retried, "total": len(targets), "results": results}


def get_webhook_relay() -> WebhookRelay:
    return WebhookRelay()
