"""DSL blueprint macros package (S68 W1 decomp from macros.py 458 LOC).

8 top-level macro blueprint funcs -> 8 files (per-macro file split):
- etl_pipeline, webhook_relay, ai_qa_pipeline, safe_action
- crud_with_audit, scrape_and_store, format_bridge, polling_etl

Backward-compat: ``from src.backend.dsl.blueprints.macros import etl_pipeline`` works.
"""

from __future__ import annotations

from src.backend.dsl.blueprints.macros.ai_qa_pipeline import (
    ai_qa_pipeline,  # S68 W1: re-export
)
from src.backend.dsl.blueprints.macros.crud_with_audit import (
    crud_with_audit,  # S68 W1: re-export
)
from src.backend.dsl.blueprints.macros.etl_pipeline import (
    etl_pipeline,  # S68 W1: re-export
)
from src.backend.dsl.blueprints.macros.format_bridge import (
    format_bridge,  # S68 W1: re-export
)
from src.backend.dsl.blueprints.macros.polling_etl import (
    polling_etl,  # S68 W1: re-export
)
from src.backend.dsl.blueprints.macros.safe_action import (
    safe_action,  # S68 W1: re-export
)
from src.backend.dsl.blueprints.macros.scrape_and_store import (
    scrape_and_store,  # S68 W1: re-export
)
from src.backend.dsl.blueprints.macros.webhook_relay import (
    webhook_relay,  # S68 W1: re-export
)

__all__ = (
    "etl_pipeline",
    "webhook_relay",
    "ai_qa_pipeline",
    "safe_action",
    "crud_with_audit",
    "scrape_and_store",
    "format_bridge",
    "polling_etl",
)
