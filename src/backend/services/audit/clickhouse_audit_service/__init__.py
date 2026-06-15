from __future__ import annotations

"""ClickHouse audit service package (S68 W2 decomp from clickhouse_audit_service.py 455 LOC).

2 classes + 4 funcs -> 3 files (per-concern):
- ``state.py``: AuditEvent (1 method)
- ``service.py``: ClickHouseAuditService (4 methods)
- ``helpers.py``: 4 module-level factory funcs

Backward-compat: ``from src.backend.services.audit.clickhouse_audit_service import ClickHouseAuditService`` works.
"""


from src.backend.services.audit.clickhouse_audit_service.helpers import (
    _make_default_event_id,  # S68 W2: helper re-export
    _make_default_timestamp,  # S68 W2: helper re-export
    _service_instance,  # S140 W5: re-export for test singleton reset
    _service_lock,  # S140 W5: re-export for test singleton reset
    get_audit_service,  # S68 W2: helper re-export
    make_audit_event,  # S68 W2: helper re-export
)
from src.backend.services.audit.clickhouse_audit_service.service import (
    ClickHouseAuditService,  # S68 W2: re-export
)
from src.backend.services.audit.clickhouse_audit_service.state import (
    AuditEvent,  # S68 W2: re-export
)

__all__ = (
    "AuditEvent",
    "ClickHouseAuditService",
    "_make_default_event_id",
    "_make_default_timestamp",
    "_service_instance",
    "_service_lock",
    "make_audit_event",
    "get_audit_service",
)
