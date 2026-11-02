"""Baseline-декларации ядра без blanket-scope (ADR-0416, дефект 3).

До ADR-0416 baseline объявлял 77 capability со scope ``"**"`` сразу для
namespace'ов ``core`` / ``system`` / ``ai-agent``. Wildcard-scope означал,
что scope-проверка была отключена: ``fs.read`` проходил для любого пути,
``net.outbound`` — для любого хоста, ``storage.read`` — для любого ключа
(в т.ч. чужого тенанта).

Проверяется:

* ресурсный scope (путь/хост/ключ) вне декларации владельца → DENY;
* в baseline-декларациях ядра не осталось blanket ``scope="**"``;
* resource-scoped capability в baseline **не** объявлены — их объявляет
  владелец ресурса (роут/плагин, ADR-0078 / ADR-044);
* объявленный baseline — исчерпывающий и с явными scope.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from src.backend.core.security.capabilities.core_declarations import (
    CORE_CAPABILITIES,
    CORE_CAPABILITY_SCOPES,
    RESOURCE_SCOPED_CAPABILITIES,
    core_capability_refs,
)
from src.backend.core.security.capabilities.errors import CapabilityDeniedError
from src.backend.core.security.capabilities.gate import (
    CapabilityGate,
    get_capability_gate,
)

pytestmark = pytest.mark.unit

#: Namespace'ы платформы, которым достаётся baseline-декларация ядра.
PLATFORM_NAMESPACES: tuple[str, ...] = ("core", "system", "ai-agent")

#: Пробы из аудита (ADR-0416, дефект 3): resource-scoped capability с
#: произвольным scope обязан отклоняться.
RESOURCE_PROBES: tuple[tuple[str, str], ...] = (
    ("fs.read", "/etc/shadow"),
    ("net.outbound", "evil.internal.example"),
    ("storage.read", "tenant-a/private/secret.txt"),
    ("rpa.shell.exec", "rm -rf /"),
    ("db.read", "credit_reports"),
    ("cache.read", "default"),
)


@pytest.fixture
def gate() -> Iterator[CapabilityGate]:
    """Изолированный process-wide singleton capability-гейта."""
    get_capability_gate.cache_clear()
    instance = get_capability_gate()
    yield instance
    get_capability_gate.cache_clear()


@pytest.mark.parametrize(("capability", "scope"), RESOURCE_PROBES)
@pytest.mark.parametrize("namespace", PLATFORM_NAMESPACES)
def test_resource_scope_denied_without_owner_declaration(
    gate: CapabilityGate, namespace: str, capability: str, scope: str
) -> None:
    """Ресурсный scope без декларации владельца → DENY (ADR-0416)."""
    with pytest.raises(CapabilityDeniedError):
        gate.check(namespace, capability, scope)


def test_baseline_declarations_have_no_wildcard_scope() -> None:
    """В baseline-декларациях ядра не осталось blanket ``scope="**"``."""
    offenders = [ref.name for ref in core_capability_refs() if ref.scope == "**"]
    assert not offenders, f"wildcard-scope в baseline: {offenders}"


def test_gate_has_no_wildcard_scope(gate: CapabilityGate) -> None:
    """Ни в одном namespace гейта не осталось blanket-scope."""
    offenders = [
        (namespace, name)
        for namespace, caps in gate._declarations.items()
        for name, ref in caps.items()
        if ref.scope == "**"
    ]
    assert not offenders, f"wildcard-scope в гейте: {offenders}"


def test_resource_scoped_capabilities_excluded_from_baseline() -> None:
    """Resource-scoped capability в baseline не объявлены."""
    declared = {ref.name for ref in core_capability_refs()}
    leaked = sorted(declared & RESOURCE_SCOPED_CAPABILITIES)
    assert not leaked, f"resource-scoped capability попали в baseline: {leaked}"


def test_declared_baseline_has_explicit_scopes() -> None:
    """Каждой объявленной capability соответствует явный непустой scope."""
    scopes = {ref.name: ref.scope for ref in core_capability_refs()}
    assert scopes, "baseline ядра не должен быть пустым"
    assert set(scopes) == set(CORE_CAPABILITY_SCOPES) | {"fs.read"}
    assert all(scope and scope != "**" for scope in scopes.values())


def test_resource_scoped_capabilities_still_known_to_core() -> None:
    """Исключённые capability остаются в списке capability ядра (ADR-0366).

    Список :data:`CORE_CAPABILITIES` отвечает на вопрос «какие capability
    принадлежат ядру» и используется резолвером; baseline-декларация
    отвечает на вопрос «что ядро выдаёт самостоятельно».
    """
    assert RESOURCE_SCOPED_CAPABILITIES <= set(CORE_CAPABILITIES)


def test_core_capabilities_classification_is_exhaustive() -> None:
    """Каждая capability ядра либо объявлена в baseline, либо исключена из него."""
    declared = {ref.name for ref in core_capability_refs()}
    unclassified = sorted(
        set(CORE_CAPABILITIES) - declared - RESOURCE_SCOPED_CAPABILITIES
    )
    assert not unclassified, f"capability без решения по scope: {unclassified}"
