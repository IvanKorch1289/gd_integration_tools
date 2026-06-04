"""Integration facade: combines all mixins into IntegrationMixin."""

from __future__ import annotations

from src.backend.dsl.builders.entity import EntityMixin
from src.backend.dsl.builders.integration_core import IntegrationCoreMixin
from src.backend.dsl.builders.notify import NotifyMixin
from src.backend.dsl.builders.security import SecurityMixin
from src.backend.dsl.builders.transport import TransportMixin

__all__ = ("IntegrationMixin",)


class IntegrationMixin(
    TransportMixin, SecurityMixin, EntityMixin, IntegrationCoreMixin, NotifyMixin
):
    """Facade combining all integration mixins."""

    __slots__ = ()
