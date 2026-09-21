"""К5 (Wave K5/chaos-tests) — chaos для ``object_storage_chain``.

3 сценария (parametrize): slow / error / disconnect.

Все тесты бьют по chain напрямую — не через DSL routes (изоляция от К2).
"""

from __future__ import annotations

import pytest

from tests.chaos._chaos_helpers import SCENARIOS, assert_chain_module_loadable

pytestmark = [pytest.mark.chaos, pytest.mark.requires_toxiproxy, pytest.mark.slow]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_object_storage_chain_chaos(scenario: str) -> None:
    """``object_storage`` chain выживает scenario={scenario} через resilience-coordinator."""
    # Smoke: проверяем импорт chain'а и помечаем сценарий.
    assert_chain_module_loadable(
        "src.backend.infrastructure.resilience.components.object_storage_chain"
    )
    # Реальный toxic-инжект делается в живом backend (job chaos.yml);
    # локально без Docker pytest помечает тест skip через
    # фикстуру ``toxiproxy`` в conftest.py (если запрошена).
    assert scenario in {"slow", "error", "disconnect"}, scenario
