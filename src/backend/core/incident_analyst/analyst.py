"""Incident Analyst — pure-Python diagnostic hypothesis generator (Wave 3 #23).

Read-only: generates hypotheses + recommendations без side effects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

__all__ = (
    "Hypothesis",
    "IncidentAnalyst",
    "IncidentContext",
    "IncidentReport",
    "Recommendation",
    "get_incident_analyst",
)


@dataclass(slots=True)
class IncidentContext:
    """Контекст incident для analysis.

    Attributes:
        error_type: Exception class name (e.g., "TimeoutError").
        error_message: Error message text.
        trace_id: OTel/Correlation trace ID.
        route_id: Affected route.
        tenant_id: Affected tenant.
        recent_deploys: List of recent deploys (version + timestamp).
        recent_config_changes: List of recent config changes.
        latency_p99_ms: Recent p99 latency (if known).
        error_rate: Recent error rate (if known).
        dependencies: List of external dependencies involved.
    """

    error_type: str
    error_message: str = ""
    trace_id: str = ""
    route_id: str = ""
    tenant_id: str = ""
    recent_deploys: list[str] = field(default_factory=list)
    recent_config_changes: list[str] = field(default_factory=list)
    latency_p99_ms: float | None = None
    error_rate: float | None = None
    dependencies: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Hypothesis:
    """Diagnostic hypothesis."""

    title: str
    description: str
    confidence: float  # 0.0-1.0
    evidence: list[str] = field(default_factory=list)
    category: str = ""  # "code" | "infra" | "config" | "data" | "external"


@dataclass(slots=True)
class Recommendation:
    """Suggested safe action."""

    action: str  # "rollback" | "replay" | "scale" | "investigate" | "wait"
    description: str
    risk_level: str  # "low" | "medium" | "high"
    reversible: bool = True
    estimated_impact: str = ""


@dataclass(slots=True)
class IncidentReport:
    """Generated report с hypotheses + recommendations."""

    context: IncidentContext
    hypotheses: list[Hypothesis] = field(default_factory=list)
    recommendations: list[Recommendation] = field(default_factory=list)
    severity: str = "unknown"  # "critical" | "high" | "medium" | "low" | "unknown"
    summary: str = ""

    @property
    def top_hypothesis(self) -> Hypothesis | None:
        if not self.hypotheses:
            return None
        return max(self.hypotheses, key=lambda h: h.confidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "severity": self.severity,
            "hypotheses": [
                {
                    "title": h.title,
                    "description": h.description,
                    "confidence": h.confidence,
                    "category": h.category,
                    "evidence": h.evidence,
                }
                for h in self.hypotheses
            ],
            "recommendations": [
                {
                    "action": r.action,
                    "description": r.description,
                    "risk_level": r.risk_level,
                    "reversible": r.reversible,
                    "estimated_impact": r.estimated_impact,
                }
                for r in self.recommendations
            ],
        }


# Pattern → (hypotheses factory, recommendations factory).
_PATTERNS: dict[str, dict[str, Any]] = {
    "TimeoutError": {
        "hypotheses": [
            ("External dependency slow/dead",
             "Upstream service unreachable или timeout; проверить p99 latency зависимости.",
             "external", 0.7),
            ("Network issue (DNS, firewall, packet loss)",
             "Network path к upstream прерван; проверить DNS resolution, firewall rules.",
             "infra", 0.5),
            ("Resource exhaustion (DB connection pool)",
             "Connection pool исчерпан; проверить pool metrics и active queries.",
             "infra", 0.4),
        ],
        "recommendations": [
            ("investigate", "Проверить health upstream dependency через dashboard.",
             "low", True, "Read-only check"),
            ("scale", "Увеличить timeout / connection pool если recent deploy.",
             "medium", True, "Affects new requests only"),
        ],
    },
    "OutOfMemoryError": {
        "hypotheses": [
            ("Memory leak в новом коде",
             "Recent deploy ввёл утечку памяти; проверить heap dump.",
             "code", 0.8),
            ("Unbounded data growth (large query result)",
             "Query возвращает больше данных чем ожидалось; bounded pagination.",
             "code", 0.5),
        ],
        "recommendations": [
            ("rollback", "Rollback к предыдущему deploy если недавний.",
             "low", True, "Restore service quickly"),
            ("scale", "Restart pods для освобождения memory.",
             "low", True, "Temporary fix"),
        ],
    },
    "ConnectionError": {
        "hypotheses": [
            ("Database down или restarted",
             "DB connection refused; проверить pg_is_in_recovery().",
             "infra", 0.8),
            ("Network partition / firewall change",
             "Network rules changed; verify с network team.",
             "infra", 0.5),
        ],
        "recommendations": [
            ("investigate", "Check DB / network health via status page.",
             "low", True, "No side effects"),
            ("scale", "Restart pods для re-establish connections.",
             "low", True, "Reconnects on startup"),
        ],
    },
    "IntegrityError": {
        "hypotheses": [
            ("Schema mismatch (expected vs actual columns)",
             "Recent migration changed schema; application using old model.",
             "code", 0.9),
            ("Concurrent update conflict",
             "Two transactions updated same row; need retry with fresh data.",
             "data", 0.4),
        ],
        "recommendations": [
            ("rollback", "Rollback recent schema migration.",
             "medium", True, "Restore compatibility"),
            ("investigate", "Check migration history vs application deploys.",
             "low", True, "Diagnostic"),
        ],
    },
    "PermissionError": {
        "hypotheses": [
            ("File/directory mode changed (chmod 0o700 vs 0o755)",
             "Permission fix вроде diskcache migration (commit 63fadf4fe) изменил mode на 0o700.",
             "config", 0.85),
            ("User running as wrong uid/gid",
             "Container running process as different user than file owner.",
             "config", 0.3),
        ],
        "recommendations": [
            ("investigate", "ls -la на проблемном path; проверить uid процесса.",
             "low", True, "Read-only"),
            ("scale", "Restart с correct user если misconfigured.",
             "low", True, "Pod restart"),
        ],
    },
    "KeyError": {
        "hypotheses": [
            ("Config missing (env var / secret not loaded)",
             "Required config / secret не загружен; check deployment yaml.",
             "config", 0.7),
            ("Schema field rename в recent deploy",
             "Код ожидает старое имя поля, БД/контракт имеет новое.",
             "code", 0.4),
        ],
        "recommendations": [
            ("investigate", "Check config + secret presence в deployment.",
             "low", True, "Diagnostic"),
            ("rollback", "Rollback если недавний deploy изменил field names.",
             "medium", True, "Restore compatibility"),
        ],
    },
    "ValidationError": {
        "hypotheses": [
            ("Request schema changed (missing field)",
             "API consumers используют устаревший contract.",
             "code", 0.6),
            ("Pydantic model update с new required field",
             "Model adds new required field without default.",
             "code", 0.5),
        ],
        "recommendations": [
            ("investigate", "Check recent model changes и contract version.",
             "low", True, "Diagnostic"),
        ],
    },
}


# Generic hypotheses if no specific pattern.
_GENERIC_HYPOTHESES: list[tuple[str, str, str, float]] = [
    (
        "Recent deploy ввёл regression",
        "Последний deploy содержит fix, который вызывает regression.",
        "code",
        0.6,
    ),
    (
        "External dependency issue",
        "Upstream service has issue (network, latency, capacity).",
        "external",
        0.5,
    ),
    (
        "Resource exhaustion (DB / memory / connections)",
        "Infrastructure resource reached limit; check metrics.",
        "infra",
        0.4,
    ),
]


class IncidentAnalyst:
    """Read-only diagnostic helper."""

    def __init__(self) -> None:
        pass

    def analyze(self, ctx: IncidentContext) -> IncidentReport:
        """Analyze incident → hypotheses + recommendations."""
        report = IncidentReport(
            context=ctx,
            summary=f"{ctx.error_type} on {ctx.route_id or 'unknown route'}",
        )

        # 1. Pattern-based hypotheses.
        pattern = _PATTERNS.get(ctx.error_type)
        if pattern:
            for title, desc, cat, conf in pattern.get("hypotheses", []):
                evidence = self._build_evidence(ctx, title)
                report.hypotheses.append(
                    Hypothesis(
                        title=title,
                        description=desc,
                        confidence=conf,
                        category=cat,
                        evidence=evidence,
                    )
                )
            for action, desc, risk, reversible, impact in pattern.get(
                "recommendations", []
            ):
                report.recommendations.append(
                    Recommendation(
                        action=action,
                        description=desc,
                        risk_level=risk,
                        reversible=reversible,
                        estimated_impact=impact,
                    )
                )
        else:
            # 2. Generic hypotheses.
            for title, desc, cat, conf in _GENERIC_HYPOTHESES:
                evidence = self._build_evidence(ctx, title)
                report.hypotheses.append(
                    Hypothesis(
                        title=title,
                        description=desc,
                        confidence=conf,
                        category=cat,
                        evidence=evidence,
                    )
                )

        # 3. Context-based boosts.
        self._apply_context_boosts(ctx, report)

        # 4. Sort by confidence.
        report.hypotheses.sort(key=lambda h: h.confidence, reverse=True)

        # 5. Severity.
        report.severity = self._classify_severity(ctx, report)

        return report

    def _build_evidence(
        self, ctx: IncidentContext, hypothesis_title: str
    ) -> list[str]:
        """Build evidence list для hypothesis из context."""
        evidence: list[str] = []
        if ctx.recent_deploys:
            evidence.append(
                f"Recent deploys: {', '.join(ctx.recent_deploys[:3])}"
            )
        if ctx.recent_config_changes:
            evidence.append(
                f"Config changes: {', '.join(ctx.recent_config_changes[:3])}"
            )
        if ctx.latency_p99_ms is not None and ctx.latency_p99_ms > 1000:
            evidence.append(f"P99 latency: {ctx.latency_p99_ms}ms (degraded)")
        if ctx.error_rate is not None and ctx.error_rate > 0.05:
            evidence.append(f"Error rate: {ctx.error_rate:.1%} (elevated)")
        if ctx.dependencies:
            evidence.append(f"Dependencies: {', '.join(ctx.dependencies)}")
        if ctx.trace_id:
            evidence.append(f"Trace ID: {ctx.trace_id}")
        if not evidence:
            evidence.append("No additional context available")
        return evidence

    def _apply_context_boosts(
        self, ctx: IncidentContext, report: IncidentReport
    ) -> None:
        """Boost confidence based on context signals."""
        # Recent deploy → boost "code" hypotheses.
        if ctx.recent_deploys:
            for h in report.hypotheses:
                if h.category == "code":
                    h.confidence = min(1.0, h.confidence + 0.15)
        # High latency → boost "infra" hypotheses.
        if ctx.latency_p99_ms and ctx.latency_p99_ms > 2000:
            for h in report.hypotheses:
                if h.category in ("infra", "external"):
                    h.confidence = min(1.0, h.confidence + 0.1)
        # Config changes → boost "config" hypotheses.
        if ctx.recent_config_changes:
            for h in report.hypotheses:
                if h.category == "config":
                    h.confidence = min(1.0, h.confidence + 0.15)

    def _classify_severity(
        self, ctx: IncidentContext, report: IncidentReport
    ) -> str:
        """Classify severity based on error_rate + p99 + error type."""
        if ctx.error_rate is not None and ctx.error_rate > 0.5:
            return "critical"
        if ctx.error_type in (
            "OutOfMemoryError",
            "SystemError",
        ):
            return "critical"
        if (
            ctx.error_rate is not None and ctx.error_rate > 0.1
        ) or (ctx.latency_p99_ms and ctx.latency_p99_ms > 5000):
            return "high"
        if report.hypotheses and report.hypotheses[0].confidence > 0.7:
            return "medium"
        if report.hypotheses:
            return "low"
        return "unknown"


_analyst: IncidentAnalyst | None = None


def get_incident_analyst() -> IncidentAnalyst:
    global _analyst
    if _analyst is None:
        _analyst = IncidentAnalyst()
    return _analyst


def reset_incident_analyst() -> None:
    global _analyst
    _analyst = None
