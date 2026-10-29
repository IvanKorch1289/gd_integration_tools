"""Инварианты prod/staging-профилей конфигурации (ADR-0371, cycle 172).

Read-only ревью конфигурации (4 агента) зафиксировало, что prod-профиль
унаследовал от ``base.yml`` dev-значения, которые в проде опасны, а staging
не отличался от dev по WAF / watermark / логированию / API-документации.

Модуль фиксирует эти инварианты как исполняемые проверки:

* ``http.ssl_verify=true`` — TLS-сертификаты исходящих запросов проверяются
  (в ``base.yml`` до cycle 172 стояло ``false``, и ни prod, ни staging его
  не переопределяли);
* ``graphql.enable_introspection=false`` — секции ``graphql:`` не было ни в
  одном профиле, дефолт модели ``True``;
* ``vault.addr`` в prod/staging — ``https`` и не loopback (в base — plaintext
  loopback для dev);
* в staging объявлена секция ``features:`` — иначе модельные дефолты
  ``lsp_server_strict=True`` / ``ai_prompt_sweep_strict=True`` дают два
  CRITICAL от ``ConfigValidator``;
* staging закрыт по WAF / watermark / request-body-логированию / Swagger —
  как prod;
* prod имеет prod-тюнинг (workers/threads/лимиты), а не dev-значения;
* в prod выключен локальный SQLite-snapshot (multi-pod: файл на под);
* в prod ``open_webui`` (localhost) исключён из fallback-цепочки AI;
* loopback-хосты в prod/staging — только из явно документированного allowlist'а;
* ``ConfigValidator`` на **merged** base+profile даёт 0 CRITICAL
  (``manage.py validate-profile`` проверяет только overlay-файл);
* в YAML-профилях нет env-плейсхолдеров ``${...}`` — загрузчик их не
  подставляет (ADR-0377);
* WAF-allowlist prod/staging покрывает хосты внешних интеграций
  (ADR-0377) — иначе исходящий запрос блокируется на ровнях
  ``WafBypassError``;
* staging не наследует dev-значения ``base.yml`` (ADR-0377).

Все проверки работают по YAML-файлам профилей (merge — как в
``core.config.config_loader._deep_merge``) и не зависят от env/Vault:
результат определяется только содержимым ``config_profiles/*.yml``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final
from urllib.parse import urlparse

import pytest
import yaml

from src.backend.core.config.base import AppBaseSettings
from src.backend.core.config.config_loader import _deep_merge
from src.backend.core.config.database import DatabaseConnectionSettings
from src.backend.core.config.features import FeatureFlags
from src.backend.core.config.security import SecureSettings
from src.backend.core.config.services.cache import RedisSettings
from src.backend.core.config.settings import Settings
from src.backend.core.config.validator import ConfigSeverity, ConfigValidator
from src.backend.core.config.vault import VaultSettings
from src.backend.core.config.waf import WafSettings
from src.backend.core.net.waf import WafPolicy

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
PROFILES_DIR = REPO_ROOT / "config_profiles"

PROD_LIKE_PROFILES: Final[tuple[str, ...]] = ("prod", "staging")
"""Профили, которые обязаны быть «не как dev» (ADR-0371)."""

_PROFILE_YAML_FILES: Final[tuple[Path, ...]] = tuple(
    sorted(PROFILES_DIR.glob("*.y*ml"))
)
"""Все YAML-файлы профилей (base + overlay'ы + mcp_clients)."""

_EXTERNAL_INTEGRATION_URLS: Final[tuple[tuple[str, str], ...]] = (
    ("skb", "prod_url"),
    ("dadata", "base_url"),
)
"""URL внешних интеграций (клиенты ``services/integrations/**``)."""

_REQUIRED_EXTERNAL_HOSTS: Final[frozenset[str]] = frozenset(
    {"api.skb-techno.ru", "suggestions.dadata.ru"}
)
"""Хосты внешних интеграций, обязательные в WAF-allowlist (ADR-0377)."""

_STAGING_NOT_DEV_PATHS: Final[tuple[str, ...]] = (
    "vault.addr",
    "http.limit_per_host",
    "security.rate_limit",
    "security.request_timeout",
    "snapshot.enabled",
)
"""Пути, где staging не должен совпадать с dev-значением из ``base.yml``."""

_LOOPBACK_MARKERS: Final[tuple[str, ...]] = ("localhost", "127.0.0.1", "::1")
"""Маркеры loopback-хоста в значениях конфигурации."""

_LOOPBACK_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {
        # WAF: loopback-sidecar'ы (clamd/otel) — реальный список хостов
        # без инфраструктуры вывести нельзя (owner-задача, ADR-0371).
        "waf.allow_hosts",
        # ClamAV: демон по умолчанию слушает loopback.
        "waf.clamav_host",
        # prod-drill: админ-доступ только с loopback (SEC_ADMIN_IPS в проде).
        "security.admin_ips",
        # elasticsearch.enabled=false — сервис выключен.
        "elasticsearch.hosts",
        # rag.enabled=false — векторное хранилище выключено.
        "rag.qdrant_url",
        "rag.chroma_host",
        # clickhouse.enabled=false — аналитика выключена.
        "clickhouse.host",
        # MQTT-клиент: брокер в prod не развёрнут (default localhost).
        "mqtt.broker_host",
        # jupyter_hub.enabled=false — интеграция выключена.
        "jupyter_hub.base_url",
        # open_webui: исключён из prod fallback_chain (см. отдельный тест),
        # реальный host — owner-задача.
        "open_webui.base_url",
    }
)
"""Допустимые loopback-хосты в prod/staging (документированы в ADR-0371)."""


