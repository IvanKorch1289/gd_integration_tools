"""YAML-schema + blueprint variants для route_wizard.

ADR-0405/ADR-0415: манифест роута генерируется в **каноничной** форме —
конверт ``[route]`` + таблицы ``[[route.capabilities]]`` с отдельными полями
``name``/``scope`` (ADR-0078). Legacy-форма ``capabilities = [...]`` объявлена
deprecated: она молча теряла scope (``scope=None``), а capability с
``scope_required=True`` без scope отвергалась гейтом.

Соответствие «шаг DSL → capability» взято из ``PROCESSOR_SIDE_EFFECTS``
(``src/backend/dsl/cli/explanation.py``) — это единственный каталог шагов и
их capability в проекте.
"""

from __future__ import annotations

from pathlib import Path

# Round 11 fix: shared helper для синхронизации default constraint с pyproject.toml.
from tools.wizards.plugin_wizard import _default_requires_core

ROOT = Path(__file__).resolve().parents[2]
ROUTES_DIR = ROOT / "routes"

SOURCE_CHOICES = ("http", "cron", "kafka", "webhook", "file_watch", "cdc")
SINK_CHOICES = ("http", "kafka", "db", "file", "dlq", "log")
AI_PROVIDER_CHOICES = ("claude", "openai", "gemini", "mock-llm")

#: Capability, которые роут вправе объявить сам: они входят в публичный
#: набор ядра (``vocabulary.public_capabilities()``), поэтому subset-инвариант
#: ADR-044 (``route.capabilities ⊆ union(requires_plugins) ∪ public``)
#: выполняется без плагина-провайдера.
#:
#: scope выбран по семантике vocabulary:
#: * ``net.outbound`` — host внешнего сервиса (runtime-гейт сверяет hostname,
#:   ``core/net/outbound_http.py``);
#: * ``db.write`` — алиас ресурса БД (matcher — ``ExactAliasMatcher``, поэтому
#:   scope обязан совпасть с именем таблицы/профиля);
#: * ``audit.write`` — семейство audit-sink'ов (tenant-id / audit-sink / '*').
_PUBLIC_CAPABILITY_BY_SINK: dict[str, tuple[tuple[str, str], ...]] = {
    # http_call → net.outbound; host взят из сгенерированного шага
    # ``http_call`` (https://api.test/sink).
    "http": (("net.outbound", "api.test"),),
    # crud_create → db.write; scope = entity из сгенерированного шага.
    "db": (("db.write", "CHANGEME"),),
}

#: Capability, которые в публичный набор **не** входят: объявить их может
#: только плагин-владелец (``[[capabilities]]`` в его ``plugin.toml``), иначе
#: роут не пройдёт subset-инвариант ADR-044. Поэтому в сгенерированный
#: манифест они попадают комментарием-подсказкой, а не активной строкой.
_PROVIDER_ONLY_BY_SINK: dict[str, tuple[str, str]] = {
    # sink_publish(kafka) → mq.publish; scope = topic.
    "kafka": ("mq.publish", "<topic>"),
    # sink_publish(file) → fs.write; scope = путь.
    "file": ("fs.write", "<path>"),
}

#: llm_call → ai.invoke (scope = workflow_id pattern или '*').
_AI_CAPABILITY: tuple[str, str] = ("ai.invoke", "*")

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


def build_capability_blocks(*, sink: str = "http", ai: bool = False) -> str:
    """Сгенерировать блоки ``[[route.capabilities]]`` для манифеста роута.

    Capability выбираются **по фактическому использованию** сгенерированного
    DSL (соответствие «шаг → capability» — ``PROCESSOR_SIDE_EFFECTS`` в
    ``src/backend/dsl/cli/explanation.py``):

    * ``audit:``      → ``audit.write`` (scope = семейство audit-sink'ов);
    * ``http_call``   → ``net.outbound`` (scope = host);
    * ``crud_create`` → ``db.write`` (scope = алиас ресурса БД);
    * ``llm_call``    → ``ai.invoke`` — capability **не публичная**, её может
      объявить только плагин-владелец, поэтому в манифест попадает
      комментарием-подсказкой (активная строка сломала бы subset-инвариант
      ADR-044 и роут не загрузился бы).

    Args:
        sink: Sink шага сгенерированного DSL.
        ai: Добавлен ли AI-шаг (``llm_call``).

    Returns:
        TOML-фрагмент с декларациями capability (без ``[route]``-конверта).

    """
    lines: list[str] = []

    for name, scope in _PUBLIC_CAPABILITY_BY_SINK.get(sink, ()):
        lines.append(_capability_comment(name))
        lines.append("[[route.capabilities]]")
        lines.append(f'name = "{name}"')
        lines.append(f'scope = "{scope}"')
        lines.append("")

    # audit.write — шаг ``audit:`` есть в каждом сгенерированном pipeline.
    lines.append(_capability_comment("audit.write"))
    lines.append("[[route.capabilities]]")
    lines.append('name = "audit.write"')
    lines.append('scope = "audit:*"')
    lines.append("")

    provider_only = _PROVIDER_ONLY_BY_SINK.get(sink)
    if provider_only is not None:
        lines.append(_provider_only_comment(provider_only[0], provider_only[1]))
        lines.append("")
    if ai:
        lines.append(_provider_only_comment(_AI_CAPABILITY[0], _AI_CAPABILITY[1]))
        lines.append("")

    return "\n".join(lines)


