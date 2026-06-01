"""ADR-0054 — declarative :class:`CapabilityPolicy` поверх :class:`CapabilityGate`.

Policy-engine консультируется gate'ом **до** deny-проверки. Позволяет
описать allow/deny правила декларативно (tenant + principal + scope-glob
+ priority + effect) без правки declarations. Tie-break: deny > allow
при равных priority.

Использование::

    from src.backend.core.security.capabilities.policy import (
        CapabilityPolicy, CapabilityRule, PolicyDecision,
    )

    policy = CapabilityPolicy([
        CapabilityRule(
            effect="allow",
            capability="net.outbound",
            scope_glob="net.outbound:*.internal:internal",
            tenant="*",
            principal="*",
            priority=100,
        ),
        CapabilityRule(
            effect="deny",
            capability="net.outbound",
            scope_glob="net.outbound:*:external",
            tenant="tenant_a",
            principal="*",
            priority=200,
        ),
    ])

    gate = CapabilityGate(policy=policy)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.backend.core.security.capabilities.matchers import SegmentedGlobMatcher

__all__ = ("CapabilityPolicy", "CapabilityRule", "PolicyDecision")


Effect = Literal["allow", "deny"]


@dataclass(frozen=True, slots=True)
class CapabilityRule:
    """Одно policy-правило.

    Args:
        effect: ``"allow"`` или ``"deny"``.
        capability: Имя capability (``net.outbound``, ``db.read``, …).
        scope_glob: Glob по scope (``net.outbound:*.internal:internal``).
            ``"*"`` или ``None`` = match-any-scope.
        tenant: Имя tenant'а или ``"*"`` для всех.
        principal: Имя principal/plugin или ``"*"`` для всех.
        priority: Целое число; правила с большим priority оцениваются
            первыми. Tie-break при равных priority: deny > allow.
    """

    effect: Effect
    capability: str
    scope_glob: str | None = None
    tenant: str = "*"
    principal: str = "*"
    priority: int = 0

    def matches(
        self, *, tenant: str, principal: str, capability: str, scope: str | None
    ) -> bool:
        """Возвращает True, если правило применимо к запрошенному контексту."""
        if self.capability != capability:
            return False
        if self.tenant != "*" and self.tenant != tenant:
            return False
        if self.principal != "*" and self.principal != principal:
            return False
        if self.scope_glob is None or self.scope_glob == "*":
            return True
        if scope is None:
            return False
        return _SCOPE_MATCHER.match(scope, self.scope_glob)


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Результат :meth:`CapabilityPolicy.evaluate`.

    Args:
        effect: Итоговый ``allow`` / ``deny`` / ``no_match``.
        rule: Победившее правило (``None`` если ``no_match``).
    """

    effect: Literal["allow", "deny", "no_match"]
    rule: CapabilityRule | None = None


class CapabilityPolicy:
    """Набор policy-правил с детерминированным evaluation order.

    Правила сортируются по убыванию priority. При равных priority
    deny-правила оцениваются первыми (deny > allow). Первое сматчившееся
    правило определяет PolicyDecision.

    Args:
        rules: Iterable правил.
    """

    def __init__(self, rules: list[CapabilityRule]) -> None:
        # deny > allow при равных priority: тег '0 if deny else 1'
        # как secondary key, отсортировано asc → deny раньше allow.
        self._rules: tuple[CapabilityRule, ...] = tuple(
            sorted(rules, key=lambda r: (-r.priority, 0 if r.effect == "deny" else 1))
        )

    @property
    def rules(self) -> tuple[CapabilityRule, ...]:
        """Возвращает правила в evaluation-порядке."""
        return self._rules

    def evaluate(
        self, *, tenant: str, principal: str, capability: str, scope: str | None
    ) -> PolicyDecision:
        """Найти первое сматчившееся правило.

        Args:
            tenant: Текущий tenant.
            principal: Текущий plugin/route.
            capability: Имя capability.
            scope: Запрошенный scope (или ``None``).

        Returns:
            :class:`PolicyDecision` с ``effect`` и победившим ``rule``.
            Если ни одно правило не сматчилось — ``effect="no_match"``.
        """
        for rule in self._rules:
            if rule.matches(
                tenant=tenant, principal=principal, capability=capability, scope=scope
            ):
                return PolicyDecision(effect=rule.effect, rule=rule)
        return PolicyDecision(effect="no_match", rule=None)


_SCOPE_MATCHER = SegmentedGlobMatcher(":")
"""Single instance для scope-glob matching (segments разделены ':')."""
