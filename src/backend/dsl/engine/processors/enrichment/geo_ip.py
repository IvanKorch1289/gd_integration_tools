from __future__ import annotations
"""S61 W2 — geo_ip.py part of enrichment decomp.

Classes: GeoIpProcessor.

Geo IP enrichment.
"""

import time
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

class GeoIpProcessor(BaseProcessor):
    """GeoIP enrichment via MaxMind GeoLite2.

    Reads IP from header/body field, looks up country/city/ISP,
    stores in exchange property.

    Requires: geoip2 library + GeoLite2-City.mmdb file at path given in ENV
    GEOIP_DB_PATH (default: /data/geoip/GeoLite2-City.mmdb).

    Usage::
        .geoip(ip_field="client_ip", output_property="geo")
    """

    def __init__(
        self,
        *,
        ip_field: str = "client_ip",
        ip_header: str | None = None,
        output_property: str = "geo",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"geoip:{ip_field}")
        self._ip_field = ip_field
        self._ip_header = ip_header
        self._output = output_property
        self._reader: Any = None

    def _get_reader(self) -> Any:
        if self._reader is None:
            import os

            try:
                import geoip2.database

                path = os.environ.get("GEOIP_DB_PATH", "/data/geoip/GeoLite2-City.mmdb")
                self._reader = geoip2.database.Reader(path)
            except (ImportError, FileNotFoundError, OSError) as exc:
                logger.debug("GeoIP reader unavailable: %s", exc)
                self._reader = False
        return self._reader

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
        ip = None
        if self._ip_header:
            ip = exchange.in_message.headers.get(self._ip_header)
        if not ip:
            body = exchange.in_message.body
            if isinstance(body, dict):
                ip = body.get(self._ip_field)
        if not ip:
            exchange.set_property(self._output, None)
            return
        reader = self._get_reader()
        if not reader:
            exchange.set_property(
                self._output, {"ip": ip, "error": "geoip_unavailable"}
            )
            return
        try:
            record = reader.city(ip)
            exchange.set_property(
                self._output,
                {
                    "ip": ip,
                    "country": record.country.iso_code,
                    "country_name": record.country.name,
                    "city": record.city.name,
                    "latitude": float(record.location.latitude)
                    if record.location.latitude
                    else None,
                    "longitude": float(record.location.longitude)
                    if record.location.longitude
                    else None,
                    "timezone": record.location.time_zone,
                },
            )
        except Exception as exc:
            exchange.set_property(self._output, {"ip": ip, "error": str(exc)})

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict (для YAML/JSON spec). Returns None для non-serializable state."""
        spec: dict[str, Any] = {}
        if self._ip_field != "client_ip":
            spec["ip_field"] = self._ip_field
        if self._ip_header is not None:
            spec["ip_header"] = self._ip_header
        if self._output != "geo":
            spec["output_property"] = self._output
        return {"geoip": spec}

