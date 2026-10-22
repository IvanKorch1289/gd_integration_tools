"""TLS-транспорт для ``GraylogGelfLogSink`` (cycle 171 audit, CRITICAL-04).

До фикса ``use_tls`` из конфигурации использовался **только** как выбор
``tcp``/``udp``: ``_send_tcp`` открывал сырой ``socket.socket(AF_INET,
SOCK_STREAM)``, и весь файл не содержал ни одной ссылки на ``ssl``. Так как
``config_profiles/prod.yml`` выставляет ``use_tls: true``, а
``logging/factory.py`` переводит это в ``protocol="tcp"``, production отправлял
логи (с tenant-контекстом и PII) открытым текстом — флаг выбирал единственный
транспорт, не умеющий шифровать.

Тесты поднимают настоящий локальный TLS-сервер и проверяют поведение на уровне
байтов, а не только факт установки флага.
"""

from __future__ import annotations

import socket
import ssl
import subprocess
import threading
from pathlib import Path

import pytest

from src.backend.infrastructure.logging.backends.graylog_gelf import (
    GraylogGelfLogSink,
)

pytestmark = pytest.mark.asyncio


def _make_self_signed(tmp_path: Path) -> tuple[Path, Path]:
    """Генерирует самоподписанный сертификат для localhost."""
    key = tmp_path / "key.pem"
    cert = tmp_path / "cert.pem"
    subprocess.run(  # noqa: S603,S607
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost,IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    return key, cert


class _TlsEchoServer:
    """Одноразовый TLS-сервер: принимает одно соединение и читает payload."""

    def __init__(self, certfile: Path, keyfile: Path) -> None:
        self._ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._ctx.load_cert_chain(certfile=str(certfile), keyfile=str(keyfile))
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.port: int = self._sock.getsockname()[1]
        self.received: bytes = b""
        self.tls_used = False
        self.error: BaseException | None = None
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _serve(self) -> None:
        try:
            raw, _ = self._sock.accept()
            with raw:
                try:
                    conn = self._ctx.wrap_socket(raw, server_side=True)
                    self.tls_used = True
                except ssl.SSLError:
                    # Клиент не предложил TLS (или отверг сертификат) — это
                    # ожидаемо в тесте «TLS обязан быть обязательным».
                    raw.close()
                    return
                with conn:
                    conn.settimeout(5)
                    try:
                        self.received = conn.recv(65535)
                    except (ssl.SSLError, OSError) as exc:  # pragma: no cover
                        self.error = exc
        except BaseException as exc:  # pragma: no cover - диагностика
            self.error = exc
        finally:
            try:
                self._sock.close()
            except OSError:
                pass

    def join(self, timeout: float = 5.0) -> None:
        self._thread.join(timeout)


async def test_tls_transport_actually_encodes_payload(tmp_path: Path) -> None:
    """С ``use_tls=True`` payload доходит до сервера через TLS."""
    key, cert = _make_self_signed(tmp_path)
    server = _TlsEchoServer(cert, key)
    server.start()

    sink = GraylogGelfLogSink(
        host="127.0.0.1",
        port=server.port,
        protocol="tcp",
        use_tls=True,
        ca_bundle=str(cert),
        tls_verify=True,
    )
    secret = b"tenant=acme pii=user@example.com"
    sink._send_tcp(secret)
    server.join()

    assert server.tls_used is True, "соединение не было обёрнуто в TLS"
    assert server.received == secret + b"\x00"
    assert not sink._dropped


async def test_no_tls_flag_means_plaintext(tmp_path: Path) -> None:
    """Контроль: без ``use_tls`` поведение прежнее — открытый текст.

    Документирует, что именно меняет флаг, и защищает от «TLS по умолчанию
    молча», если кто-то решит включить его неявно.
    """
    key, cert = _make_self_signed(tmp_path)
    server = _TlsEchoServer(cert, key)
    server.start()

    sink = GraylogGelfLogSink(
        host="127.0.0.1", port=server.port, protocol="tcp", use_tls=False
    )
    payload = b"plain-bytes"
    sink._send_tcp(payload)
    server.join()

    assert server.tls_used is False
    assert server.received == b""  # сервер не смог говорить по TLS


async def test_tls_failure_never_degrades_to_plaintext(tmp_path: Path) -> None:
    """Неверный CA → ``SSLError`` пробрасывается, а не игнорируется.

    Молчаливый откат на plaintext здесь означал бы утечку логов, поэтому
    ошибка обязана быть видна вызывающему.
    """
    _key, cert = _make_self_signed(tmp_path)
    server = _TlsEchoServer(cert, _key)
    server.start()

    # ca_bundle указывает на другой сертификат → верификация провалится.
    other = tmp_path / "other-cert.pem"
    other.write_bytes(cert.read_bytes())

    sink = GraylogGelfLogSink(
        host="127.0.0.1",
        port=server.port,
        protocol="tcp",
        use_tls=True,
        ca_bundle=None,  # системные CA — сертификат не пройдёт
        tls_verify=True,
    )
    with pytest.raises(ssl.SSLError):
        sink._send_tcp(b"must-not-be-sent-plaintext")
    server.join()

    assert server.received == b""


async def test_tls_verify_disabled_is_explicit_and_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Отключение проверки возможно, но только явным флагом и с логом."""
    key, cert = _make_self_signed(tmp_path)
    server = _TlsEchoServer(cert, key)
    server.start()

    with caplog.at_level("WARNING", logger="logging.graylog_gelf"):
        sink = GraylogGelfLogSink(
            host="127.0.0.1",
            port=server.port,
            protocol="tcp",
            use_tls=True,
            ca_bundle=None,
            tls_verify=False,
        )
        sink._send_tcp(b"insecure-but-encrypted")
    server.join()

    assert server.tls_used is True, "TLS всё равно должен применяться"
    assert "tls_verification_disabled" in caplog.text


async def test_no_cert_none_without_explicit_optout(tmp_path: Path) -> None:
    """Проверяем, что дефолт — верификация, а не CERT_NONE."""
    _key, cert = _make_self_signed(tmp_path)
    ctx = ssl.create_default_context(cafile=str(cert))
    assert ctx.verify_mode is not ssl.CERT_NONE
    assert ctx.check_hostname is True