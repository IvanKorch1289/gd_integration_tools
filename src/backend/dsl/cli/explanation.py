"""DSL Route Explain — структурный graph + side-effects analysis.

Per 25.09 audit #9: «Реализовать DSL explain/replay MVP».

``explain_route()`` парсит ``route.toml`` + ``*.dsl.yaml`` и возвращает
structured JSON с:

1. **Graph**: nodes (steps) + edges (sequential flow) для visualization;
2. **Side effects**: network/db/fs/mq/ai для каждого step;
3. **Required capabilities**: computed из step types vs declared;
4. **Retry policies**: max attempts + backoff strategy per step;
5. **Time budgets**: total route timeout + per-step estimates;
6. **Feature flags**: declared в route.toml;
7. **Tenant awareness**: declared в capabilities / route.toml.

Output формат: ``RouteExplanation`` dataclass → ``to_dict()`` → JSON.

Не выполняет route (нет side effects), только статический analysis.
Для runtime simulation — см. ``simulate.py`` (Sprint 7 follow-up).
"""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

__all__ = ("RouteExplanation", "StepExplanation", "SideEffect", "explain_route")


# === Side-effect catalog (subset of processors from src/backend/dsl/engine/processors) ===
# Каждый processor → (capability, side_effect_type, host_pattern).
# Этот catalog используется для объяснения route без runtime execution.
_PROCESSOR_SIDE_EFFECTS: dict[str, tuple[str, str, str]] = {
    # capability, side_effect_type, host_pattern (regex)
    "http_call": ("net.outbound", "network", r"https?://[\w.-]+(:\d+)?(/.*)?$"),
    "soap_call": ("net.outbound", "network", r"https?://[\w.-]+(:\d+)?/soap(/.*)?$"),
    "grpc_call": ("net.outbound", "network", r"[\w.-]+:\d+"),
    "ws_publish": ("net.outbound", "network", r"wss?://[\w.-]+(:\d+)?(/.*)?$"),
    "mq_publish": ("mq.publish", "mq", r"[\w.-]+:[a-z]+:[\w.-]+"),
    "db_query_external": ("db.read", "db", r"[\w.-]+:\d+/[\w.-]+"),
    "db_persist": ("db.write", "db", r"[\w.-]+:\d+/[\w.-]+"),
    "secret_get": ("secrets.read", "secrets", r"vault://[\w./-]+"),
    "file_read": ("fs.read", "fs", r"[\w./-]+"),
    "file_write": ("fs.write", "fs", r"[\w./-]+"),
    "call_com": ("net.outbound", "network", r"https?://[\w.-]+:\d+(/.*)?$"),
    "llm_call": ("ai.llm", "ai", r"[\w.-]+://[\w./-]+"),  # provider
    "audit": ("audit.write", "audit", ""),  # no external host
    "policy": ("", "", ""),  # no side effect
    "feature_flag": ("", "", ""),  # no side effect
    "transform": ("", "", ""),  # no side effect
    "validate_response": ("", "", ""),  # no side effect
    "choice": ("", "", ""),  # no side effect
    "parallel": ("", "", ""),  # no side effect
    "try_catch": ("", "", ""),  # no side effect
    "saga": ("", "", ""),  # orchestration
    "invoke_workflow": ("workflow.invoke", "workflow", ""),
    "invoke_action": ("", "", ""),  # action — internal
    "publish_event": ("", "", ""),
    "redirect": ("", "", ""),  # routing
    "notify_cascade": ("", "", ""),
    "get_setting": ("settings.read", "settings", ""),
    "db_call_procedure": ("db.execute", "db", r"[\w.-]+:\d+/[\w.-]+"),
    "crud_create": ("db.write", "db", r"[\w.-]+:\d+/[\w.-]+"),
    "crud_read": ("db.read", "db", r"[\w.-]+:\d+/[\w.-]+"),
    "crud_update": ("db.write", "db", r"[\w.-]+:\d+/[\w.-]+"),
    "crud_delete": ("db.write", "db", r"[\w.-]+:\d+/[\w.-]+"),
    "crud_list": ("db.read", "db", r"[\w.-]+:\d+/[\w.-]+"),
    "proxy": ("net.outbound", "network", r"https?://[\w.-]+(:\d+)?(/.*)?$"),
}


