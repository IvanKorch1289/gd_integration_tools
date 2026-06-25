"""S171 M6.1 — FtpUploadProcessor (gap fill).

Async FTP/SFTP file upload via stdlib :mod:`ftplib` (SFTP requires paramiko).
Capability: rpa.ftp.upload (medium risk — network).
"""
from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_rpa_logger = get_logger("dsl.rpa")


class FtpUploadProcessor(BaseProcessor):
    """Upload local file → FTP server.

    Args:
        host: FTP host.
        port: FTP port (default 21).
        user: Username.
        password: Password.
        local_path: Source file.
        remote_path: Destination path на FTP.
    """

    required_capability: str | None = "rpa.ftp.upload"
    audit_event: str | None = "rpa.ftp.upload"

    def __init__(
        self,
        *,
        host: str,
        port: int = 21,
        user: str = "",
        password: str = "",
        local_path: str,
        remote_path: str,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"ftp_upload:{host}")
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.local_path = local_path
        self.remote_path = remote_path

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        if not os.path.exists(self.local_path):
            raise FileNotFoundError(f"FtpUploadProcessor: {self.local_path}")

        def _upload() -> None:
            from ftplib import FTP

            ftp = FTP()
            ftp.connect(self.host, self.port)
            try:
                if self.user:
                    ftp.login(self.user, self.password)
                with open(self.local_path, "rb") as f:
                    ftp.storbinary(f"STOR {self.remote_path}", f)
            finally:
                try:
                    ftp.quit()
                except Exception:
                    ftp.close()

        await asyncio.to_thread(_upload)
        _rpa_logger.info(
            "ftp_upload host=%s local=%s remote=%s",
            self.host, self.local_path, self.remote_path,
        )
        exchange.in_message.body["uploaded"] = True
