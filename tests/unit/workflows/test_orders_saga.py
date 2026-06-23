"""S168 W14: orders_saga demo workflow removed (commit 9164a59 "enable all feature flags + remove demos").

All 8 tests in this module depend on build_orders_saga_workflow() which no longer exists.
Skipped — not deleted (the workflow design pattern is still valid, just the demo was removed).
"""
import pytest

pytest.skip("orders_saga demo removed — S168 W14", allow_module_level=True)
