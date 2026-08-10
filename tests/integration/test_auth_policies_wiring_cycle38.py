"""B-20 fix (cycle 38): composition root fail-loud при fake-active policy.

Задача: подтвердить, что :func:`src.backend.plugins.composition.di.register_app_state`
поднимает :class:`src.backend.core.errors.ProductionWiringError` при
``policy.engine_enabled=True`` + ОБА ``policy.opa_url`` И ``policy.casbin_model_path``
пустые (fake-active security в production-профиле).

Каждый движок по-прежнему опционален (OPA-only / Casbin-only — валидные
конфигурации из :mod:`tests.integration.test_opa_runtime_cycle37`), но
обнуление обоих URL при включённом мастер-флага → composition root
проваливается fail-loud.

Сценарии:

* **engine_enabled=True** + ОБА URL пустые → raise ``ProductionWiringError``.
* **engine_enabled=False** + ОБА URL пустые → no raise, log+continue (legacy).
* **engine_enabled=True** + только OPA URL задан → no raise (OPA-only valid).
* **engine_enabled=True** + только Casbin path задан → no raise (Casbin-only valid).

Pre-state (зафиксировано до B-20 fix):

* ``plugins/composition/di.py`` имел silent skip: ``if policy_settings.opa_url:
  <wire OPA>``; ``if policy_settings.casbin_model_path: <wire Casbin>``. При
  ``engine_enabled=True`` + оба пустые → цикл целиком silent, лог info-message
  о том, что ничего не заведено. AuthorizationGateway регистрировался с
  пустым ``policies`` tuple, LLM policy-gate оставался только в fail-closed
  capability-check режиме.
* В prod-профиле (cycle 38 #1) ``engine_enabled=True`` поднимается через
  YAML-overlay → silent fake-active security в production запрещена.

Тесты intentionally минимальные: они верифицируют ТОЛЬКО fail-loud semantic
composition root при misconfiguration. Реальный OPA/Casbin runtime coverage
уже есть в ``test_opa_runtime_cycle37.py``.
"""


from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI

from src.backend.core.config.features import feature_flags
from src.backend.core.errors import ProductionWiringError
from src.backend.plugins.composition import di

# ───────────────────────────── fixtures ────────────────────────────────── #


@pytest.fixture(autouse=True)
def _enable_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    """Все тесты работают с authz_gateway_enabled=True."""
    monkeypatch.setattr(feature_flags, "authz_gateway_enabled", True)


@pytest.fixture
def fresh_app() -> FastAPI:
    """Свежий FastAPI app с минимальным state."""
    return FastAPI()


