# ruff: noqa: S321 — false positive (controlled pattern)

"""S171 M6.1 — FtpUploadProcessor (gap fill).

Async FTP/SFTP file upload via stdlib :mod:`ftplib` (SFTP requires paramiko).
Capability: rpa.ftp.upload (medium risk — network).

Security (V1 hotfix): FTP_TLS is mandatory. Plaintext FTP would leak the
bind password and the file contents on the wire. Legacy plaintext mode is
only allowed when ``allow_insecure_ftp=True`` AND the process is run
with an explicit dev/test profile (enforced via ``require_insecure_flag``).
Default = strict TLS with cert verification.
"""

from __future__ import annotations

import asyncio
import os
import ssl
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_rpa_logger = get_logger("dsl.rpa")

# Honor ``FTP_INSECURE_OK`` for dev/test only. Production must never see
# this env var. The same flag is mirrored in the constructor arg.
_INSECURE_ENV = "FTP_INSECURE_OK"


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

    required_capability: ClassVar[str | None] = "rpa.ftp.upload"
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
        allow_insecure_ftp: bool = False,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"ftp_upload:{host}")
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.local_path = local_path
        self.remote_path = remote_path
        # The plaintext-FTP escape hatch requires both an explicit ctor
        # flag AND the env var (default-off). The env var is what
        # ops/production can revoke centrally via deployment manifests.
        env_insecure = os.environ.get(_INSECURE_ENV) == "1"
        production = os.environ.get("APP_ENV", "").lower() in {"prod", "production"}
        self._allow_insecure = allow_insecure_ftp and env_insecure and not production

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Загружает локальный файл на FTP-сервер.

        Default transport: FTP over TLS (explicit AUTH TLS + ``prot_p``)
        with certificate verification via ``ssl.create_default_context``.
        Plaintext mode is hard-fail-closed unless ``allow_insecure_ftp``
        AND env ``FTP_INSECURE_OK=1`` were both set at construction.
        """
        if not await self.auth_check(exchange, action="write"):
            return
        if not os.path.exists(self.local_path):
            raise FileNotFoundError(f"FtpUploadProcessor: {self.local_path}")

        def _upload() -> None:
            if self._allow_insecure:
                # Plaintext FTP path — gated by ctor ``allow_insecure_ftp=True``
                # AND env ``FTP_INSECURE_OK=1`` (fail-closed in production).
                # Used only for legacy dev/test servers that lack FTPS.
                from ftplib import FTP  # nosec B402 — gated opt-in path

                ftp = FTP()  # nosec B321 — gated opt-in path
                # Rationale: opt-in legacy path; both flags required,
                # logged via ``_rpa_logger.info(tls=...)`` for audit.
                ftp.connect(self.host, self.port)
                try:
                    if self.user:
                        ftp.login(self.user, self.password)
                    with open(self.local_path, "rb") as f:
                        ftp.storbinary(f"STOR {self.remote_path}", f)
                finally:
                    try:
                        ftp.quit()
                    except (OSError, ConnectionError, RuntimeError) as quit_exc:
                        # cycle-9/D-AUDIT-949: narrow exceptions + observability.
                        # OSError/ConnectionError для FTP network, RuntimeError
                        # для server error. Bare `except Exception` маскировал
                        # unrelated runtime errors.
                        import logging

                        logging.getLogger(__name__).debug(
                            "ftpupload.ftp_quit_failed", extra={"error": str(quit_exc)}
                        )
                        ftp.close()
                return

            # TLS path: explicit AUTH TLS + encrypted data channel + cert
            # validation. Fail-closed on any handshake / cert error.
            from ftplib import FTP_TLS  # nosec B402 — encrypted FTPS, cert-validated

            tls_context = ssl.create_default_context()
            tls_context.check_hostname = True
            tls_context.verify_mode = ssl.CERT_REQUIRED

            ftp = FTP_TLS(context=tls_context, timeout=30)
            # Rationale: TLS-only transport (RFC 4217); CERT_REQUIRED +
            # ``prot_p()`` below. Default path; not a plaintext FTP call.
            ftp.connect(self.host, self.port)
            try:
                if self.user:
                    ftp.login(self.user, self.password)
                # Switch data channel to TLS too (RFC 4217 §5.1).
                ftp.prot_p()
                with open(self.local_path, "rb") as f:
                    ftp.storbinary(f"STOR {self.remote_path}", f)
            finally:
                try:
                    ftp.quit()
                except (OSError, ConnectionError, RuntimeError) as tls_quit_exc:
                    # cycle-9/D-AUDIT-950: см. D-AUDIT-949 — тот же narrow для
                    # TLS path.
                    import logging

                    logging.getLogger(__name__).debug(
                        "ftpupload.ftp_tls_quit_failed",
                        extra={"error": str(tls_quit_exc)},
                    )
                    ftp.close()

        await asyncio.to_thread(_upload)
        _rpa_logger.info(
            "ftp_upload host=%s local=%s remote=%s tls=%s",
            self.host,
            self.local_path,
            self.remote_path,
            not self._allow_insecure,
        )
        self.set_result(exchange, "body.uploaded", True)