class _ProfileSettings(Settings):
    """Корень конфигурации профиля + секция ``features``.

    В базовом :class:`Settings` поля ``features`` нет (feature-флаги живут
    в отдельном singleton'е ``core.config.features.feature_flags``), а
    ``ConfigValidator`` читает именно ``settings.features``. Подкласс
    добавляет поле, чтобы валидатор проверял флаги **этого** профиля,
    а не глобального singleton'а, загруженного при импорте.
    """

    features: FeatureFlags


def _load_yaml(path: Path) -> dict[str, Any]:
    """Читает YAML-файл профиля.

    Args:
        path: Путь к YAML-файлу.

    Returns:
        Разобранный mapping (пустой dict для пустого файла).
    """
    with open(path) as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def _overlay(profile: str) -> dict[str, Any]:
    """Читает overlay-файл профиля (без base).

    Args:
        profile: Имя профиля (``prod``/``staging``).

    Returns:
        Содержимое ``config_profiles/{profile}.yml``.
    """
    return _load_yaml(PROFILES_DIR / f"{profile}.yml")


def _merged(profile: str) -> dict[str, Any]:
    """Сливает ``base.yml`` + ``{profile}.yml`` так же, как это делает прод-код.

    Args:
        profile: Имя профиля (``prod``/``staging``).

    Returns:
        Итоговый конфиг после ``_deep_merge`` из ``config_loader``.
    """
    return _deep_merge(_load_yaml(PROFILES_DIR / "base.yml"), _overlay(profile))


def _construct(model_cls: type[Any], section: dict[str, Any] | None) -> Any:
    """Собирает экземпляр модели конфигурации из YAML-секции.

    Значения не валидируются (``.model_construct``) и env/Vault не читаются —
    проверяется ровно то, что лежит в YAML-файлах профиля.

    Args:
        model_cls: Pydantic-модель настроек.
        section: YAML-секция (может быть пустой).

    Returns:
        Экземпляр модели с заданными значениями и дефолтами модели.
    """
    values = {
        key: value
        for key, value in (section or {}).items()
        if key in model_cls.model_fields
    }
    return model_cls.model_construct(**values)


def _build_profile_settings(profile: str) -> _ProfileSettings:
    """Собирает корневой ``Settings`` профиля из merged YAML.

    Args:
        profile: Имя профиля (``prod``/``staging``).

    Returns:
        Экземпляр настроек, собранный из ``base.yml`` + overlay профиля.
    """
    merged = _merged(profile)
    return _ProfileSettings.model_construct(
        app=_construct(AppBaseSettings, merged.get("app")),
        secure=_construct(SecureSettings, merged.get("security")),
        vault=_construct(VaultSettings, merged.get("vault")),
        database=_construct(DatabaseConnectionSettings, merged.get("database")),
        redis=_construct(RedisSettings, merged.get("redis")),
        features=_construct(FeatureFlags, merged.get("features")),
    )


def _loopback_paths(data: dict[str, Any]) -> list[str]:
    """Собирает dot-path'ы значений, содержащих loopback-хост.

    Args:
        data: Конфигурация профиля (merged).

    Returns:
        Список путей вида ``section.key`` / ``section.key[0]``.
    """
    found: list[str] = []

    def walk(node: Any, path: str) -> None:
        """Рекурсивно обходит конфигурацию и собирает пути loopback-значений."""
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        elif isinstance(node, str):
            lowered = node.lower()
            if any(marker in lowered for marker in _LOOPBACK_MARKERS):
                found.append(path)

    walk(data, "")
    return found


