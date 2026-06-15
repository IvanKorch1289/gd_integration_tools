from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import grpc

from src.backend.core.config.settings import settings
from src.backend.core.di.providers import get_grpc_logger_provider
from src.backend.entrypoints.grpc.grpc_server.file_stream import (  # S131 W2 (TD-026 cont. full wire-up)
    FileStreamGRPCServicer,
)
from src.backend.entrypoints.grpc.grpc_server.interceptor import AuthInterceptor
from src.backend.entrypoints.grpc.grpc_server.invoker import InvokerGRPCServicer
from src.backend.entrypoints.grpc.grpc_server.order import OrderGRPCServicer
from src.backend.entrypoints.grpc.protobuf.files_pb2_grpc import (  # S131 W2 (TD-026 cont. full wire-up)
    add_FileServiceServicer_to_server,
)
from src.backend.entrypoints.grpc.protobuf.invoker_pb2_grpc import (
    add_InvokerServiceServicer_to_server,
)
from src.backend.entrypoints.grpc.protobuf.orders_pb2_grpc import (
    add_OrderServiceServicer_to_server,
)

grpc_logger = get_grpc_logger_provider()

# S17 K3 W3 (D12): helper для извлечения correlation_id вынесен в
# ``grpc/correlation.py`` (имп. наверху), чтобы тесты могли импортировать
# без protobuf-stubs (top-level ``invoker_pb2`` требует sys.path-magic).


def _load_tls_credentials() -> "grpc.ServerCredentials | None":
    """Загружает TLS-credentials из settings.grpc. None — если TLS отключён.

    Ожидаемые файлы: server_cert.pem, server_key.pem, optional ca_cert.pem
    (для mTLS с проверкой клиентских сертификатов).
    """
    from pathlib import Path

    import grpc

    tls = getattr(settings.grpc, "tls_enabled", False)
    if not tls:
        return None

    cert_path = Path(getattr(settings.grpc, "server_cert_path", ""))
    key_path = Path(getattr(settings.grpc, "server_key_path", ""))
    if not (cert_path.exists() and key_path.exists()):
        raise RuntimeError(
            "gRPC TLS включён, но server_cert_path/server_key_path не найдены."
        )

    server_cert = cert_path.read_bytes()
    server_key = key_path.read_bytes()
    ca_path = Path(getattr(settings.grpc, "ca_cert_path", "") or "")
    ca_cert = ca_path.read_bytes() if ca_path.exists() else None

    require_client_auth = bool(getattr(settings.grpc, "require_client_auth", False))

    return grpc.ssl_server_credentials(
        [(server_key, server_cert)],
        root_certificates=ca_cert,
        require_client_auth=require_client_auth,
    )


async def serve() -> None:
    """Запуск gRPC-сервера с регистрацией всех servicer."""
    from concurrent import futures
    from pathlib import Path

    from grpc.aio import server

    Path(settings.grpc.socket_path).unlink(missing_ok=True)

    interceptors = []
    api_key = getattr(settings.secure, "api_key", None)
    if api_key:
        interceptors.append(AuthInterceptor(expected_key=api_key))

    executor = futures.ThreadPoolExecutor(max_workers=settings.grpc.max_workers)
    grpc_server = server(
        executor,
        options=[
            ("grpc.so_reuseport", 1),
            ("grpc.max_send_message_length", 100 * 1024 * 1024),
            ("grpc.max_receive_message_length", 100 * 1024 * 1024),
        ],
        interceptors=interceptors,
    )

    add_OrderServiceServicer_to_server(OrderGRPCServicer(), grpc_server)
    add_InvokerServiceServicer_to_server(InvokerGRPCServicer(), grpc_server)
    # S131 W2 (TD-026 cont. full wire-up): FileStreamGRPCServicer registered
    # для streaming DownloadFile/UploadFile RPCs (S128 W3 + S131 W2).
    add_FileServiceServicer_to_server(FileStreamGRPCServicer(), grpc_server)

    credentials = _load_tls_credentials()
    if credentials is None:
        # dev/local-only: unix-socket или loopback. Запрещено в prod через
        # валидацию в settings.grpc (ADR-004).
        grpc_server.add_insecure_port(settings.grpc.socket_uri)
        grpc_logger.warning(
            "gRPC сервер запущен без TLS — допустимо только для dev/unix-socket."
        )
    else:
        grpc_server.add_secure_port(settings.grpc.socket_uri, credentials)
        grpc_logger.info(
            "gRPC сервер запущен с TLS (mTLS=%s)",
            bool(getattr(settings.grpc, "require_client_auth", False)),
        )

    await grpc_server.start()
    grpc_logger.info("gRPC-сервер запущен на %s", settings.grpc.socket_uri)

    try:
        await grpc_server.wait_for_termination()
    except KeyboardInterrupt:
        grpc_logger.info("Остановка gRPC-сервера...")
    finally:
        await grpc_server.stop(5)
        executor.shutdown(wait=True)
