"""YAML-schema + blueprint variants для route_wizard."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTES_DIR = ROOT / "routes"

SOURCE_CHOICES = ("http", "cron", "kafka", "webhook", "file_watch", "cdc")
SINK_CHOICES = ("http", "kafka", "db", "file", "dlq", "log")
AI_PROVIDER_CHOICES = ("claude", "openai", "gemini", "mock-llm")

SOURCE_DESCRIPTIONS = {
    "http": "HTTP endpoint (REST/webhook-style)",
    "cron": "Cron scheduler (APScheduler cron-style)",
    "kafka": "Kafka consumer (topic + group_id)",
    "webhook": "Webhook receiver (path-based)",
    "file_watch": "File watcher (glob pattern)",
    "cdc": "CDC source (database change data capture)",
}

SINK_DESCRIPTIONS = {
    "http": "HTTP sink (http_call step)",
    "kafka": "Kafka producer (topic publish)",
    "db": "Database sink (crud_create step)",
    "file": "File sink (write to path)",
    "dlq": "Dead Letter Queue (dlq sink)",
    "log": "Log sink (structured log output)",
}


def _source_yaml(source: str) -> dict[str, object]:
    """Build source section for DSL YAML."""
    if source == "http":
        return {"http": {"method": "POST", "path": "/api/v1/CHANGEME"}}
    if source == "cron":
        return {"cron": "0 */6 * * *"}
    if source == "kafka":
        return {"kafka": {"topic": "CHANGEME", "group_id": "CHANGEME"}}
    if source == "webhook":
        return {"webhook": {"path": "/webhooks/CHANGEME"}}
    if source == "file_watch":
        return {"file_watch": {"glob": "/data/incoming/*.csv"}}
    if source == "cdc":
        return {"cdc": {"table": "public.CHANGEME"}}
    return {source: "TODO"}


def _sink_step(sink: str) -> dict[str, object]:
    """Build sink step for DSL YAML."""
    if sink == "http":
        return {"http_call": {"url": "https://api.test/sink", "method": "POST"}}
    if sink == "kafka":
        return {"sink_publish": {"sink_kind": "kafka", "topic": "CHANGEME"}}
    if sink == "db":
        return {"crud_create": {"entity": "CHANGEME", "body": "${body}"}}
    if sink == "file":
        return {"sink_publish": {"sink_kind": "file", "path": "/data/out/$id.json"}}
    if sink == "dlq":
        return {"sink_publish": {"sink_kind": "dlq", "queue": "default_dlq"}}
    return {"log": {"level": "info"}}


def build_dsl_yaml(
    *,
    name: str,
    source: str,
    sink: str,
    ai: bool = False,
    retry: bool = False,
    retry_attempts: int = 3,
    ai_model: str = "claude-3-5-sonnet-20241022",
    ai_provider: str = "claude",
    ai_prompt_from: str = "body.context",
    ai_result_property: str = "ai_response",
    p95_ms: int = 500,
    timeout_ms: int = 5000,
) -> str:
    """Собирает основной YAML-маршрут."""
    import yaml

    steps: list = []

    # Normalizer call_function
    steps.append(
        {"call_function": {"ref": f"extensions.{name}.normalizer:apply_rules"}}
    )

    # Retry policy
    if retry:
        steps.append(
            {
                "policy": {
                    "retry": {
                        "attempts": retry_attempts,
                        "backoff": "exponential",
                        "max_delay_ms": 5000,
                    }
                }
            }
        )

    # AI step
    if ai:
        steps.append(
            {
                "llm_call": {
                    "provider": ai_provider,
                    "model": ai_model,
                    "prompt_from": ai_prompt_from,
                    "result_property": ai_result_property,
                    "dry_run_provider": "mock-llm",
                }
            }
        )

    # Sink
    steps.append(_sink_step(sink))

    # Audit
    steps.append({"audit": {"action": f"{name}.processed"}})

    # Response
    steps.append({"to": {"response": {"code": 200, "body": "${body}"}}})

    route: dict = {"route_id": name, "source": _source_yaml(source), "steps": steps}

    return yaml.safe_dump(route, allow_unicode=True, sort_keys=False)


def build_route_toml(
    *,
    name: str,
    ai: bool = False,
    retry: bool = False,
    tenant_aware: bool = True,
    p95_ms: int = 500,
    timeout_ms: int = 5000,
    enabled_features: list[str] | None = None,
) -> str:
    """Собирает route.toml manifest."""
    capabilities = ["net.outbound", "db.write", "audit.write"]
    if ai:
        capabilities.append("ai.llm")
    if retry:
        capabilities.append("retry.enabled")
    cap_toml = "[" + ", ".join(f'"{c}"' for c in capabilities) + "]"
    feat_str = ", ".join(f'"{f}"' for f in (enabled_features or ["default"]))

    return f"""\
# route.toml (V11): manifest для route '{name}' (S33 W1 wizard).
name = "{name}"
version = "0.1.0"
requires_core = ">=22.0,<23"
capabilities = {cap_toml}
tenant_aware = {str(tenant_aware).lower()}
feature_flag = {{ enabled = true, gate = "{name}_enabled" }}
slo = {{ p95_ms = {p95_ms}, timeout_ms = {timeout_ms} }}
schedule = "never"


## Разрешённые feature-flags (управление фичей через feature_flags section)
[feature_flags]
default = [{feat_str}]
"""