def _is_allowlisted(path: str) -> bool:
    """Проверяет, разрешён ли loopback-хост по allowlist'у.

    Args:
        path: Dot-path значения (``waf.allow_hosts[0]``).

    Returns:
        ``True``, если путь покрыт одной из записей allowlist'а.
    """
    return any(
        path == entry or path.startswith(f"{entry}.") or path.startswith(f"{entry}[")
        for entry in _LOOPBACK_ALLOWLIST
    )


def _value_at(data: dict[str, Any], path: str) -> Any:
    """Возвращает значение по dot-path (``section.key``).

    Args:
        data: Конфигурация профиля (merged).
        path: Dot-path значения.

    Returns:
        Значение по указанному пути.
    """
    node: Any = data
    for part in path.split("."):
        node = node[part]
    return node


def _placeholder_paths(data: dict[str, Any]) -> list[str]:
    """Собирает dot-path'ы строковых значений с env-плейсхолдером ``${...}``.

    Args:
        data: Конфигурация профиля (merged или оверлей).

    Returns:
        Список путей вида ``section.key`` / ``section.key[0]``.
    """
    found: list[str] = []

    def walk(node: Any, path: str) -> None:
        """Рекурсивно обходит конфигурацию и собирает пути плейсхолдеров."""
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        elif isinstance(node, str) and "${" in node:
            found.append(path)

    walk(data, "")
    return found


def _external_integration_urls(merged: dict[str, Any]) -> list[str]:
    """Собирает URL внешних интеграций из merged-конфига.

    Args:
        merged: Слияние ``base.yml`` + overlay профиля.

    Returns:
        Список URL интеграций (``skb``/``dadata``).
    """
    urls: list[str] = []
    for section, key in _EXTERNAL_INTEGRATION_URLS:
        url = (merged.get(section) or {}).get(key)
        if url:
            urls.append(str(url))
    return urls


def _external_integration_hosts(merged: dict[str, Any]) -> set[str]:
    """Собирает хосты внешних интеграций из merged-конфига.

    Args:
        merged: Слияние ``base.yml`` + overlay профиля.

    Returns:
        Множество хостов (lowercase) внешних интеграций.
    """
    hosts: set[str] = set()
    for url in _external_integration_urls(merged):
        host = urlparse(url).hostname
        if host:
            hosts.add(host.lower())
    return hosts


class TestTlsVerification:
    """TLS-сертификаты исходящих запросов проверяются в prod/staging."""

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_ssl_verify_enabled(self, profile: str) -> None:
        """Effective ``http.ssl_verify`` — ``True``."""
        assert _merged(profile)["http"]["ssl_verify"] is True

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_ssl_verify_declared_explicitly(self, profile: str) -> None:
        """Overlay профиля объявляет ``http.ssl_verify`` явно (не наследует)."""
        assert _overlay(profile)["http"]["ssl_verify"] is True


class TestGraphQLIntrospection:
    """GraphQL-интроспекция объявлена выключенной."""

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_introspection_disabled(self, profile: str) -> None:
        """Effective ``graphql.enable_introspection`` — ``False``."""
        assert _merged(profile)["graphql"]["enable_introspection"] is False

    def test_introspection_disabled_in_base(self) -> None:
        """``base.yml`` объявляет ``graphql.enable_introspection=false``."""
        base = _load_yaml(PROFILES_DIR / "base.yml")
        assert base["graphql"]["enable_introspection"] is False

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_introspection_declared_explicitly(self, profile: str) -> None:
        """Overlay профиля объявляет ``graphql.enable_introspection`` явно."""
        overlay = _overlay(profile)
        assert overlay["graphql"]["enable_introspection"] is False


class TestVaultAddress:
    """Vault в prod — не loopback и не plaintext."""

    def test_prod_vault_addr_is_https(self) -> None:
        """Effective ``vault.addr`` в prod — ``https://...``."""
        assert _merged("prod")["vault"]["addr"].startswith("https://")

    def test_prod_vault_addr_not_loopback(self) -> None:
        """Effective ``vault.addr`` в prod — не loopback-хост."""
        addr = _merged("prod")["vault"]["addr"].lower()
        assert "localhost" not in addr
        assert "127.0.0.1" not in addr

    def test_prod_vault_addr_declared_explicitly(self) -> None:
        """Prod объявляет ``vault.addr`` явно (не наследует loopback из base)."""
        assert _overlay("prod")["vault"]["addr"].startswith("https://")

    def test_staging_vault_addr_is_https_not_loopback(self) -> None:
        """Staging больше не наследует loopback-plaintext Vault из base.

        ADR-0377: staging выровнен до prod-уровня — ``https`` и не
        loopback (в ``base.yml`` остаётся dev-дефолт
        ``http://127.0.0.1:8200``).
        """
        addr = _merged("staging")["vault"]["addr"].lower()
        assert addr.startswith("https://")
        assert "localhost" not in addr
        assert "127.0.0.1" not in addr


