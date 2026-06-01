"""HeaderMapPolicy — правила трансформации headers при проксировании.

Цели проектирования:
* pure pass-through по умолчанию (ни одного surprise rewrite);
* опциональные add/drop/override — для strip-auth, tracing, tenant-inject;
* правила применяются детерминированно, в порядке: drop → override → add.

Применяется симметрично к request (ExposeProxyProcessor) и response
(ForwardToProcessor)::

    policy = HeaderMapPolicy(
        add={"X-Forwarded-By": "gd-bus"},
        drop=["Authorization"],
    )
    merged = policy.apply(original_headers)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

__all__ = ("HeaderMapPolicy",)


@dataclass(slots=True)
class HeaderMapPolicy:
    """Декларативная политика трансформации HTTP/SOAP-headers.

    Attributes:
        add: Заголовки, добавляемые к результату (не переопределяют
            существующие — используйте ``override`` для этого).
        drop: Имена заголовков, удаляемых полностью (регистр игнорируется).
        override: Заголовки, которые переопределяют существующие.
    """

    add: dict[str, str] = field(default_factory=dict)
    drop: tuple[str, ...] = ()
    override: dict[str, str] = field(default_factory=dict)

    def apply(self, headers: Mapping[str, str]) -> dict[str, str]:
        dropped = {k.lower() for k in self.drop}
        result: dict[str, str] = {
            k: v for k, v in headers.items() if k.lower() not in dropped
        }
        result.update(self.override)
        for k, v in self.add.items():
            result.setdefault(k, v)
        return result

    @classmethod
    def from_dict(cls, raw: dict[str, object] | None) -> "HeaderMapPolicy":
        if not raw:
            return cls()
        add_val = raw.get("add") or {}
        drop_val = raw.get("drop") or ()
        override_val = raw.get("override") or {}
        if not isinstance(add_val, dict):
            raise TypeError("header_map.add должен быть dict")
        if not isinstance(drop_val, (list, tuple)):
            raise TypeError("header_map.drop должен быть list/tuple")
        if not isinstance(override_val, dict):
            raise TypeError("header_map.override должен быть dict")
        return cls(
            add={str(k): str(v) for k, v in add_val.items()},
            drop=tuple(str(x) for x in drop_val),
            override={str(k): str(v) for k, v in override_val.items()},
        )
