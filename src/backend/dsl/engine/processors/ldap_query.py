"""DSL-процессор ``ldap_query`` — LDAP search через ldap3.

Wave ``[wave:s5/k3-w3-processor-pack-3]``.

Lazy-import: ``ldap3`` через ``asyncio.to_thread`` (стабильный wheel
для Python 3.14, soft-dep `dsl-extras-3`). Если не
доступен — ``exchange.fail()``.

Контракт DSL::

    .ldap_query(
        server="ldap://corp.local",
        bind_dn="cn=admin,dc=corp,dc=local",
        password="${env.LDAP_PWD}",
        search_base="dc=corp,dc=local",
        search_filter="(objectClass=person)",
        attributes=["cn", "mail"],
        to="body.employees",
    )

Feature flag: ``feature_flags.proc_ldap_query`` (default-OFF).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("LdapQueryProcessor",)


@processor(
    "ldap_query",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "server": {"type": "string"},
            "bind_dn": {"type": "string"},
            "password": {"type": "string"},
            "search_base": {"type": "string"},
            "search_filter": {"type": "string"},
            "attributes": {"type": "array", "items": {"type": "string"}},
            "to": {"type": "string"},
            "use_ssl": {"type": "boolean"},
        },
        "required": ["server", "search_base", "search_filter"],
    },
    capabilities=("net.outbound.ldap:external",),
    meta={"tier": 1, "category": "directory"},
    tags=("ldap", "directory", "auth"),
)
class LdapQueryProcessor(BaseProcessor):
    """Async LDAP search.

    Args:
        server: URL сервера (``ldap://host:389`` или ``ldaps://host:636``).
        bind_dn: DN для bind (anonymous если None).
        password: Пароль bind (None для anonymous).
        search_base: Base DN для search.
        search_filter: LDAP-фильтр (``(objectClass=person)``).
        attributes: Список атрибутов для возврата (None → все).
        to: Куда положить list[dict] результатов.
        use_ssl: Включить LDAPS.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.STATEFUL

    def __init__(
        self,
        server: str,
        search_base: str,
        search_filter: str,
        *,
        bind_dn: str | None = None,
        password: str | None = None,
        attributes: list[str] | None = None,
        to: str = "body.ldap_result",
        use_ssl: bool = False,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"ldap_query:{server}")
        if not server:
            raise ValueError("ldap_query: server must be non-empty")
        if not search_base:
            raise ValueError("ldap_query: search_base must be non-empty")
        if not search_filter:
            raise ValueError("ldap_query: search_filter must be non-empty")
        self._server = server
        self._search_base = search_base
        self._search_filter = search_filter
        self._bind_dn = bind_dn
        self._password = password
        self._attributes = attributes
        self._target = to
        self._use_ssl = use_ssl

    def _apply_target(self, exchange: "Exchange[Any]", value: Any) -> None:
        if self._target.startswith("body."):
            field = self._target[len("body.") :]
            body = exchange.in_message.body
            if not isinstance(body, dict):
                body = {}
                exchange.in_message.body = body  
            body[field] = value
            return
        if self._target.startswith("properties."):
            field = self._target[len("properties.") :]
            exchange.set_property(field, value)
            return
        exchange.set_property(self._target, value)

    def _search_sync(self) -> list[dict[str, Any]]:
        """Sync ldap3 search в worker thread (для use через ``asyncio.to_thread``)."""
        from ldap3 import (  
            ALL_ATTRIBUTES,
            Connection,
            Server,
        )

        srv = Server(self._server, use_ssl=self._use_ssl)
        conn = Connection(
            srv, user=self._bind_dn, password=self._password, auto_bind=True
        )
        try:
            attrs = self._attributes or ALL_ATTRIBUTES
            conn.search(
                search_base=self._search_base,
                search_filter=self._search_filter,
                attributes=attrs,
            )
            entries = []
            for e in conn.entries:
                entry: dict[str, Any] = {"dn": e.entry_dn}
                for attr in (
                    self._attributes if self._attributes else e.entry_attributes
                ):
                    val = getattr(e, attr, None)
                    if val is not None:
                        entry[attr] = (
                            list(val.values) if hasattr(val, "values") else val
                        )
                entries.append(entry)
            return entries
        finally:
            conn.unbind()

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.proc_ldap_query:
                exchange.set_property("ldap_query_status", "skipped")
                return
        except Exception as _:  # noqa: BLE001
            pass

        # Primary path: ldap3 + asyncio.to_thread (стабильный wheel py3.14).
        try:
            entries = await asyncio.to_thread(self._search_sync)
            self._apply_target(exchange, entries)
            return
        except ImportError:
            pass
        except Exception as exc:  # noqa: BLE001
            exchange.fail(f"ldap_query error: {exc}")
            return

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {
            "server": self._server,
            "search_base": self._search_base,
            "search_filter": self._search_filter,
        }
        if self._bind_dn:
            spec["bind_dn"] = self._bind_dn
        if self._password:
            spec["password"] = self._password
        if self._attributes:
            spec["attributes"] = self._attributes
        if self._target != "body.ldap_result":
            spec["to"] = self._target
        if self._use_ssl:
            spec["use_ssl"] = True
        return {"ldap_query": spec}
