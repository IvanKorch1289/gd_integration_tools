"""API versioning: header/URL, deprecation+sunset metadata."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ("APIVersion",)


@dataclass(slots=True)
class APIVersion:
    version: str
    deprecated: bool = False
    sunset: str | None = None  # ISO date (RFC 8594)

    def as_headers(self) -> dict[str, str]:
        out = {"API-Version": self.version}
        if self.deprecated:
            out["Deprecation"] = "true"
        if self.sunset:
            out["Sunset"] = self.sunset
        return out
