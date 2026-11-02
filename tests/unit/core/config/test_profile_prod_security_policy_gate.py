"""ADR-0403: прод-валидатор — HS256 без секрета и fallback на localhost.

Два инварианта, которые до ADR-0403 никто не проверял
(``manage.py validate-profile prod`` был «зелёным»):

1. **Симметричный JWT-алгоритм без гарантированного секрета.**
   ``security.algorithm: HS256`` в prod требует, чтобы секрет откуда-то
   приходил: YAML (``security.secret_key``), env (``SEC_SECRET_KEY``) или
   Vault (``vault.enabled`` + ``addr`` + ``secret_path``). Если ни одного
   источника нет — подпись токенов не обеспечена → CRITICAL.
   Политика алгоритма (HS256 vs RS256) валидатор НЕ меняет — только
   сообщает.

2. **Fallback-цепочка AI с недоступным в prod хостом.**
   ``ai_providers.fallback_chain`` в prod не должен содержать провайдера,
   чей ``base_url`` указывает на loopback (``localhost`` / ``127.0.0.1`` /
   ``::1``): молчаливый откат на локальный инференс в проде — тихая
   деградация. Состав цепочки валидатор НЕ меняет — только сообщает.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from src.backend.core.config.validator import ConfigSeverity
from src.backend.core.config.validator.profile_merge import validate_profile_config

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
PROFILES_DIR = REPO_ROOT / "config_profiles"

JWT_VIOLATION_CODE = "security.jwt_symmetric_algorithm_without_secret"
FALLBACK_VIOLATION_CODE = "ai_providers.fallback_chain_localhost"


def _profiles_dir(tmp_path: Path) -> Path:
    """Копия репозиторных профилей во временный каталог.

    Args:
        tmp_path: Временный каталог pytest.

    Returns:
        Путь к каталогу профилей (``base.yml`` + ``prod.yml``).

    """
    directory = tmp_path / "config_profiles"
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("base.yml", "prod.yml"):
        (directory / name).write_text(
            (PROFILES_DIR / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    return directory


def _patch_profile(directory: Path, section: str, values: dict[str, Any]) -> None:
    """Изменить секцию профиля ``prod.yml`` в подготовленном каталоге.

    Секция обновляется по ключам (остальные ключи секции сохраняются) —
    иначе merged-конфиг теряет обязательные поля (``admin_ips`` и т.п.)
    и валидатор сообщает ``profile.incomplete`` вместо проверки инварианта.

    Args:
        directory: Каталог профилей.
        section: Имя YAML-секции верхнего уровня.
        values: Значения секции (обновляются по ключам).

    """
    path = directory / "prod.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    current = data.get(section)
    merged_section = dict(current) if isinstance(current, dict) else {}
    merged_section.update(values)
    data[section] = merged_section
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def _critical_codes(violations: tuple[Any, ...]) -> list[str]:
    """Коды CRITICAL-нарушений.

    Args:
        violations: Кортеж нарушений валидатора.

    Returns:
        Список кодов CRITICAL-нарушений.

    """
    return [
        violation.code
        for violation in violations
        if violation.severity == ConfigSeverity.CRITICAL
    ]


def test_repo_prod_profile_has_no_critical_violations() -> None:
    """Штатный prod-профиль: CRITICAL-нарушений нет (секрет — из Vault)."""
    violations = validate_profile_config("prod")

    assert _critical_codes(violations) == [], (
        f"prod-профиль: CRITICAL-нарушения: {_critical_codes(violations)}"
    )


def test_symmetric_algorithm_without_any_secret_source_is_critical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HS256 без YAML/env/Vault-секрета в prod — CRITICAL."""
    monkeypatch.delenv("SEC_SECRET_KEY", raising=False)
    profiles = _profiles_dir(tmp_path)
    _patch_profile(profiles, "security", {"algorithm": "HS256"})
    _patch_profile(profiles, "vault", {"enabled": False})

    violations = validate_profile_config("prod", profiles)

    assert JWT_VIOLATION_CODE in _critical_codes(violations), (
        f"ожидался {JWT_VIOLATION_CODE}, получено {_critical_codes(violations)}"
    )


