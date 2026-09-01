"""Unit-тесты ``core.config.services`` — coverage ratchet (S48 W38).

core/config/services/__init__.py — facade для per-service config Settings
(40+ symbols: CacheSettings, RedisSettings, GraphQLSettings, InvokerSettings,
JupyterHubSettings, LLMSettings, MailSettings, QueueSettings, ResilienceSettings,
RPASettings, SMSSettings, SnapshotSettings, TasksSettings, WSSettings,
WatermarkSettings, FileStorageSettings, LogStorageSettings + matching
singletons + BreakerProfile/FallbackPolicy для resilience).
Big facade (~50 statements), 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class/singleton identity.
"""

from __future__ import annotations

import pytest

from src.backend.core.config import services as config_services
from src.backend.core.config.services import (
    # Settings classes
    CacheSettings,
    FileStorageSettings,
    GRPCSettings,
    GraphQLSettings,
    InvokerSettings,
    JupyterHubSettings,
    LLMSettings,
    LogStorageSettings,
    MailSettings,
    QueueSettings,
    RPASettings,
    RedisSettings,
    ResilienceSettings,
    SMSSettings,
    SnapshotSettings,
    TasksSettings,
    WSSettings,
    WatermarkSettings,
    # Singleton instances
    cache_settings,
    fs_settings,
    graphql_settings,
    grpc_settings,
    invoker_settings,
    jupyter_hub_settings,
    llm_settings,
    log_settings,
    mail_settings,
    queue_settings,
    redis_settings,
    resilience_settings,
    rpa_settings,
    sms_settings,
    snapshot_settings,
    tasks_settings,
    watermark_settings,
    ws_settings,
    # Resilience primitives
    BreakerProfile,
    FallbackPolicy,
)


@pytest.mark.unit
class TestServicesFacadeAllExports:
    """``__all__`` audit через parametrize (38 symbols)."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "CacheSettings",
            "FileStorageSettings",
            "GRPCSettings",
            "GraphQLSettings",
            "InvokerSettings",
            "JupyterHubSettings",
            "LLMSettings",
            "LogStorageSettings",
            "MailSettings",
            "QueueSettings",
            "RPASettings",
            "RedisSettings",
            "ResilienceSettings",
            "SMSSettings",
            "SnapshotSettings",
            "TasksSettings",
            "WSSettings",
            "WatermarkSettings",
            "cache_settings",
            "fs_settings",
            "graphql_settings",
            "grpc_settings",
            "invoker_settings",
            "jupyter_hub_settings",
            "llm_settings",
            "log_settings",
            "mail_settings",
            "queue_settings",
            "redis_settings",
            "resilience_settings",
            "rpa_settings",
            "sms_settings",
            "snapshot_settings",
            "tasks_settings",
            "watermark_settings",
            "ws_settings",
            "BreakerProfile",
            "FallbackPolicy",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(config_services, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in config_services.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 38 символов."""
        assert len(config_services.__all__) == 38


@pytest.mark.unit
class TestServicesFacadeIdentity:
    """Identity checks: Settings classes + singleton instances + resilience primitives."""

    def test_settings_classes_are_types(self) -> None:
        """``Settings`` classes — type (Pydantic settings)."""
        for cls in (
            CacheSettings,
            FileStorageSettings,
            GRPCSettings,
            GraphQLSettings,
            InvokerSettings,
            JupyterHubSettings,
            LLMSettings,
            LogStorageSettings,
            MailSettings,
            QueueSettings,
            RPASettings,
            RedisSettings,
            ResilienceSettings,
            SMSSettings,
            SnapshotSettings,
            TasksSettings,
            WSSettings,
            WatermarkSettings,
        ):
            assert isinstance(cls, type), f"{cls.__name__} is not a type"

    def test_singletons_are_settings_instances(self) -> None:
        """Singletons — instances of corresponding Settings classes."""
        for cls, singleton in (
            (CacheSettings, cache_settings),
            (FileStorageSettings, fs_settings),
            (GRPCSettings, grpc_settings),
            (GraphQLSettings, graphql_settings),
            (InvokerSettings, invoker_settings),
            (JupyterHubSettings, jupyter_hub_settings),
            (LLMSettings, llm_settings),
            (LogStorageSettings, log_settings),
            (MailSettings, mail_settings),
            (QueueSettings, queue_settings),
            (RPASettings, rpa_settings),
            (RedisSettings, redis_settings),
            (ResilienceSettings, resilience_settings),
            (SMSSettings, sms_settings),
            (SnapshotSettings, snapshot_settings),
            (TasksSettings, tasks_settings),
            (WSSettings, ws_settings),
            (WatermarkSettings, watermark_settings),
        ):
            assert isinstance(singleton, cls), (
                f"{singleton!r} is not an instance of {cls.__name__}"
            )

    def test_breaker_profile_is_type(self) -> None:
        """``BreakerProfile`` — type (Pydantic dataclass)."""
        assert isinstance(BreakerProfile, type)

    def test_fallback_policy_is_type(self) -> None:
        """``FallbackPolicy`` — type (Pydantic dataclass)."""
        assert isinstance(FallbackPolicy, type)
