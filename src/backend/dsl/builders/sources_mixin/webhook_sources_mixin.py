from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder


class WebhookSourcesMixin:
    """webhook source registration для RouteBuilder. S57 W2 extraction."""

    __slots__ = ()

    @classmethod
    def from_webhook(cls, route_id: str, path: str, **kwargs: Any) -> RouteBuilder:
        """Создаёт маршрут с источником inbound webhook.

        Лениво импортирует :class:`WebhookSource` из
        ``infrastructure.sources.webhook``.
        HMAC-SHA256 верификация включается через ``hmac_secret`` в kwargs.

        Args:
            route_id: Уникальный ID маршрута.
            path: HTTP-путь для inbound webhook (e.g., ``/webhooks/github``).
            **kwargs: Дополнительные параметры для :class:`WebhookSource`
                (hmac_secret, hmac_header, timestamp_header и др.).

        Returns:
            RouteBuilder с ``source`` установленным в ``webhook:<path>``.

        Example::

            route = (
                RouteBuilder.from_webhook(
                    "github.push",
                    path="/webhooks/github",
                    hmac_secret="my-secret",
                    hmac_header="X-Hub-Signature-256",
                )
                .dispatch_action("ci.trigger_build")
                .build()
            )
        """
        import importlib

        mod = importlib.import_module("src.backend.infrastructure.sources.webhook")
        WebhookSource = mod.WebhookSource
        source_instance = WebhookSource(source_id=route_id, path=path, **kwargs)
        builder: RouteBuilder = cls(route_id=route_id, source=f"webhook:{path}")
        object.__setattr__(builder, "_source_instance", source_instance)
        return builder