@dataclass(slots=True, frozen=True)
class SideEffect:
    """Side effect одного step.

    Attributes:
        kind: network | db | fs | mq | ai | audit | secrets | settings | workflow
        capability: required capability из ADR-044
        target: extracted host/URL/path (если applicable)
        description: human-readable summary
    """

    kind: str
    capability: str
    target: str
    description: str

    def to_dict(self) -> dict[str, str]:
        """Сериализация SideEffect в dict для JSON output.

        Returns:
            Dict с полями kind/capability/target/description.
        """
        return asdict(self)


@dataclass(slots=True, frozen=True)
class StepExplanation:
    """Объяснение одного step в route.

    Attributes:
        step_type: тип step (http_call, policy, feature_flag, etc.)
        index: позиция в steps[]
        side_effects: список side effects этого step
        capabilities_required: capabilities запрашиваемые step'ом
        retry: retry policy (max_attempts + backoff strategy) или None
        estimated_duration_ms: rough estimate (default 100ms)
        raw_args: оригинальные args из YAML (для debugging)
    """

    step_type: str
    index: int
    side_effects: list[SideEffect] = field(default_factory=list)
    capabilities_required: tuple[str, ...] = ()
    retry: dict[str, Any] | None = None
    estimated_duration_ms: int = 100
    raw_args: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Сериализация StepExplanation в dict для JSON output.

        Returns:
            Dict с полями step_type/index/side_effects/capabilities_required/
            retry/estimated_duration_ms/raw_args.
        """
        return {
            "step_type": self.step_type,
            "index": self.index,
            "side_effects": [se.to_dict() for se in self.side_effects],
            "capabilities_required": list(self.capabilities_required),
            "retry": self.retry,
            "estimated_duration_ms": self.estimated_duration_ms,
            "raw_args": self.raw_args,
        }


@dataclass(slots=True, frozen=True)
class RouteExplanation:
    """Полное объяснение route.

    Attributes:
        route_id: ID route из route.toml::name
        route_dir: путь к каталогу route
        manifest: содержимое route.toml (dict)
        steps: list[StepExplanation]
        side_effects_aggregate: union всех side effects (для quick view)
        capabilities_required: union всех capabilities
        capabilities_declared: из route.toml::capabilities
        capabilities_missing: required - declared (security gap)
        total_estimated_duration_ms: sum of per-step estimates
        timeout_ms: из manifest.slo.timeout_ms (route timeout budget)
        feature_flags: dict из manifest.feature_flag
        tenant_aware: из manifest.tenant_aware
        issues: list warnings / errors (например, missing capabilities)
    """

    route_id: str
    route_dir: str
    manifest: dict[str, Any]
    steps: list[StepExplanation]
    side_effects_aggregate: tuple[SideEffect, ...]
    capabilities_required: tuple[str, ...]
    capabilities_declared: tuple[str, ...]
    capabilities_missing: tuple[str, ...]
    total_estimated_duration_ms: int
    timeout_ms: int | None
    feature_flags: dict[str, Any]
    tenant_aware: bool
    issues: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Сериализация RouteExplanation в dict для JSON output.

        Returns:
            Dict с полями route_id/route_dir/manifest/steps/side_effects_aggregate/
            capabilities_required/capabilities_declared/capabilities_missing/
            total_estimated_duration_ms/timeout_ms/feature_flags/tenant_aware/issues.
        """
        return {
            "route_id": self.route_id,
            "route_dir": self.route_dir,
            "manifest": self.manifest,
            "steps": [s.to_dict() for s in self.steps],
            "side_effects_aggregate": [
                se.to_dict() for se in self.side_effects_aggregate
            ],
            "capabilities_required": sorted(set(self.capabilities_required)),
            "capabilities_declared": sorted(set(self.capabilities_declared)),
            "capabilities_missing": sorted(set(self.capabilities_missing)),
            "total_estimated_duration_ms": self.total_estimated_duration_ms,
            "timeout_ms": self.timeout_ms,
            "feature_flags": self.feature_flags,
            "tenant_aware": self.tenant_aware,
            "issues": self.issues,
        }