def _capability_comment(name: str) -> str:
    """Поясняющий комментарий к capability-декларации."""
    hints = {
        "net.outbound": (
            "# net.outbound — host внешнего сервиса: runtime-гейт сверяет scope\n"
            "# по hostname (core/net/outbound_http.py). При смене сервиса обновите\n"
            "# и scope, и URL шага http_call."
        ),
        "db.write": (
            "# db.write — алиас ресурса БД: matcher в vocabulary — ExactAliasMatcher,\n"
            "# поэтому scope обязан совпасть с именем таблицы/профиля. Замените\n"
            "# scope вместе с entity в DSL-шаге crud_create."
        ),
        "audit.write": (
            "# audit.write — семейство audit-sink'ов (vocabulary: scope = tenant-id,\n"
            "# audit-sink или '*'). Шаг audit: пишет события роута."
        ),
    }
    return hints.get(name, f"# {name}")


def _provider_only_comment(name: str, scope: str) -> str:
    """Подсказка для capability, которую объявляет только плагин-владелец."""
    return (
        f'# {name} (scope = "{scope}") — capability не публичная: объявить её\n'
        "# может только плагин-владелец ([[capabilities]] в его plugin.toml) и\n"
        "# подключить его через [route.requires_plugins]. Без этого роут не\n"
        "# пройдёт subset-инвариант ADR-044, поэтому строка оставлена комментарием."
    )


def build_route_toml(
    *,
    name: str,
    ai: bool = False,
    retry: bool = False,
    tenant_aware: bool = True,
    p95_ms: int = 500,
    timeout_ms: int = 5000,
    enabled_features: list[str] | None = None,
    sink: str = "http",
) -> str:
    """Собрать ``route.toml`` manifest (каноничная форма ADR-0405/ADR-0415).

    Capability объявляются таблицами ``[[route.capabilities]]`` с отдельными
    ``name``/``scope`` — legacy-форма ``capabilities = [...]`` объявлена
    deprecated в ADR-0405 (теряла scope → роут не грузился).

    Args:
        name: Имя роута (snake_case).
        ai: Добавить AI-шаг (``llm_call``) — требует capability ``ai.invoke``.
        retry: Добавить retry-policy. Политика повторов **не** является
            capability (``policy`` в каталоге шагов не имеет side-effect), так
            что в манифест она не попадает.
        tenant_aware: Pipeline работает в TenantContext.
        p95_ms: SLO p95, мс.
        timeout_ms: Жёсткий таймаут обработчика, мс.
        enabled_features: Разрешённые feature-flags.
        sink: Sink шага сгенерированного DSL — определяет набор capability.

    Returns:
        TOML-текст манифеста.

    """
    feat_str = ", ".join(f'"{f}"' for f in (enabled_features or ["default"]))

    return f"""\
# route.toml (V11): manifest для route '{name}'.
#
# ADR-0405/ADR-0415: capability объявляются структурированно —
# [[route.capabilities]] с отдельными полями name/scope (ADR-0078).
# Legacy-форма (плоский список строк) объявлена deprecated: она молча теряла
# scope, а capability с scope_required=True без scope отвергалась гейтом.
[route]
name = "{name}"
version = "0.1.0"
requires_core = "{_default_requires_core()}"
pipelines = ["main.dsl.yaml"]
tenant_aware = {str(tenant_aware).lower()}
feature_flag = {{ enabled = true, gate = "{name}_enabled" }}
slo = {{ p95_ms = {p95_ms}, timeout_ms = {timeout_ms} }}
schedule = "never"

{build_capability_blocks(sink=sink, ai=ai)}
[route.feature_flags]
default = [{feat_str}]
"""
