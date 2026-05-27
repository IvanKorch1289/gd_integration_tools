"""Pytest-фикстура: toxiproxy для chaos-сценариев.

Запускает контейнер ``ghcr.io/shopify/toxiproxy:2.9.0`` и предоставляет
:class:`Toxiproxy` контроллер с тремя шорткатами:

* :meth:`add_latency` — toxic ``latency`` (имитация slow);
* :meth:`add_bandwidth` — toxic ``bandwidth=0`` (имитация error);
* :meth:`disable` — ``proxy.enabled=False`` 30s (имитация disconnect).

Если ``testcontainers`` или сам toxiproxy недоступен — fixture
выставляет ``pytest.skip(reason="toxiproxy unavailable")``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest

__all__ = ("Toxiproxy", "ToxiproxyProxy", "toxiproxy")


@dataclass(slots=True)
class ToxiproxyProxy:
    """Один proxy в toxiproxy + контроль toxic'ов."""

    name: str
    listen: str
    upstream: str
    enabled: bool = True


class Toxiproxy:
    """Тонкий клиент к toxiproxy admin API через httpx.

    Не зависит от ``toxiproxy-python`` (упрощает supply-chain)
    — подмножество API достаточно для трёх chaos-сценариев.
    """

    def __init__(self, *, base_url: str) -> None:
        """Запоминает admin URL toxiproxy (``http://host:port``)."""
        import httpx  # noqa: PLC0415

        self._client = httpx.Client(base_url=base_url, timeout=5.0)

    def populate(self, proxies: list[dict[str, Any]]) -> list[ToxiproxyProxy]:
        """Создать proxies батчем через ``POST /populate``."""
        resp = self._client.post("/populate", content=json.dumps(proxies).encode())
        resp.raise_for_status()
        return [ToxiproxyProxy(**p) for p in resp.json().get("proxies", proxies)]

    def add_latency(self, proxy: str, *, latency_ms: int = 5000) -> None:
        """Добавить toxic ``latency`` (имитация slow)."""
        self._client.post(
            f"/proxies/{proxy}/toxics",
            content=json.dumps(
                {
                    "name": "lat",
                    "type": "latency",
                    "stream": "downstream",
                    "attributes": {"latency": latency_ms},
                }
            ).encode(),
        ).raise_for_status()

    def add_bandwidth(self, proxy: str, *, rate_kbps: int = 0) -> None:
        """Добавить toxic ``bandwidth=0`` (имитация error / reset)."""
        self._client.post(
            f"/proxies/{proxy}/toxics",
            content=json.dumps(
                {
                    "name": "bw",
                    "type": "bandwidth",
                    "stream": "downstream",
                    "attributes": {"rate": rate_kbps},
                }
            ).encode(),
        ).raise_for_status()

    def disable(self, proxy: str, *, duration_s: float = 30.0) -> None:
        """Выключить proxy на ``duration_s`` секунд (имитация disconnect)."""
        self._client.post(
            f"/proxies/{proxy}", content=json.dumps({"enabled": False}).encode()
        ).raise_for_status()
        time.sleep(duration_s)
        self._client.post(
            f"/proxies/{proxy}", content=json.dumps({"enabled": True}).encode()
        ).raise_for_status()

    def reset(self) -> None:
        """Сбросить все toxic'и через ``POST /reset``."""
        self._client.post("/reset").raise_for_status()

    def close(self) -> None:
        """Закрыть HTTP-клиент."""
        self._client.close()


@pytest.fixture(scope="session")
def toxiproxy() -> Iterator[Toxiproxy]:
    """Поднимает toxiproxy + отдаёт :class:`Toxiproxy` контроллер."""
    try:
        from testcontainers.core.container import DockerContainer  # noqa: PLC0415
    except ImportError:
        pytest.skip("testcontainers not installed (extra: testkit)")

    container = (
        DockerContainer("ghcr.io/shopify/toxiproxy:2.9.0")
        .with_exposed_ports(8474)
        .with_command("-host=0.0.0.0")
    )
    try:
        container.start()
    except Exception as exc:  # pragma: no cover — Docker недоступен
        pytest.skip(f"toxiproxy unavailable: {exc}")

    host = container.get_container_host_ip()
    port = container.get_exposed_port(8474)
    proxy = Toxiproxy(base_url=f"http://{host}:{port}")
    try:
        yield proxy
    finally:
        proxy.close()
        container.stop()