def _extract_host_from_args(args: dict[str, Any]) -> str:
    """Extract host/URL/path из args step'а."""
    for key in ("url", "host", "endpoint", "target", "path", "connection_string"):
        if key in args:
            return str(args[key])
    return ""


def _classify_step(
    step_type: str, args: dict[str, Any]
) -> tuple[tuple[str, ...], list[SideEffect]]:
    """Classify single step: capabilities + side effects."""
    capabilities: list[str] = []
    side_effects: list[SideEffect] = []

    entry = _PROCESSOR_SIDE_EFFECTS.get(step_type)
    if entry is None:
        # Unknown step type — heuristic: check args for known patterns.
        if "url" in args or "host" in args:
            capabilities.append("net.outbound")
            side_effects.append(
                SideEffect(
                    kind="network",
                    capability="net.outbound",
                    target=_extract_host_from_args(args),
                    description=f"Unknown step '{step_type}' with url/host (heuristic: net.outbound)",
                )
            )
        return tuple(capabilities), side_effects

    cap, kind, _ = entry
    if cap:
        capabilities.append(cap)
    if kind:
        target = _extract_host_from_args(args)
        side_effects.append(
            SideEffect(
                kind=kind,
                capability=cap,
                target=target,
                description=f"{step_type} → {kind} ({cap})",
            )
        )
    return tuple(capabilities), side_effects


def _extract_retry(args: dict[str, Any]) -> dict[str, Any] | None:
    """Extract retry policy из step args (policy.step)."""
    retry = args.get("retry")
    if not isinstance(retry, dict):
        return None
    return {
        "attempts": int(retry.get("attempts", 1)),
        "backoff": str(retry.get("backoff", "fixed")),
        "max_delay_ms": int(retry.get("max_delay_ms", 0)),
    }


def _estimate_step_duration(step_type: str, args: dict[str, Any]) -> int:
    """Rough per-step duration estimate (ms) для total time budget."""
    estimates: dict[str, int] = {
        "http_call": 200,
        "soap_call": 300,
        "grpc_call": 150,
        "ws_publish": 50,
        "mq_publish": 30,
        "db_query_external": 50,
        "db_persist": 80,
        "db_call_procedure": 100,
        "secret_get": 50,
        "file_read": 5,
        "file_write": 10,
        "llm_call": 1500,
        "audit": 5,
        "policy": 1,
        "feature_flag": 1,
        "transform": 1,
        "validate_response": 5,
        "invoke_workflow": 500,
        "proxy": 100,
        "crud_create": 100,
        "crud_read": 50,
        "crud_update": 80,
        "crud_delete": 50,
        "crud_list": 100,
        "redirect": 10,
        "get_setting": 5,
    }
    return estimates.get(step_type, 100)


def _parse_yaml_steps(yaml_path: Path) -> list[dict[str, Any]]:
    """Parse *.dsl.yaml → list of steps (skipping comments)."""
    try:
        with yaml_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError) as exc:
        raise ValueError(f"failed to parse {yaml_path}: {exc}") from exc

    if not isinstance(data, dict):
        return []

    steps = data.get("steps", [])
    if not isinstance(steps, list):
        return []

    # Filter to dict steps (skip comments which are strings starting with #).
    return [s for s in steps if isinstance(s, dict)]


