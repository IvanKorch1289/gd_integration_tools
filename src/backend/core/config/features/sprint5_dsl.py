"""Sprint 5 DSL+Workflow feature-flags (T1.3.16 split from core.config.features.__init__).

Извлечено 25 flags (S38 P1.1 W1 T1.3.16):
- Sprint 5 K3 DSL+Workflow (25):
  - proc_html_template (Sprint 5 K3 W1)
  - proc_jsonpath (Sprint 5 K3 W1)
  - proc_jq (Sprint 5 K3 W1)
  - proc_regex_extractor (Sprint 5 K3 W1)
  - proc_webhook_signature (Sprint 5 K3 W2)
  - proc_zip_archive (Sprint 5 K3 W2)
  - proc_pdf_template (Sprint 5 K3 W2)
  - proc_ldap_query (Sprint 5 K3 W3)
  - proc_webdav (Sprint 5 K3 W3)
  - proc_ics_calendar (Sprint 5 K3 W3)
  - proc_unit_conversion (Sprint 5 K3 W3)
  - proc_geo (Sprint 5 K3 W3)
  - proc_rate_convert (Sprint 5 K3 W4)
  - db_call_procedure_enabled (Sprint 5 K3 W8)
  - policy_chainable_enabled (Sprint 5 K3 W7)
  - web_search_enabled (Sprint 5 K3 W9)
  - workflow_step_log_enabled (Sprint 5 K3 W11)
  - workflow_dryrun_enabled (Sprint 5 K3 W10)
  - cdc_postgres_enabled (Sprint 5 K3 W5)
  - result_unwrap_processor (Sprint 5 K3 W12)
  - blueprint_cdc_enrich (Sprint 5 K3 W6)
  - blueprint_ai_pipeline (Sprint 5 K3 W6)
  - blueprint_saga_compensation (Sprint 5 K3 W6)
  - taskgroup_processors (Sprint 5 K3 W13)
  - invoke_workflow_reply_enabled (Sprint 5 K3 W14)
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Sprint5DSLFlags(BaseSettings):
    """Sprint 5 K3 DSL+Workflow. Owner: K3 DSL.

    Per S38 T1.3.16, извлечено из monolithic ``core.config.features.FeatureFlags``.

    Re-export в ``__init__.py``:
        from src.backend.core.config.features.sprint5_dsl import Sprint5DSLFlags
        class FeatureFlags(..., Sprint5DSLFlags, ...):
            ...

    Env-var prefix: ``FEATURE_``.
    """

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

    # ─── Sprint 5 — К3 DSL+Workflow ───────────────────────────────────────
    proc_html_template: bool = Field(
        default=False,
        title="K3 S5 W1: HtmlTemplateProcessor (Jinja2 HTML rendering)",
        description=(
            "K3 Sprint 5 Wave 1. Owner: K3 DSL. ETA: S5-W1. "
            "Активирует регистрацию HtmlTemplateProcessor в ProcessorRegistry."
        ),
    )

    proc_jsonpath: bool = Field(
        default=False,
        title="K3 S5 W1: JsonPathProcessor (jsonpath-ng query)",
        description=(
            "K3 Sprint 5 Wave 1. Owner: K3 DSL. ETA: S5-W1. "
            "Активирует JsonPathProcessor для извлечения поля по JsonPath."
        ),
    )

    proc_jq: bool = Field(
        default=False,
        title="K3 S5 W1: JqProcessor (jmespath query)",
        description=(
            "K3 Sprint 5 Wave 1. Owner: K3 DSL. ETA: S5-W1. "
            "Активирует JqProcessor для трансформации JSON через JMESPath."
        ),
    )

    proc_regex_extractor: bool = Field(
        default=False,
        title="K3 S5 W1: RegexExtractorProcessor (re.findall)",
        description=(
            "K3 Sprint 5 Wave 1. Owner: K3 DSL. ETA: S5-W1. "
            "Активирует RegexExtractorProcessor (regex named-groups)."
        ),
    )

    proc_webhook_signature: bool = Field(
        default=False,
        title="K3 S5 W2: WebhookSignatureProcessor (standardwebhooks HMAC verify)",
        description=(
            "K3 Sprint 5 Wave 2. Owner: K3 DSL. ETA: S5-W2. "
            "Активирует WebhookSignatureProcessor — HMAC-SHA256 / JWS verify "
            "входящих webhooks (Stripe-style standardwebhooks)."
        ),
    )

    proc_zip_archive: bool = Field(
        default=False,
        title="K3 S5 W2: ZipArchiveProcessor (stdlib zipfile pack/unpack)",
        description=(
            "K3 Sprint 5 Wave 2. Owner: K3 DSL. ETA: S5-W2. "
            "Активирует ZipArchiveProcessor — pack/unpack ZIP-архивов."
        ),
    )

    proc_pdf_template: bool = Field(
        default=False,
        title="K3 S5 W2: PdfTemplateProcessor (reportlab PDF rendering)",
        description=(
            "K3 Sprint 5 Wave 2. Owner: K3 DSL. ETA: S5-W2. "
            "Активирует PdfTemplateProcessor — генерация PDF из шаблона."
        ),
    )

    proc_ldap_query: bool = Field(
        default=False,
        title="K3 S5 W3: LdapQueryProcessor (ldap3 search)",
        description=(
            "K3 Sprint 5 Wave 3. Owner: K3 DSL. ETA: S5-W3. "
            "Активирует LdapQueryProcessor — async LDAP search через ldap3."
        ),
    )

    proc_webdav: bool = Field(
        default=False,
        title="K3 S5 W3: WebDavProcessor (webdav4 upload/download)",
        description=(
            "K3 Sprint 5 Wave 3. Owner: K3 DSL. ETA: S5-W3. "
            "Активирует WebDavProcessor — file операции через WebDAV."
        ),
    )

    proc_ics_calendar: bool = Field(
        default=False,
        title="K3 S5 W3: IcsCalendarProcessor (ics.py calendar parse/render)",
        description=(
            "K3 Sprint 5 Wave 3. Owner: K3 DSL. ETA: S5-W3. "
            "Активирует IcsCalendarProcessor — iCalendar parsing/rendering."
        ),
    )

    proc_unit_conversion: bool = Field(
        default=False,
        title="K3 S5 W3: UnitConversionProcessor (pint quantity convert)",
        description=(
            "K3 Sprint 5 Wave 3. Owner: K3 DSL. ETA: S5-W3. "
            "Активирует UnitConversionProcessor — pint-based unit conversion."
        ),
    )

    proc_geo: bool = Field(
        default=False,
        title="K3 S5 W3: GeoProcessor (geopy distance/geocoding)",
        description=(
            "K3 Sprint 5 Wave 3. Owner: K3 DSL. ETA: S5-W3. "
            "Активирует GeoProcessor — distance calc + geocoding (sync via thread)."
        ),
    )

    proc_rate_convert: bool = Field(
        default=False,
        title="K3 S5 W4: RateConvertProcessor (currency rates через WAF httpx)",
        description=(
            "K3 Sprint 5 Wave 4. Owner: K3 DSL. ETA: S5-W4. "
            "Активирует RateConvertProcessor — currency rates через "
            "OutboundHttpClient (WAF). default-OFF до интеграции с rate-provider."
        ),
    )

    db_call_procedure_enabled: bool = Field(
        default=False,
        title="K3 S5 W8: DSL .db_call_procedure(name, params, schema)",
        description=(
            "K3 Sprint 5 Wave 8. Owner: K3 DSL. ETA: S5-W8. "
            "Активирует RouteBuilder .db_call_procedure() builder method + "
            "DbCallProcedureProcessor (asyncpg execute SP)."
        ),
    )

    policy_chainable_enabled: bool = Field(
        default=False,
        title="K3 S5 W7: .policy.cache().policy.circuit_breaker() chainable",
        description=(
            "K3 Sprint 5 Wave 7. Owner: K3 DSL. ETA: S5-W7. "
            "Активирует chainable .policy.* API в RouteBuilder — composable "
            "policies через ResilienceCoordinator."
        ),
    )

    web_search_enabled: bool = Field(
        default=False,
        title="K3 S5 W9: .web_search(engine, query, max_results) builder",
        description=(
            "K3 Sprint 5 Wave 9. Owner: K3 DSL. ETA: S5-W9. "
            "Активирует RouteBuilder .web_search() поверх Tavily/Perplexity/SearXNG."
        ),
    )

    workflow_step_log_enabled: bool = Field(
        default=False,
        title="K3 S5 W11: StepAuditMiddleware → ClickHouse workflow_step_log",
        description=(
            "K3 Sprint 5 Wave 11. Owner: K3 DSL. ETA: S5-W11. "
            "Активирует StepAuditMiddleware — запись step-execution в ClickHouse "
            "workflow_step_log + OTel custom span attributes."
        ),
    )

    workflow_dryrun_enabled: bool = Field(
        default=False,
        title="K3 S5 W10: manage.py workflow dryrun (record/replay)",
        description=(
            "K3 Sprint 5 Wave 10. Owner: K3 DSL. ETA: S5-W10. "
            "Активирует manage.py workflow dryrun subcommand + JSON-отчёт."
        ),
    )

    cdc_postgres_enabled: bool = Field(
        default=False,
        title="K3 S5 W5: CDC Postgres logical replication (psycopg3+pgoutput)",
        description=(
            "K3 Sprint 5 Wave 5. Owner: K3 DSL. ETA: S5-W5. "
            "Активирует CdcPostgresLogicalSource + RouteBuilder .from_cdc(). "
            "default-OFF до создания replication-slot и smoke-теста."
        ),
    )

    result_unwrap_processor: bool = Field(
        default=False,
        title="K3 S5 W12: ResultUnwrapProcessor (result>=0.17 monad)",
        description=(
            "K3 Sprint 5 Wave 12. Owner: K3 DSL. ETA: S5-W12. "
            "Активирует ResultUnwrapProcessor — Ok/Err handling в pipeline."
        ),
    )

    blueprint_cdc_enrich: bool = Field(
        default=False,
        title="K3 S5 W6: Blueprint cdc_enrich",
        description=(
            "K3 Sprint 5 Wave 6. Owner: K3 DSL. ETA: S5-W6. "
            "Активирует blueprint cdc_enrich (cdc → enrich → publish)."
        ),
    )

    blueprint_ai_pipeline: bool = Field(
        default=False,
        title="K3 S5 W6: Blueprint ai_pipeline",
        description=(
            "K3 Sprint 5 Wave 6. Owner: K3 DSL. ETA: S5-W6. "
            "Активирует blueprint ai_pipeline (input → preprocess → llm → validate → output)."
        ),
    )

    blueprint_saga_compensation: bool = Field(
        default=False,
        title="K3 S5 W6: Blueprint saga_with_compensation",
        description=(
            "K3 Sprint 5 Wave 6. Owner: K3 DSL. ETA: S5-W6. "
            "Активирует blueprint saga_with_compensation (steps + compensate stages)."
        ),
    )

    taskgroup_processors: bool = Field(
        default=False,
        title="K3 S5 W13: asyncio.TaskGroup migration в parallel/streaming/batch",
        description=(
            "K3 Sprint 5 Wave 13. Owner: K3 DSL. ETA: S5-W13. "
            "Активирует TaskGroup-based реализацию в processors. "
            "default-OFF до перформанс-baseline diff."
        ),
    )

    invoke_workflow_reply_enabled: bool = Field(
        default=False,
        title="K3 S5 W14: .invoke_workflow reply-channels (correlation_id routing)",
        description=(
            "K3 Sprint 5 Wave 14. Owner: K3 DSL. ETA: S5-W14. "
            "Активирует reply-channel routing через correlation_id для "
            "async-api/signal modes invoke_workflow."
        ),
    )


__all__ = ("Sprint5DSLFlags",)
