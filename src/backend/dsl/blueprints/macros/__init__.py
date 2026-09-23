"""DSL blueprint macros package (S68 W1 decomp from macros.py 458 LOC).

8 top-level macro blueprint funcs -> 8 files (per-macro file split):
- etl_pipeline, webhook_relay, ai_qa_pipeline, safe_action
- crud_with_audit, scrape_and_store, format_bridge, polling_etl

Backward-compat: ``from src.backend.dsl.blueprints.macros import etl_pipeline`` works.
"""

from __future__ import annotations

from src.backend.dsl.blueprints.macros.ai_qa_pipeline import (  # noqa: F401 — re-export
    ai_qa_pipeline,  # S68 W1: re-export
)
from src.backend.dsl.blueprints.macros.crud_with_audit import (  # noqa: F401 — re-export
    crud_with_audit,  # S68 W1: re-export
)
from src.backend.dsl.blueprints.macros.etl_pipeline import (  # noqa: F401 — re-export
    etl_pipeline,  # S68 W1: re-export
)
from src.backend.dsl.blueprints.macros.format_bridge import (  # noqa: F401 — re-export
    format_bridge,  # S68 W1: re-export
)
from src.backend.dsl.blueprints.macros.polling_etl import (  # noqa: F401 — re-export
    polling_etl,  # S68 W1: re-export
)
from src.backend.dsl.blueprints.macros.safe_action import (  # noqa: F401 — re-export
    safe_action,  # S68 W1: re-export
)
from src.backend.dsl.blueprints.macros.scrape_and_store import (  # noqa: F401 — re-export
    scrape_and_store,  # S68 W1: re-export
)
from src.backend.dsl.blueprints.macros.webhook_relay import (  # noqa: F401 — re-export
    webhook_relay,  # S68 W1: re-export
)

__all__ = (
    "ai_qa_pipeline",
    "crud_with_audit",
    "etl_pipeline",
    "format_bridge",
    "polling_etl",
    "safe_action",
    "scrape_and_store",
    "webhook_relay",
)