def _parse_toml_manifest(toml_path: Path) -> dict[str, Any]:
    """Parse route.toml → manifest dict."""
    try:
        with toml_path.open("rb") as f:
            return tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise ValueError(f"failed to parse {toml_path}: {exc}") from exc


def explain_route(route_dir: Path) -> RouteExplanation:
    """Build structured explanation of a route.

    Per 25.09 audit #9: «gd route explain — graph, network/DB side effects,
    retries, time budgets, feature flags».

    Args:
        route_dir: каталог с ``route.toml`` + ``*.dsl.yaml``.

    Returns:
        :class:`RouteExplanation` с graph + side effects + capabilities
        + retry/time budgets + feature flags.

    Raises:
        ValueError: при отсутствии route.toml или yaml parse error.
    """
    route_dir = Path(route_dir)
    toml_path = route_dir / "route.toml"
    if not toml_path.is_file():
        raise ValueError(f"route.toml не найден в {route_dir}")

    manifest = _parse_toml_manifest(toml_path)
    declared_caps = tuple(manifest.get("capabilities", []) or [])

    yaml_files = sorted(route_dir.glob("*.dsl.yaml"))
    if not yaml_files:
        raise ValueError(f"*.dsl.yaml файлы отсутствуют в {route_dir}")

    # Aggregate steps из всех yaml файлов.
    all_steps: list[dict[str, Any]] = []
    for yf in yaml_files:
        all_steps.extend(_parse_yaml_steps(yf))

    step_explanations: list[StepExplanation] = []
    capabilities_required_set: set[str] = set()
    side_effects_all: list[SideEffect] = []
    issues: list[str] = []
    total_duration = 0

    for idx, step in enumerate(all_steps):
        if not step:
            continue
        step_type, args = next(iter(step.items()))
        caps, side_effects = _classify_step(step_type, args)
        retry = _extract_retry(args) if step_type == "policy" else None
        duration = _estimate_step_duration(step_type, args)
        step_exp = StepExplanation(
            step_type=step_type,
            index=idx,
            side_effects=side_effects,
            capabilities_required=caps,
            retry=retry,
            estimated_duration_ms=duration,
            raw_args=args,
        )
        step_explanations.append(step_exp)
        capabilities_required_set.update(caps)
        side_effects_all.extend(side_effects)
        total_duration += duration * max(1, retry["attempts"] if retry else 1)

    capabilities_required = tuple(sorted(capabilities_required_set))
    capabilities_missing = tuple(
        sorted(set(capabilities_required) - set(declared_caps))
    )
    if capabilities_missing:
        issues.append(
            f"Required capabilities {capabilities_missing} не объявлены в "
            f"route.toml::capabilities (declared: {list(declared_caps)})"
        )

    timeout_ms = None
    slo = manifest.get("slo", {}) or {}
    if isinstance(slo, dict):
        to = slo.get("timeout_ms")
        if isinstance(to, int):
            timeout_ms = to
    if timeout_ms is not None and total_duration > timeout_ms:
        issues.append(
            f"Sum of step estimates ({total_duration}ms) > route timeout "
            f"({timeout_ms}ms) — risk of timeout under load"
        )

    feature_flag_block = manifest.get("feature_flag", {}) or {}
    if not isinstance(feature_flag_block, dict):
        feature_flag_block = {}

    return RouteExplanation(
        route_id=str(manifest.get("name", route_dir.name)),
        route_dir=str(route_dir),
        manifest=manifest,
        steps=step_explanations,
        side_effects_aggregate=tuple(side_effects_all),
        capabilities_required=capabilities_required,
        capabilities_declared=declared_caps,
        capabilities_missing=capabilities_missing,
        total_estimated_duration_ms=total_duration,
        timeout_ms=timeout_ms,
        feature_flags=feature_flag_block,
        tenant_aware=bool(manifest.get("tenant_aware", False)),
        issues=issues,
    )
