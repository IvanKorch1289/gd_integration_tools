"""DSL-процессор ``geo`` — геокодинг и distance через geopy (sync via thread).

Wave ``[wave:s5/k3-w3-processor-pack-3]``.

Использует библиотеку ``geopy`` (lazy). Поддерживает 3 операции:

* ``geocode`` — address → (lat, lon);
* ``reverse`` — (lat, lon) → address;
* ``distance`` — пара точек → расстояние (км) через WGS-84 geodesic.

Контракт DSL::

    .geo(mode="geocode", address="Moscow", to="body.coords")
    .geo(mode="distance", point_a=(55.75, 37.62), point_b=(59.93, 30.32), to="body.km")

Feature flag: ``feature_flags.proc_geo`` (default-OFF).
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


__all__ = ("GeoProcessor",)


_ALLOWED_MODES = frozenset({"geocode", "reverse", "distance"})


@processor(
    "geo",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": sorted(_ALLOWED_MODES)},
            "address": {"type": "string"},
            "point_a": {"type": "array"},
            "point_b": {"type": "array"},
            "to": {"type": "string"},
            "user_agent": {"type": "string"},
        },
        "required": ["mode"],
    },
    capabilities=("net.outbound.nominatim:external",),
    meta={"tier": 1, "category": "transform"},
    tags=("geo", "geopy", "geocoding", "distance"),
)
class GeoProcessor(BaseProcessor):
    """Геокодинг / reverse / distance через geopy.

    Args:
        mode: ``geocode`` (address→coords) / ``reverse`` (coords→address) /
            ``distance`` (pair of coords → km).
        address: Адрес для ``geocode`` (или ``reverse`` если point_a задан).
        point_a: Координаты (lat, lon) первой точки.
        point_b: Координаты (lat, lon) второй точки (только для distance).
        to: Куда положить результат.
        user_agent: User-Agent для Nominatim (best-practice: уникальный).
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.STATEFUL

    def __init__(
        self,
        mode: str,
        *,
        address: str | None = None,
        point_a: tuple[float, float] | list[float] | None = None,
        point_b: tuple[float, float] | list[float] | None = None,
        to: str = "body.geo_result",
        user_agent: str = "gd-integration-tools",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"geo:{mode}")
        if mode not in _ALLOWED_MODES:
            raise ValueError(
                f"geo: mode must be one of {sorted(_ALLOWED_MODES)}, got {mode!r}"
            )
        self._mode = mode
        self._address = address
        self._point_a = tuple(point_a) if point_a else None
        self._point_b = tuple(point_b) if point_b else None
        self._target = to
        self._user_agent = user_agent

    def _apply_target(self, exchange: "Exchange[Any]", value: Any) -> None:
        if self._target.startswith("body."):
            field = self._target[len("body.") :]
            body = exchange.in_message.body
            if not isinstance(body, dict):
                body = {}
                exchange.in_message.body = body  # type: ignore[assignment]
            body[field] = value
            return
        if self._target.startswith("properties."):
            field = self._target[len("properties.") :]
            exchange.set_property(field, value)
            return
        exchange.set_property(self._target, value)

    def _exec_sync(self) -> Any:
        from geopy.distance import geodesic  # type: ignore[import-not-found]
        from geopy.geocoders import Nominatim  # type: ignore[import-not-found]

        match self._mode:
            case "geocode":
                if not self._address:
                    raise ValueError("geo geocode: address required")
                geocoder = Nominatim(user_agent=self._user_agent)
                loc = geocoder.geocode(self._address, timeout=10)
                if loc is None:
                    return None
                return {
                    "latitude": loc.latitude,
                    "longitude": loc.longitude,
                    "address": loc.address,
                }
            case "reverse":
                if not self._point_a:
                    raise ValueError("geo reverse: point_a required")
                geocoder = Nominatim(user_agent=self._user_agent)
                loc = geocoder.reverse(self._point_a, timeout=10)
                if loc is None:
                    return None
                return {"address": loc.address, "raw": loc.raw}
            case "distance":
                if not self._point_a or not self._point_b:
                    raise ValueError("geo distance: point_a + point_b required")
                d = geodesic(self._point_a, self._point_b)
                return {"km": d.km, "meters": d.m, "miles": d.miles}
            case _:
                raise ValueError(f"Unsupported mode {self._mode!r}")

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.proc_geo:
                exchange.set_property("geo_status", "skipped")
                return
        except Exception as _:  # noqa: BLE001
            pass

        try:
            result = await asyncio.to_thread(self._exec_sync)
        except ImportError as exc:
            exchange.fail(f"geo: geopy not available: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            exchange.fail(f"geo error: {exc}")
            return

        self._apply_target(exchange, result)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"mode": self._mode}
        if self._address:
            spec["address"] = self._address
        if self._point_a:
            spec["point_a"] = list(self._point_a)
        if self._point_b:
            spec["point_b"] = list(self._point_b)
        if self._target != "body.geo_result":
            spec["to"] = self._target
        if self._user_agent != "gd-integration-tools":
            spec["user_agent"] = self._user_agent
        return {"geo": spec}
