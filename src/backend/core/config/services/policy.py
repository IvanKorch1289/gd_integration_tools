"""B-12 fix (cycle 37): настройки policy engines (OPA + Casbin).

Управляют активацией runtime-policy-движков для
:class:`AuthorizationGateway`. По умолчанию **disabled** на dev/dev_light —
никаких сетевых вызовов к внешним policy-сервисам при разработке.
Для prod-профиля выставляются в ``config_profiles/prod.yml`` через overlay
и становятся ``enabled=true``.

YAML-группа: ``policy``. ENV-prefix: ``POLICY_``.
"""

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("PolicySettings", "policy_settings")


class PolicySettings(BaseSettingsWithLoader):
    """Конфигурация policy engines (B-12 fix, cycle 37).

    Поля:

    * ``engine_enabled`` — мастер-флаг: при ``False`` composition root
      вообще НЕ инстанцирует OPA/Casbin и не пробрасывает ``policies``
      в :class:`AuthorizationGateway` (default OFF на dev/dev_light).
    * ``opa_url`` — базовый URL OPA REST API (см. ``OPAClient.base_url``).
    * ``opa_policy_name`` — rego-package path (точки → слэши в URL),
      дефолт ``"authz/default"``.
    * ``casbin_model_path`` / ``casbin_policy_path`` — файловые пути
      для ``CasbinAdapter`` (4-арг модель с tenant, см.
      ``policies/casbin_model_tenant.conf``).
    """

    yaml_group: ClassVar[str] = "policy"
    model_config = SettingsConfigDict(env_prefix="POLICY_", extra="forbid")

    engine_enabled: bool = Field(
        default=False,
        description=(
            "Мастер-флаг policy-движков. При False composition root не "
            "инстанцирует OPA/Casbin (dev/dev_light default OFF)."
        ),
        examples=[False, True],
    )
    opa_url: str = Field(
        default="http://localhost:8181",
        description="Базовый URL OPA REST API (``OPAClient.base_url``).",
        examples=["http://opa:8181", "http://localhost:8181"],
    )
    opa_policy_name: str = Field(
        default="authz/default",
        description=(
            "Имя rego-package (точки → слэши на стороне клиента), например "
            "``authz/default`` (``OPAClient.query`` строит ``/v1/data/authz/default``)."
        ),
        examples=["authz/default"],
    )
    casbin_model_path: str | None = Field(
        default=None,
        description=(
            "Путь к RBAC-модели (CONF). Для tenant-aware варианта — "
            "``policies/casbin_model_tenant.conf``."
        ),
        examples=["policies/casbin_model_tenant.conf"],
    )
    casbin_policy_path: str | None = Field(
        default=None,
        description="Путь к policy-store (CSV/DB) для Casbin.",
        examples=["policies/casbin_policies.csv"],
    )


policy_settings = PolicySettings()
"""Глобальный экземпляр настроек policy engines (B-12 fix, cycle 37)."""