class TestStagingHardening:
    """Staging не отличается от dev по WAF / watermark / логированию / docs."""

    def test_features_section_declared(self) -> None:
        """Секция ``features:`` объявлена (иначе 2 CRITICAL в валидаторе)."""
        features = _overlay("staging")["features"]
        assert features["lsp_server_strict"] is False
        assert features["ai_prompt_sweep_strict"] is False

    def test_waf_is_strict(self) -> None:
        """``waf.strict=true`` и allowlist непустой."""
        waf = _overlay("staging")["waf"]
        assert waf["strict"] is True
        assert waf["allow_hosts"]

    def test_watermark_is_durable(self) -> None:
        """``watermark.backend=postgres`` (в base — ``memory``)."""
        assert _overlay("staging")["watermark"]["backend"] == "postgres"

    def test_request_body_logging_disabled(self) -> None:
        """``log.log_requests=false`` (в base — ``true``)."""
        assert _overlay("staging")["log"]["log_requests"] is False

    def test_api_docs_disabled(self) -> None:
        """Swagger/ReDoc выключены, как в prod."""
        app = _overlay("staging")["app"]
        assert app["enable_swagger"] is False
        assert app["enable_redoc"] is False


class TestProdTuning:
    """Prod-профиль не наследует dev-значения."""

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_workers_above_single_process(self, profile: str) -> None:
        """В prod/staging больше одного ASGI-процесса (в base — ``workers=1``)."""
        assert _merged(profile)["app"]["workers"] > 1

    def test_workers_and_threads_are_production_level(self) -> None:
        """Воркеров и runtime-потоков больше одного."""
        merged = _merged("prod")
        assert merged["app"]["workers"] >= 2
        assert merged["app"]["granian_runtime_threads"] >= 2

    def test_limits_are_production_level(self) -> None:
        """Лимит соединений на хост и rate-limit выше dev-значений из base."""
        merged = _merged("prod")
        assert merged["http"]["limit_per_host"] >= 50
        assert merged["security"]["rate_limit"] >= 3000
        assert merged["security"]["request_timeout"] >= 30.0

    def test_tuning_declared_explicitly(self) -> None:
        """Prod-тюнинг объявлен в overlay-файле, а не унаследован от base."""
        overlay = _overlay("prod")
        assert overlay["app"]["workers"] >= 2
        assert overlay["app"]["granian_runtime_threads"] >= 2
        assert overlay["http"]["limit_per_host"] >= 50
        assert overlay["security"]["rate_limit"] >= 3000
        assert overlay["security"]["request_timeout"] >= 30.0

    def test_local_snapshot_disabled(self) -> None:
        """Локальный SQLite-snapshot в prod выключен (файл на под)."""
        assert _overlay("prod")["snapshot"]["enabled"] is False

    def test_open_webui_excluded_from_fallback_chain(self) -> None:
        """``open_webui`` (localhost) не участвует в откате AI-провайдера."""
        chain = _merged("prod")["ai_providers"]["fallback_chain"]
        assert "open_webui" not in chain


class TestLoopbackHosts:
    """Loopback-хосты в prod/staging — только из документированного allowlist'а."""

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_no_unexpected_loopback_hosts(self, profile: str) -> None:
        """Нет loopback-значений вне allowlist'а."""
        unexpected = [
            path
            for path in _loopback_paths(_merged(profile))
            if not _is_allowlisted(path)
        ]
        assert unexpected == [], (
            f"профиль {profile}: недокументированные loopback-хосты: {unexpected}"
        )

    def test_allowlist_is_not_empty(self) -> None:
        """Allowlist не пуст — иначе проверка выше вырождается в no-op."""
        assert _LOOPBACK_ALLOWLIST


class TestConfigValidatorOnMergedProfile:
    """``ConfigValidator`` на merged base+profile (а не только на overlay)."""

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_no_critical_violations(self, profile: str) -> None:
        """Ни одного CRITICAL-нарушения на merged-конфиге профиля."""
        merged = _merged(profile)
        violations = ConfigValidator().validate(
            _build_profile_settings(profile), _construct(WafSettings, merged.get("waf"))
        )
        critical = [
            violation.code
            for violation in violations
            if violation.severity == ConfigSeverity.CRITICAL
        ]
        assert critical == [], f"профиль {profile}: CRITICAL-нарушения: {critical}"