@pytest.fixture
def stub_constructors(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """Подменяет тяжёлые конструкторы из ``register_app_state`` лёгкими mock'ами.

    Используется в тестах, где ``engine_enabled=False`` или требуется
    успешно завершить ``register_app_state`` — мы не хотим поднимать
    реальные OPA/Casbin singletons. Для ``engine_enabled=True`` + raise-кейса
    фикстура НЕ нужна: raise случается ДО попытки инстанциации.
    """
    instances: dict[str, MagicMock] = {}

    def _make_stub(attr: str) -> MagicMock:
        mock = MagicMock(name=attr)
        instances[attr] = mock
        return mock

    monkeypatch.setattr(
        "src.backend.infrastructure.security.api_key_manager.APIKeyManager",
        lambda: _make_stub("api_key_manager"),
    )
    monkeypatch.setattr(
        "src.backend.dsl.engine.tracer.ExecutionTracer", lambda: _make_stub("tracer")
    )
    monkeypatch.setattr(
        "src.backend.dsl.engine.plugin_registry.ProcessorPluginRegistry",
        lambda: _make_stub("plugin_registry"),
    )
    monkeypatch.setattr(
        "src.backend.dsl.engine.versioning.PipelineVersionManager",
        lambda: _make_stub("pipeline_version_manager"),
    )
    monkeypatch.setattr(
        "src.backend.infrastructure.application.slo_tracker.SLOTracker",
        lambda: _make_stub("slo_tracker"),
    )
    monkeypatch.setattr(
        "src.backend.infrastructure.database.pool_monitor.PoolMonitor",
        lambda: _make_stub("pool_monitor"),
    )
    monkeypatch.setattr(
        "src.backend.infrastructure.clients.external.langfuse_client.LangFuseClient",
        lambda: _make_stub("langfuse_client"),
    )
    monkeypatch.setattr(
        "src.backend.infrastructure.application.vault_refresher.VaultSecretRefresher",
        lambda: _make_stub("vault_refresher"),
    )
    monkeypatch.setattr(
        "src.backend.entrypoints.mqtt.mqtt_handler.MqttHandler",
        lambda settings: _make_stub("mqtt_handler"),
    )
    reply_reg = _make_stub("reply_registry")
    monkeypatch.setattr(
        "src.backend.infrastructure.messaging.invocation_replies.get_reply_channel_registry",
        lambda: reply_reg,
    )
    monkeypatch.setattr(
        "src.backend.services.execution.invoker.Invoker",
        lambda: _make_stub("invoker"),
    )
    monkeypatch.setattr(
        "src.backend.infrastructure.watermark.factory.create_watermark_store",
        lambda *args, **kwargs: _make_stub("watermark_store"),
    )
    return instances


def _make_fake_settings(
    *,
    engine_enabled: bool,
    opa_url: str = "",
    casbin_model_path: str | None = None,
) -> Any:
    """Создаёт duck-type settings для monkeypatch в ``policy_settings``."""
    return type(
        "_S",
        (),
        {
            "engine_enabled": engine_enabled,
            "opa_url": opa_url,
            "opa_policy_name": "authz/default",
            "casbin_model_path": casbin_model_path,
            "casbin_policy_path": None,
        },
    )()


# ─────────────────────────────── tests ─────────────────────────────────── #


class TestAuthPoliciesWiringCycle38:
    """B-20 fix (cycle 38): auth_policies fail-loud при engine_enabled=True."""

    def test_engine_enabled_with_both_urls_empty_raises(
        self,
        fresh_app: FastAPI,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """engine_enabled=True + ОБА URL пустые → raise ProductionWiringError.

        Fake-active security: production-wiring говорит "включи policy engines",
        но ни один движок не сконфигурирован. Composition root должен
        провалиться fail-loud, не silent skip.
        """
        fake_settings = _make_fake_settings(
            engine_enabled=True,
            opa_url="",
            casbin_model_path=None,
        )
        monkeypatch.setattr(
            "src.backend.core.config.services.policy.policy_settings",
            fake_settings,
            raising=False,
        )

        with pytest.raises(ProductionWiringError) as exc_info:
            di.register_app_state(fresh_app)

        # Сообщение должно явно указывать на misconfiguration.
        assert "policy.engine_enabled=True" in str(exc_info.value)
        # missing-список содержит обе ненастроенные настройки.
        assert "policy.opa_url" in exc_info.value.missing
        assert "policy.casbin_model_path" in exc_info.value.missing

    def test_engine_enabled_with_opa_url_only_does_not_raise(
        self,
        fresh_app: FastAPI,
        stub_constructors: dict[str, MagicMock],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """engine_enabled=True + только OPA URL → no raise (OPA-only valid).

        Каждый движок опционален, но ОБА пустыми быть не могут. OPA-only
        конфигурация — валидный путь, не должен fail-loud.
        """
        fake_settings = _make_fake_settings(
            engine_enabled=True,
            opa_url="http://opa:8181",
            casbin_model_path=None,
        )
        monkeypatch.setattr(
            "src.backend.core.config.services.policy.policy_settings",
            fake_settings,
            raising=False,
        )

        # Не должно бросить исключение.
        di.register_app_state(fresh_app)

    def test_engine_enabled_with_casbin_path_only_does_not_raise(
        self,
        fresh_app: FastAPI,
        stub_constructors: dict[str, MagicMock],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """engine_enabled=True + только Casbin path → no raise (Casbin-only valid)."""
        fake_settings = _make_fake_settings(
            engine_enabled=True,
            opa_url="",
            casbin_model_path="/etc/casbin/model.conf",
        )
        monkeypatch.setattr(
            "src.backend.core.config.services.policy.policy_settings",
            fake_settings,
            raising=False,
        )

        # Не должно бросить исключение.
        di.register_app_state(fresh_app)

    def test_engine_disabled_with_empty_urls_does_not_raise(
        self,
        fresh_app: FastAPI,
        stub_constructors: dict[str, MagicMock],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """engine_enabled=False + пустые URL → no raise (silent skip legacy).

        На dev/dev_light профилях (default OFF) composition root не выполняет
        wiring policy-движков — AuthorizationGateway создаётся с пустым
        policies tuple, capability check остаётся единственной защитой.
        """
        fake_settings = _make_fake_settings(
            engine_enabled=False,
            opa_url="",
            casbin_model_path=None,
        )
        monkeypatch.setattr(
            "src.backend.core.config.services.policy.policy_settings",
            fake_settings,
            raising=False,
        )

        # Не должно бросить исключение.
        di.register_app_state(fresh_app)

        # AuthorizationGateway создан, но policies chain пустой.
        from src.backend.core.security.authorization_gateway import AuthorizationGateway

        assert isinstance(fresh_app.state.authorization_gateway, AuthorizationGateway)
        assert fresh_app.state.authorization_gateway._policies == ()
