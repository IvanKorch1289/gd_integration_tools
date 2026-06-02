"""LangFuse REST API reader для cost-дашборда (Wave D.5).

Тонкая обёртка над ``langfuse.Langfuse.fetch_traces(...)``. Аналитика
группируется по ``route|tenant|provider`` и сортируется по убыванию
``total_cost_usd``.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

logger = logging.getLogger(__name__)

__all__ = ("LangFuseReader", "CostRow")


@dataclass(slots=True)
class CostRow:
    """Строка таблицы cost-аналитики."""

    key: str
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "requests": self.requests,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
        }


class LangFuseReader:
    """Адаптер чтения cost-метрик из LangFuse."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    def _ensure_client(self) -> Any | None:
        if self._client is not None:
            return self._client
        try:
            from langfuse import Langfuse

            from src.backend.core.config.ai_2026 import langfuse_settings

            if not langfuse_settings.enabled:
                return None
            self._client = Langfuse(
                host=langfuse_settings.host or None,
                public_key=langfuse_settings.public_key or None,
                secret_key=langfuse_settings.secret_key or None,
            )
            return self._client
        except Exception as exc:  # noqa: BLE001
            logger.debug("LangFuseReader client init skipped: %s", exc)
            return None

    async def fetch_costs(
        self,
        *,
        window: timedelta = timedelta(hours=24),
        group_by: Literal["route", "tenant", "provider"] = "route",
        top_n: int = 10,
    ) -> list[CostRow]:
        """Возвращает топ-N строк cost-агрегации.

        Args:
            window: окно (от now-window до now).
            group_by: ключ группировки.
            top_n: размер топа.
        """
        client = self._ensure_client()
        if client is None:
            return []
        try:
            traces = client.fetch_traces(
                from_timestamp=(datetime.now(timezone.utc) - window).isoformat()
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("LangFuse fetch_traces failed: %s", exc)
            return []

        data = _normalize_traces(traces)
        buckets: dict[str, CostRow] = defaultdict(lambda: CostRow(key=""))
        for trace in data:
            key = _select_key(trace, group_by)
            row = buckets[key]
            row.key = key
            row.requests += 1
            usage = trace.get("usage") or {}
            row.prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
            row.completion_tokens += int(usage.get("completion_tokens", 0) or 0)
            row.total_cost_usd += float(trace.get("cost_usd", 0.0) or 0.0)

        rows = sorted(buckets.values(), key=lambda r: r.total_cost_usd, reverse=True)
        return rows[: max(int(top_n), 0)]


def _normalize_traces(raw: Any) -> list[dict[str, Any]]:
    """Принимает разные форматы ``fetch_traces`` (SDK 2.x)."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [t for t in raw if isinstance(t, dict)]
    data_attr = getattr(raw, "data", None)
    if isinstance(data_attr, list):
        out = []
        for item in data_attr:
            if isinstance(item, dict):
                out.append(item)
            elif hasattr(item, "model_dump"):
                out.append(item.model_dump())
        return out
    if isinstance(raw, dict) and isinstance(raw.get("data"), list):
        return [t for t in raw["data"] if isinstance(t, dict)]
    return []


def _select_key(trace: dict[str, Any], group_by: str) -> str:
    meta = trace.get("metadata") or {}
    if group_by == "tenant":
        return str(meta.get("tenant") or "default")
    if group_by == "provider":
        model = str(trace.get("model") or meta.get("model") or "")
        return model.split("/", 1)[0] if "/" in model else (model or "unknown")
    return str(meta.get("route") or trace.get("name") or "unknown")