class TestNoEnvPlaceholders:
    """В YAML-профилях нет env-плейсхолдеров ``${...}`` (ADR-0377).

    YAML-загрузчик (``core.config.config_loader``) НЕ подставляет
    переменные окружения, а Helm эти файлы не шаблонизирует: плейсхолдер
    попадал в рантайм как есть (``opa_url='${OPA_URL:-http://opa:8181}'`` →
    OPA-клиент получал невалидный URL и все решения становились deny;
    Casbin — ``FileNotFoundError '${CASBIN_MODEL_PATH:-...}'``).
    """

    @pytest.mark.parametrize("path", _PROFILE_YAML_FILES, ids=lambda path: path.name)
    def test_no_placeholder_in_values(self, path: Path) -> None:
        """Ни одно строковое значение профиля не содержит ``${...}``."""
        assert _placeholder_paths(_load_yaml(path)) == [], (
            f"{path.name}: env-плейсхолдеры не поддерживаются YAML-загрузчиком"
        )

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_policy_endpoints_are_literals(self, profile: str) -> None:
        """``policy.opa_url`` — URL, ``casbin_*_path`` — абсолютные пути."""
        policy = _merged(profile)["policy"]
        assert policy["opa_url"].startswith("http")
        assert Path(str(policy["casbin_model_path"])).is_absolute()
        assert Path(str(policy["casbin_policy_path"])).is_absolute()


class TestWafAllowlistCoversIntegrations:
    """WAF-allowlist prod/staging покрывает внешние интеграции (ADR-0377).

    При ``strict=true`` исходящий запрос к хосту вне allowlist'а
    блокируется (``core/net/waf.py`` → ``WafBypassError``). В prod
    запросы к СКБ-Техно и DaData идут напрямую (минуя WAF-шлюз
    ``http.waf_url``) → без этих хостов интеграции не работали.
    """

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_integration_hosts_in_allowlist(self, profile: str) -> None:
        """Хосты интеграций из merged-конфига есть в allowlist."""
        merged = _merged(profile)
        allowed = set(merged["waf"]["allow_hosts"])
        missing = {
            host for host in _external_integration_hosts(merged) if host not in allowed
        }
        assert missing == set(), f"профиль {profile}: хосты вне allowlist: {missing}"

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_required_external_hosts_present(self, profile: str) -> None:
        """Известные внешние хосты интеграций присутствуют в allowlist."""
        allowed = set(_merged(profile)["waf"]["allow_hosts"])
        assert _REQUIRED_EXTERNAL_HOSTS <= allowed, (
            f"профиль {profile}: нет {_REQUIRED_EXTERNAL_HOSTS - allowed}"
        )

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_outbound_request_to_integration_is_allowed(self, profile: str) -> None:
        """Проба из свипа: запрос к интеграции не блокируется WAF-политикой."""
        merged = _merged(profile)
        policy = WafPolicy(
            allow_hosts=frozenset(merged["waf"]["allow_hosts"]),
            deny_hosts=frozenset(merged["waf"]["deny_hosts"]),
            strict=merged["waf"]["strict"],
        )
        blocked = [
            f"{url} ({decision.reason})"
            for url in _external_integration_urls(merged)
            if not (decision := policy.evaluate(url)).allowed
        ]
        assert blocked == [], f"профиль {profile}: WAF блокирует: {blocked}"


class TestStagingIsNotDev:
    """Staging не наследует dev-значения из ``base.yml`` (ADR-0377)."""

    @pytest.mark.parametrize("path", _STAGING_NOT_DEV_PATHS)
    def test_staging_differs_from_dev(self, path: str) -> None:
        """Effective-значение staging отличается от dev-значения."""
        assert _value_at(_merged("staging"), path) != _value_at(_merged("dev"), path), (
            f"staging унаследовал dev-значение {path}"
        )

    def test_staging_limits_are_production_level(self) -> None:
        """Лимиты staging — prod-уровня (не dev-значения из base.yml)."""
        merged = _merged("staging")
        assert merged["http"]["limit_per_host"] >= 50
        assert merged["security"]["rate_limit"] >= 3000
        assert merged["security"]["request_timeout"] >= 30.0

    def test_staging_snapshot_disabled(self) -> None:
        """Локальный SQLite-snapshot в staging выключен (как в prod)."""
        assert _merged("staging")["snapshot"]["enabled"] is False
