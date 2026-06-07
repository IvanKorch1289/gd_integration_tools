"""Тонкий REST-клиент Flagsmith API (Sprint 7 K1 closure).

Назначение:
    Минимальный async httpx-обёртка над Flagsmith Edge API
    (https://docs.flagsmith.com/clients/rest). Lazy-import httpx, чтобы
    не тащить I/O-стек, пока external provider выключен. Используется
    :mod:`src.backend.core.feature_flags.openfeature_provider` через
    OpenFeature SDK при ``FEATURE_FLAG_BACKEND=flagsmith``.

    Реализует только endpoint'ы, востребованные OpenFeature provider'ом:

    - ``GET /flags/`` — environment-default flags (без identity).
    - ``GET /identities/?identifier=<tenant_id>`` — per-identity flags + traits.

    Подробнее: https://docs.flagsmith.com/clients/server-side/python.

feature_flag:
    ``openfeature_flagsmith_backend`` (default-OFF; ENV
    ``FEATURE_FLAG_BACKEND=flagsmith`` переключает на этот клиент).
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger


from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

__all__ = ("FlagsmithClient", "FlagsmithFlag", "FlagsmithUnavailableError")

_logger = get_logger("core.feature_flags.flagsmith_client")
_DEFAULT_API_URL = "https://edge.api.flagsmith.com/api/v1/"
_DEFAULT_TIMEOUT_SECONDS = 2.0


class FlagsmithUnavailableError(RuntimeError):
    """Поднимается, когда Flagsmith REST endpoint недоступен."""


@dataclass(slots=True, frozen=True)
class FlagsmithFlag:
    """Распарсенный flag из Flagsmith API.

    Attributes:
        name: Имя feature-flag (``feature.name``).
        enabled: Включён ли flag (``enabled``).
        value: Полезная нагрузка ``feature_state_value`` (str / int / dict).
    """

    name: str
    enabled: bool
    value: Any


class FlagsmithClient:
    """Async REST-клиент Flagsmith API (минимальный сабсет endpoints).

    Args:
        environment_key: API key окружения Flagsmith
            (``ser.<server_side_key>``). Если None, клиент возвращает
            пустые ответы (graceful degradation).
        api_url: Base URL Flagsmith API (default — edge.api.flagsmith.com).
        timeout_seconds: Таймаут одного запроса; short-by-default чтобы
            не блокировать hot-path (Sprint 7 best-practice).
        http_client: Опциональный pre-created ``httpx.AsyncClient`` (DI для тестов).

    Пример:
        >>> client = FlagsmithClient(environment_key="ser.abc123")
        >>> flags = await client.get_identity_flags(tenant_id="acme-corp")
        >>> for f in flags:
        ...     print(f.name, f.enabled, f.value)
    """

    def __init__(
        self,
        environment_key: str | None = None,
        *,
        api_url: str = _DEFAULT_API_URL,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Инициализирует клиент. HTTP-клиент создаётся lazy."""
        self.environment_key = environment_key
        self.api_url = api_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds
        self._client: httpx.AsyncClient | None = http_client

    async def get_environment_flags(self) -> list[FlagsmithFlag]:
        """Возвращает дефолтные flags окружения (без identity).

        Returns:
            Список [FlagsmithFlag]; пустой при отсутствии environment_key.
        """
        if self.environment_key is None:
            return []
        client = self._get_client()
        try:
            resp = await client.get("flags/")
        except Exception as exc:
            _logger.warning("Flagsmith get_environment_flags failed: %s", exc)
            raise FlagsmithUnavailableError(str(exc)) from exc
        if resp.status_code != 200:
            _logger.warning(
                "Flagsmith /flags/ unexpected status=%s body=%s",
                resp.status_code,
                resp.text[:200],
            )
            return []
        return [_parse_flag(item) for item in resp.json()]

    async def get_identity_flags(
        self, tenant_id: str, traits: dict[str, Any] | None = None
    ) -> list[FlagsmithFlag]:
        """Возвращает flags конкретной identity (tenant) с overrides.

        Args:
            tenant_id: Identity Flagsmith (``identifier`` query-param).
            traits: Опциональные per-identity traits (plan, region и т.п.) —
                в текущей upstream-версии передаются через POST, поэтому
                здесь принимаются для совместимости API, но не отправляются
                (можно расширить при необходимости).

        Returns:
            Список [FlagsmithFlag] для identity.
        """
        if self.environment_key is None:
            return []
        client = self._get_client()
        params: dict[str, str] = {"identifier": tenant_id}
        _ = traits  # traits-aware запрос требует POST; зарезервировано.
        try:
            resp = await client.get("identities/", params=params)
        except Exception as exc:
            _logger.warning("Flagsmith get_identity_flags failed: %s", exc)
            raise FlagsmithUnavailableError(str(exc)) from exc
        if resp.status_code != 200:
            _logger.warning(
                "Flagsmith /identities/ unexpected status=%s body=%s",
                resp.status_code,
                resp.text[:200],
            )
            return []
        payload = resp.json()
        flags_raw = payload.get("flags", []) if isinstance(payload, dict) else []
        return [_parse_flag(item) for item in flags_raw]

    async def aclose(self) -> None:
        """Graceful close внутреннего httpx-клиента (если был создан)."""
        if self._client is None:
            return
        try:
            await self._client.aclose()
        except Exception as _:
            _logger.exception("FlagsmithClient close failed")
        self._client = None

    # ── private ──────────────────────────────────────────────────────────

    def _get_client(self) -> httpx.AsyncClient:
        """Lazy-init HTTP-клиент (через WAF-facade при flag ON).

        WAF Phase-2 (R-V15-5): использует :func:`make_http_client`,
        который под флагом ``waf_outbound_via_facade`` возвращает
        :class:`OutboundHttpClient` с audit + capability check.

        Returns:
            Live HTTP-клиент с заголовком ``X-Environment-Key``.
        """
        if self._client is not None:
            return self._client
        from src.backend.core.net.migration_helper import make_http_client

        self._client = make_http_client(
            base_url=self.api_url,
            headers={"X-Environment-Key": self.environment_key or ""},
            timeout=self.timeout_seconds,
            plugin="core/feature_flags/flagsmith",
        )
        return self._client  # type: ignore[return-value]


def _parse_flag(item: dict[str, Any]) -> FlagsmithFlag:
    """Распаковывает ответ Flagsmith API в [FlagsmithFlag].

    Args:
        item: Сырой dict из ``/flags/`` или ``/identities/?...``.

    Returns:
        [FlagsmithFlag] с name/enabled/value.
    """
    feature = item.get("feature", {}) if isinstance(item, dict) else {}
    return FlagsmithFlag(
        name=str(feature.get("name", "")),
        enabled=bool(item.get("enabled", False)),
        value=item.get("feature_state_value"),
    )