def test_asymmetric_algorithm_needs_no_secret_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RS256 — асимметричный: секрет не требуется, нарушения нет."""
    monkeypatch.delenv("SEC_SECRET_KEY", raising=False)
    profiles = _profiles_dir(tmp_path)
    _patch_profile(profiles, "security", {"algorithm": "RS256"})
    _patch_profile(profiles, "vault", {"enabled": False})

    violations = validate_profile_config("prod", profiles)

    assert JWT_VIOLATION_CODE not in _critical_codes(violations)


def test_secret_in_yaml_is_a_valid_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Секрет в YAML профиля — гарантированный источник."""
    monkeypatch.delenv("SEC_SECRET_KEY", raising=False)
    profiles = _profiles_dir(tmp_path)
    _patch_profile(profiles, "security", {"algorithm": "HS256", "secret_key": "x" * 40})
    _patch_profile(profiles, "vault", {"enabled": False})

    violations = validate_profile_config("prod", profiles)

    assert JWT_VIOLATION_CODE not in _critical_codes(violations)


def test_secret_in_env_is_a_valid_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``SEC_SECRET_KEY`` в окружении — гарантированный источник."""
    monkeypatch.setenv("SEC_SECRET_KEY", "y" * 40)
    profiles = _profiles_dir(tmp_path)
    _patch_profile(profiles, "security", {"algorithm": "HS256"})
    _patch_profile(profiles, "vault", {"enabled": False})

    violations = validate_profile_config("prod", profiles)

    assert JWT_VIOLATION_CODE not in _critical_codes(violations)


def test_localhost_provider_in_fallback_chain_is_critical(tmp_path: Path) -> None:
    """``open_webui`` (localhost:3000) в fallback-цепочке prod — CRITICAL."""
    profiles = _profiles_dir(tmp_path)
    _patch_profile(
        profiles,
        "ai_providers",
        {"fallback_chain": ["perplexity", "open_webui", "openai"]},
    )
    # ADR-0412: дефолтный endpoint OpenWebUI — service-DNS (``open-webui``),
    # поэтому loopback-случай проверяется явно (фикстура, а не дефолт).
    _patch_profile(profiles, "open_webui", {"base_url": "http://localhost:3000"})

    violations = validate_profile_config("prod", profiles)

    assert FALLBACK_VIOLATION_CODE in _critical_codes(violations), (
        f"ожидался {FALLBACK_VIOLATION_CODE}, получено {_critical_codes(violations)}"
    )


def test_prod_fallback_chain_without_localhost_is_allowed(tmp_path: Path) -> None:
    """Fallback-цепочка без loopback-хостов — нарушений нет."""
    profiles = _profiles_dir(tmp_path)
    _patch_profile(
        profiles,
        "ai_providers",
        {"fallback_chain": ["perplexity", "huggingface", "openai"]},
    )

    violations = validate_profile_config("prod", profiles)

    assert FALLBACK_VIOLATION_CODE not in _critical_codes(violations)


def test_dev_profile_is_not_affected(tmp_path: Path) -> None:
    """В dev оба инварианта не проверяются (dev-профиль — не prod)."""
    profiles = _profiles_dir(tmp_path)
    (profiles / "dev.yml").write_text(
        yaml.safe_dump(
            {
                "app": {"environment": "development"},
                "security": {"algorithm": "HS256"},
                "vault": {"enabled": False},
                "ai_providers": {"fallback_chain": ["perplexity", "open_webui"]},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    violations = validate_profile_config("dev", profiles)

    codes = _critical_codes(violations)
    assert JWT_VIOLATION_CODE not in codes
    assert FALLBACK_VIOLATION_CODE not in codes
