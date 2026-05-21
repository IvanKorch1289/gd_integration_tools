"""Sprint 6 K2 — Granian RSGI production tuning конфигурация.

Назначение:
    Декларативная Pydantic-settings конфигурация для запуска Granian в
    production (ADR-0059). Используется через :mod:`tools.granian_runner`.

Ключевые поля:

* :attr:`workers` — число воркеров (auto = ``os.cpu_count()``, минимум 2).
* :attr:`blocking_threads` — размер blocking thread pool (auto / int).
* :attr:`loop` — event-loop backend (uvloop / asyncio).
* :attr:`interface` — ``rsgi`` (Sprint 6 K2 default-ON через feature-flag)
  или ``asgi``.
* :attr:`http` — HTTP-режим (auto / 1 / 2).
* :attr:`log_level` — уровень логирования.

Feature-flag: ``granian_rsgi_mode_enabled`` (default-OFF). При выключенном
флаге :attr:`interface` принудительно фиксируется на ``asgi`` независимо
от значения в settings.

Использование::

    from src.backend.core.scaling.granian_tuning import granian_tuning

    cmd = granian_tuning.build_cli_command(
        app="src.main:app", host="0.0.0.0", port=8000,
    )
"""

from __future__ import annotations

import os
from typing import ClassVar, Literal

from pydantic import Field, computed_field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("GranianTuning", "granian_tuning")


class GranianTuning(BaseSettingsWithLoader):
    """Production-tuning параметры запуска Granian.

    Все поля имеют sane defaults; конкретные значения переопределяются
    через ENV (префикс ``GRANIAN_``) или ``config_profiles/<profile>.yml``.

    See Also:
        :doc:`/docs/adr/0059-granian-rsgi-production` — ADR-0059.
    """

    yaml_group: ClassVar[str] = "granian"
    model_config = SettingsConfigDict(
        env_prefix="GRANIAN_", extra="ignore", validate_default=True
    )

    workers: int | Literal["auto"] = Field(
        default="auto",
        title="Число воркеров",
        description=(
            "Number of worker processes. 'auto' = os.cpu_count() с min=2. "
            "Перекрывается через ENV GRANIAN_WORKERS."
        ),
    )

    max_workers: int = Field(
        default=16,
        title="Максимум воркеров",
        description="Верхняя граница для auto-режима (защита от oversubscribe).",
        ge=1,
    )

    blocking_threads: int | Literal["auto"] = Field(
        default="auto",
        title="Blocking thread pool",
        description=(
            "Размер thread-pool для блокирующих операций. 'auto' = NCPU*4. "
            "Перекрывается через ENV GRANIAN_BLOCKING_THREADS."
        ),
    )

    loop: Literal["uvloop", "asyncio"] = Field(
        default="uvloop",
        title="Event-loop backend",
        description=(
            "uvloop рекомендован для Linux/macOS; asyncio — fallback (Windows)."
        ),
    )

    interface: Literal["rsgi", "asgi"] = Field(
        default="rsgi",
        title="Granian interface mode",
        description=(
            "rsgi — нативный Granian (быстрее); asgi — совместимость. "
            "Принудительно asgi если feature_flag granian_rsgi_mode_enabled=False."
        ),
    )

    http: Literal["auto", "1", "2"] = Field(
        default="auto",
        title="HTTP-режим",
        description="auto / 1 (HTTP/1.1 only) / 2 (HTTP/2 only).",
    )

    log_level: Literal["debug", "info", "warning", "error"] = Field(
        default="info",
        title="Уровень логирования",
        description="Granian internal log-level.",
    )

    access_log: bool = Field(
        default=True,
        title="Access log",
        description="Включить access-log (через structlog).",
    )

    backlog: int = Field(
        default=2048,
        title="TCP backlog",
        description="TCP listen backlog (default 2048 для production).",
        ge=128,
    )

    @computed_field(description="Резолвленное число воркеров")
    def resolved_workers(self) -> int:
        """Возвращает фактическое число воркеров.

        Если ``workers='auto'`` — использует ``os.cpu_count()`` с
        ограничением ``max(2, min(value, max_workers))``.
        """
        if self.workers == "auto":
            ncpu = os.cpu_count() or 2
            return max(2, min(ncpu, self.max_workers))
        return int(self.workers)

    @computed_field(description="Резолвленный blocking thread pool")
    def resolved_blocking_threads(self) -> int:
        """Возвращает фактический размер blocking-pool.

        Если ``blocking_threads='auto'`` — использует ``resolved_workers * 4``.
        """
        if self.blocking_threads == "auto":
            return self.resolved_workers * 4
        return int(self.blocking_threads)

    @computed_field(description="Фактический interface с учётом feature-flag")
    def resolved_interface(self) -> str:
        """Возвращает фактический Granian interface.

        Если ``feature_flags.granian_rsgi_mode_enabled=False`` — принудительно
        возвращает ``"asgi"`` независимо от значения :attr:`interface`.

        Returns:
            str: ``"rsgi"`` или ``"asgi"``.
        """
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.granian_rsgi_mode_enabled:
                return "asgi"
        except Exception:  # noqa: BLE001
            return "asgi"
        return self.interface

    def build_cli_command(
        self,
        *,
        app: str,
        host: str = "0.0.0.0",
        port: int = 8000,
        granian_cmd: str = "granian",
    ) -> list[str]:
        """Сформировать CLI-команду для запуска Granian.

        Args:
            app: ASGI/RSGI приложение в формате ``module:attr``
                (например, ``src.main:app``).
            host: Bind host (default 0.0.0.0).
            port: Bind port (default 8000).
            granian_cmd: Команда granian (default ``granian``).

        Returns:
            Список аргументов для ``subprocess.run``.
        """
        cmd = [
            granian_cmd,
            "--interface",
            self.resolved_interface,
            "--host",
            host,
            "--port",
            str(port),
            "--workers",
            str(self.resolved_workers),
            "--loop",
            self.loop,
            "--http",
            self.http,
            "--log-level",
            self.log_level,
            "--backlog",
            str(self.backlog),
        ]
        if self.access_log:
            cmd.append("--access-log")
        # blocking-threads — Granian флаг --threads
        cmd.extend(["--threads", str(self.resolved_blocking_threads)])
        cmd.append(app)
        return cmd


granian_tuning = GranianTuning()
"""Глобальный singleton — настройки Granian production-tuning."""
