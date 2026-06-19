"""DSL feature-flags (T1.3.8 split from core.config.features.__init__).

Извлечено 12 flags из K5 — DSL + K3 — sources (S38 P1.1 epic, T1.3.8 PR):
- frontend_schema_registry_ui (K5 W1)
- frontend_action_bus_ui (K5 W2)
- dsl_processor_registry_strict (K5 W3)
- dsl_route_hot_reload (K5 W5)
- lsp_server_published (S19 K3 W4)
- admin_marketplace_endpoints (K5 W4)
- dsl_visual_editor_enabled (S19 K3 W5)
- builder_source_sugar (K3 W5)
- service_toml_loader (K3 W5)
- graphql_subscription_source (K3 W5)
- email_imap_source (K3 W5)
- notification_dsl_enabled (K3 W1)

Future T1.3.8.5+ extensions (Sprint 5/6/7 K3 DSL sections, ~60 fields).
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DSLFlags(BaseSettings):
    """K5 — DSL + K3 — sources. Owner: K5 DSL, K3 DSL.

    Per S38 T1.3.8, извлечено из monolithic ``core.config.features.FeatureFlags``
    для eventual multi-inheritance split (9 доменов, 10 PRs).

    Re-export в ``__init__.py``:
        from src.backend.core.config.features.dsl import DSLFlags
        class FeatureFlags(..., DSLFlags, ...):
            ...

    Env-var prefix: ``FEATURE_`` (inherited from parent pydantic-settings config).
    """

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

    frontend_schema_registry_ui: bool = Field(
        default=True,
        title="Frontend: Schema Registry UI (6-tab viewer)",
        description=(
            "K5 Wave 1. Owner: K5 DSL. ETA: S3-W1. "
            "Активирует страницу 40_Schema_Registry.py — 6-tab viewer "
            "(OpenAPI / WSDL / XSD / Protobuf / AsyncAPI / GraphQL SDL) "
            "с Download / Validate / Diff. "
            "default-OFF до staging-smoke + интеграции с Schema-registry RAM (R1)."
        ),
    )

    frontend_action_bus_ui: bool = Field(
        default=True,
        title="K5: Action Bus Streamlit UI (список actions + invoke с JSON-payload)",
        description=(
            "K5 Wave 2. Owner: K5 DSL. ETA: S3-W2. "
            "Активирует страницу 50_Action_Bus.py с invoke registered actions, "
            "JSON-payload editor, 3 invoke modes (sync/async-fire-and-forget/async-api). "
            "default-OFF до staging-smoke action-bus-client."
        ),
    )

    dsl_processor_registry_strict: bool = Field(
        default=True,
        title="DSL: ProcessorRegistry strict mode (отказ при missing schema)",
        description=(
            "K5 Wave 3. Owner: K5 DSL. ETA: S2-W3. "
            "Активирует строгий режим ProcessorRegistry: процессоры без "
            "reflection-schema не регистрируются. default-OFF до 100% "
            "покрытия 77 процессоров."
        ),
    )

    dsl_route_hot_reload: bool = Field(
        default=True,
        title="DSL: hot-reload для routes/<name>/ (<3s)",
        description=(
            "K5 Wave 5. Owner: K5 DSL. ETA: S2-W5. "
            "Активирует watchfiles-based reload routes/<name>/route.toml. "
            "default-OFF в production; default-ON в dev профиле."
        ),
    )

    lsp_server_published: bool = Field(
        default=True,
        title="S19 K3 W4: LSP server published (YAML schema completion)",
        description=(
            "S19 K3 W4. Owner: K3 DSL. "
            "Активирует YAML schema completion в LSP server "
            "(tools/dsl_lsp/schema_completion.py + gd_dsl.yaml schema). "
            "CompletionList с 22 step-type keywords (proxy, call_function, "
            "crud_create, и т.д.) + JSON-Schema snippets. "
            "default-OFF до staging-smoke completion в VSCode/JetBrains."
        ),
    )

    admin_marketplace_endpoints: bool = Field(
        default=True,
        title="Admin: Action-Bus + Plugin-Marketplace REST endpoints",
        description=(
            "K5 Wave 4. Owner: K5 DSL. ETA: S3-W4. "
            "Активирует /api/v1/admin/actions/* и /api/v1/admin/plugins/* — "
            "backend endpoints для Streamlit 50_Action_Bus.py + 60_Plugin_Marketplace.py. "
            "default-OFF до staging-smoke и интеграции с ActionHandlerRegistry + PluginLoader."
        ),
    )

    dsl_visual_editor_enabled: bool = Field(
        default=True,
        title="Sprint 19 K3 W5: DSL Visual Editor (Drag-Drop Route Builder)",
        description=(
            "S19 K3 W5. Owner: K3 DSL. "
            "Активирует страницу 40_dsl_visual_editor.py — drag-drop route editor "
            "с three-panel layout (step palette / canvas / properties). "
            "Export to YAML. default-OFF до staging-smoke."
        ),
    )

    builder_source_sugar: bool = Field(
        default=True,
        title="K3: Builder source-сахар (.from_kafka/.from_rabbit/.from_mqtt/...)",
        description=(
            "K3 Wave 5. Owner: K3 DSL. ETA: S3-W5. "
            "Активирует 8 classmethod'ов-фабрик SourcesMixin: "
            "from_cdc / from_kafka / from_rabbit / from_mqtt / "
            "from_redis_streams / from_filewatcher / from_webhook / from_schedule. "
            "При False методы работают в режиме совместимости (строковый source DSN). "
            "default-OFF до интеграции с SourceRegistry и staging-smoke."
        ),
    )

    service_toml_loader: bool = Field(
        default=True,
        title="K3: service.toml loader + ServiceDSLRegistry",
        description=(
            "K3 Wave 5. Owner: K3 DSL. ETA: S3-W5. "
            "Активирует загрузку manifest'ов *.service.toml из extensions/ "
            "и регистрацию ServiceSpec в ServiceDSLRegistry singleton. "
            "При False register() — no-op. "
            "default-OFF до интеграции с auto-registration в plugin-loader."
        ),
    )

    graphql_subscription_source: bool = Field(
        default=True,
        title="K3: GraphQL subscription source (@strawberry.subscription via WebSocket)",
        description=(
            "K3 Wave 5. Owner: K3 DSL. ETA: S3-W5. "
            "Активирует GraphQLSubscriptionSource — async-генератор событий "
            "из GraphQL WebSocket-подписок (протокол graphql-ws, библиотека gql). "
            "default-OFF до установки 'gql[websockets]' и staging-smoke."
        ),
    )

    email_imap_source: bool = Field(
        default=True,
        title="K3: EmailIMAPSource через aioimaplib (IMAP IDLE, stream())",
        description=(
            "K3 Wave 5. Owner: K3 Email/IMAP. ETA: S3-W5. "
            "Активирует EmailIMAPSource — AsyncIterator[EmailMessage] поверх "
            "IMAP IDLE (aioimaplib). Используется .from_imap() в RouteBuilder. "
            "default-OFF до установки 'aioimaplib' в S3 cutover и staging-smoke."
        ),
    )

    notification_dsl_enabled: bool = Field(
        default=True,
        title="K3: Notification DSL через Apprise (.notify / .notify_multi)",
        description=(
            "K3 Wave 1. Owner: K3 Notification. ETA: S3-W1. "
            "Активирует AppriseNotificationService и DSL-процессор notify_apprise. "
            "100+ backends: Slack/Telegram/Discord/Email/SMS и др. "
            "default-OFF до установки 'apprise>=1.9.0' в S3 cutover и staging-smoke."
        ),
    )


__all__ = ("DSLFlags",)
