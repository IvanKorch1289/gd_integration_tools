"""Per-route timeout spec (S18 W6, P0 Gateway-centralization gap).

Назначение:
    Унифицированная модель ``RouteTimeoutSpec`` для per-route таймаутов.
    Используется в двух местах:

    * :class:`services.routes.manifest_toml.RouteManifest.timeout` —
      загружается из ``route.toml::[timeout]``;
    * :class:`dsl.builders.policy_mixin.PolicyChain.timeout` —
      Python fluent API ``.policy.timeout(connect=..., read=...,
      write=..., total=...)``.

    Размещён в :mod:`core.utils` (не в ``services/`` и не в ``dsl/``),
    потому что dataclass должны импортировать оба слоя
    (services/routes для manifest и dsl/builders для DSL builder),
    но между собой они напрямую не связаны.

Семантика:
    * **connect / read / write** — outbound httpx-таймауты (передаются в
      httpx-клиенты при outbound-вызовах из pipeline). Middleware
      (:class:`entrypoints.middlewares.timeout.TimeoutMiddleware`) их
      **не** использует.
    * **total** — общий бюджет на обработку inbound-запроса.
      Используется TimeoutMiddleware для cap'а; fallback на
      :class:`settings.secure.request_timeout`.

    Все 4 поля опциональны. ``None`` означает "fallback на global default".
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ("RouteTimeoutSpec",)


@dataclass(frozen=True, slots=True)
class RouteTimeoutSpec:
    """Per-route timeout configuration (S18 W6, S-Gateway-centralization).

    Attributes:
        connect: httpx connect-timeout (для outbound calls в pipeline);
            ``None`` → дефолт httpx-клиента.
        read: httpx read-timeout (для outbound calls); ``None`` → дефолт.
        write: httpx write-timeout (для outbound calls); ``None`` → дефолт.
        total: Общий бюджет обработки inbound-запроса в секундах.
            Используется :class:`TimeoutMiddleware`. ``None`` →
            ``settings.secure.request_timeout`` (global fallback).

    Notes:
        Frozen dataclass — безопасно использовать в pydantic-моделях
        (RouteManifest) и DSL builders без риска мутации.
        ``slots=True`` снижает memory overhead для большого числа routes.
    """

    connect: float | None = None
    read: float | None = None
    write: float | None = None
    total: float | None = None
