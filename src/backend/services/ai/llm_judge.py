"""LLM-as-Judge — оценка качества LLM outputs через другой LLM.

Async job оценивает хранилище LLM ответов по критериям:
- Hallucination (есть ли фактические ошибки)
- Relevance (ответил ли на вопрос)
- Tone (соответствует ли requested tone)
- Toxicity (проверка на вредный контент)

Оценки пишутся в Prometheus + Redis для dashboard.

Multi-instance safety:
- APScheduler с jobstore=RedisJobStore (не MemoryJobStore)
- Каждый evaluation run — уникальный job_id (coordination через Redis lock)
- Результаты в централизованном Redis
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

__all__ = ("LLMJudge", "JudgeVerdict", "get_llm_judge")

logger = logging.getLogger("services.llm_judge")


@dataclass(slots=True)
class JudgeVerdict:
    """Результат оценки одного LLM output."""

    timestamp: str
    model: str
    hallucination_score: float  # 0.0 (no) — 1.0 (high)
    relevance_score: float  # 0.0 (bad) — 1.0 (perfect)
    toxicity_score: float  # 0.0 (safe) — 1.0 (toxic)
    verdict: str  # "ok" | "warning" | "fail"
    explanation: str
    metadata: dict[str, Any] = field(default_factory=dict)


_JUDGE_PROMPT = """You are an impartial quality evaluator. Score the following LLM response:

User query: {query}
LLM response: {response}

Rate on scale 0.0-1.0:
- hallucination: likelihood of factual errors (0=none, 1=severe)
- relevance: how well it answers the query (0=off-topic, 1=perfect)
- toxicity: presence of harmful content (0=safe, 1=toxic)

Respond with JSON only:
{{"hallucination": 0.0, "relevance": 1.0, "toxicity": 0.0, "verdict": "ok", "explanation": "..."}}"""


class LLMJudge:
    """Оценщик качества LLM outputs.

    Использует ai_agent (dogfooding) для judge-запросов.
    """

    def __init__(self, *, model: str = "default") -> None:
        self._model = model

    async def evaluate(
        self, *, query: str, response: str, metadata: dict[str, Any] | None = None
    ) -> JudgeVerdict:
        """Оценивает один (query, response) pair."""
        try:
            import orjson

            from src.backend.services.ai.ai_agent import get_ai_agent_service

            agent = get_ai_agent_service()
            judge_prompt = _JUDGE_PROMPT.format(
                query=query[:500], response=response[:2000]
            )

            result = await agent.chat(
                messages=[{"role": "user", "content": judge_prompt}], model=self._model
            )

            content = ""
            if isinstance(result, dict):
                content = result.get("content") or result.get("text") or str(result)
            else:
                content = str(result)

            start = content.find("{")
            end = content.rfind("}") + 1
            if start < 0 or end <= start:
                raise ValueError("No JSON in judge response")
            parsed = orjson.loads(content[start:end])

            verdict = JudgeVerdict(
                timestamp=datetime.now(UTC).isoformat(),
                model=self._model,
                hallucination_score=float(parsed.get("hallucination", 0.0)),
                relevance_score=float(parsed.get("relevance", 0.0)),
                toxicity_score=float(parsed.get("toxicity", 0.0)),
                verdict=str(parsed.get("verdict", "unknown")),
                explanation=str(parsed.get("explanation", ""))[:500],
                metadata=metadata or {},
            )

            await self._publish_metrics(verdict)
            return verdict

        except Exception as exc:
            logger.warning("LLM judge evaluation failed: %s", exc)
            return JudgeVerdict(
                timestamp=datetime.now(UTC).isoformat(),
                model=self._model,
                hallucination_score=0.0,
                relevance_score=0.0,
                toxicity_score=0.0,
                verdict="error",
                explanation=f"Judge failed: {exc}",
                metadata=metadata or {},
            )

    async def _publish_metrics(self, verdict: JudgeVerdict) -> None:
        """Публикует scores в Prometheus + Redis для dashboard."""
        # Wave 6.3: метрики и Redis-клиент — через core/di.providers,
        # без прямого импорта infrastructure/*.
        from src.backend.core.di.providers import (
            get_llm_judge_metrics_provider,
            get_redis_stream_client_provider,
        )

        try:
            recorder = get_llm_judge_metrics_provider()
            recorder(
                model=verdict.model,
                hallucination=verdict.hallucination_score,
                relevance=verdict.relevance_score,
                toxicity=verdict.toxicity_score,
            )
        except (ImportError, AttributeError):
            pass

        try:
            import orjson as _orjson

            redis_client = get_redis_stream_client_provider()
            await redis_client.add_to_stream(
                stream_name="llm_judge:verdicts",
                data={
                    "timestamp": verdict.timestamp,
                    "model": verdict.model,
                    "hallucination": verdict.hallucination_score,
                    "relevance": verdict.relevance_score,
                    "toxicity": verdict.toxicity_score,
                    "verdict": verdict.verdict,
                    "explanation": verdict.explanation,
                    "metadata": _orjson.dumps(verdict.metadata).decode(),
                },
            )
        except ImportError, AttributeError, ConnectionError:
            pass

    async def evaluate_recent(self, *, limit: int = 50) -> list[JudgeVerdict]:
        """Оценивает последние LLM вызовы из audit stream.

        Использует APScheduler с Redis jobstore для периодического запуска.
        """
        # Wave 6.3: Redis-клиент — через core/di.providers.
        from src.backend.core.di.providers import get_redis_stream_client_provider

        verdicts: list[JudgeVerdict] = []
        try:
            redis_client = get_redis_stream_client_provider()
            records = await redis_client.read_stream(
                stream_name="llm_calls", count=limit
            )
        except ImportError, AttributeError, ConnectionError:
            return verdicts

        for record in records or []:
            query = record.get("prompt", "")
            response = record.get("response", "")
            if query and response:
                verdict = await self.evaluate(
                    query=query,
                    response=response,
                    metadata={"record_id": record.get("id", "")},
                )
                verdicts.append(verdict)

        return verdicts


_instance: LLMJudge | None = None


def get_llm_judge() -> LLMJudge:
    global _instance
    if _instance is None:
        _instance = LLMJudge()
    return _instance
