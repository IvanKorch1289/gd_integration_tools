"""gRPC server package (S65 W3 decomp from grpc_server.py 480 LOC).

3 servicers + 1 interceptor + 3 funcs → 5 files (per-concern):
- ``base.py``: BaseGRPCServicer (abstract base)
- ``order.py``: OrderGRPCServicer
- ``invoker.py``: InvokerGRPCServicer
- ``interceptor.py``: AuthInterceptor
- ``server.py``: 3 top-level server funcs

Backward-compat: ``from src.backend.entrypoints.grpc.grpc_server import OrderGRPCServicer`` works.
"""

from __future__ import annotations

from src.backend.entrypoints.grpc.grpc_server._safe_error import (
    _safe_error,  # S65 W3: top-level func re-export
)
from src.backend.entrypoints.grpc.grpc_server.base import (
    BaseGRPCServicer,  # S65 W3: re-export
)
from src.backend.entrypoints.grpc.grpc_server.interceptor import (
    AuthInterceptor,  # S65 W3: re-export
)
from src.backend.entrypoints.grpc.grpc_server.invoker import (
    InvokerGRPCServicer,  # S65 W3: re-export
)
from src.backend.entrypoints.grpc.grpc_server.order import (
    OrderGRPCServicer,  # S65 W3: re-export
)
from src.backend.entrypoints.grpc.grpc_server.server import (
    _load_tls_credentials,  # S65 W3: top-level func re-export
    serve,  # S65 W3: top-level func re-export
)

__all__ = (
    "BaseGRPCServicer",
    "OrderGRPCServicer",
    "InvokerGRPCServicer",
    "AuthInterceptor",
    "_safe_error",
    "_load_tls_credentials",
    "serve",
)
