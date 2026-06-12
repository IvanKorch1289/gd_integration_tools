from __future__ import annotations

"""Setup infrastructure package (S60 W3 decomp from setup_infra.py 534 LOC).

13 top-level funcs decomposed в 4 files (per concern):
- ``health.py`` (2): _get_watcher_manager, _register_health_checks
- ``pools.py`` (5): _register_pools_in_unified_manager, _warmup_connection_pools, _redis_enabled, _s3_enabled, _clickhouse_enabled
- ``workflow_audit.py`` (2): _init_workflow_audit_sink, _close_workflow_audit_sink
- ``lifecycle.py`` (4): _register_default_degradation_features, perform_infrastructure_operation, starting, ending

Backward-compat: ``from src.backend.plugins.composition.setup_infra import perform_infrastructure_operation`` works.
"""


from src.backend.plugins.composition.setup_infra.health import (
    _get_watcher_manager,  # S60 W3: re-export
    _register_health_checks,  # S60 W3: re-export
)
from src.backend.plugins.composition.setup_infra.lifecycle import (
    _register_default_degradation_features,  # S60 W3: re-export
    ending,  # S60 W3: re-export
    perform_infrastructure_operation,  # S60 W3: re-export
    starting,  # S60 W3: re-export
)
from src.backend.plugins.composition.setup_infra.pools import (
    _clickhouse_enabled,  # S60 W3: re-export
    _redis_enabled,  # S60 W3: re-export
    _register_pools_in_unified_manager,  # S60 W3: re-export
    _s3_enabled,  # S60 W3: re-export
    _warmup_connection_pools,  # S60 W3: re-export
)
from src.backend.plugins.composition.setup_infra.scheduler_leader import (  # S71 W2: extracted из setup_infra.py orphan
    _scheduler_heartbeat_loop,  # S71 W3: TD-S64-W2 closure, lock auto-extend
    _start_scheduler_with_leader_election,  # S64 W2: leader election
    _stop_scheduler_if_leader,  # S64 W2: symmetric shutdown
)
from src.backend.plugins.composition.setup_infra.workflow_audit import (
    _close_workflow_audit_sink,  # S60 W3: re-export
    _init_workflow_audit_sink,  # S60 W3: re-export
)

__all__ = (
    "_get_watcher_manager",
    "_register_health_checks",
    "_register_pools_in_unified_manager",
    "_warmup_connection_pools",
    "_redis_enabled",
    "_s3_enabled",
    "_clickhouse_enabled",
    "_init_workflow_audit_sink",
    "_close_workflow_audit_sink",
    "_register_default_degradation_features",
    "_scheduler_heartbeat_loop",  # S71 W3
    "_start_scheduler_with_leader_election",  # S71 W2
    "_stop_scheduler_if_leader",  # S71 W2
    "perform_infrastructure_operation",
    "starting",
    "ending",
)
