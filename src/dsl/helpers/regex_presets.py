"""Regex presets для частых банковских/RU-паттернов."""

from __future__ import annotations

import re

__all__ = ("PRESETS", "match")

PRESETS: dict[str, re.Pattern[str]] = {
    "inn10": re.compile(r"^\d{10}$"),
    "inn12": re.compile(r"^\d{12}$"),
    "kpp": re.compile(r"^\d{9}$"),
    "bic": re.compile(r"^\d{9}$"),
    "swift": re.compile(r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$"),
    "iban": re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$"),
    "ru_phone": re.compile(r"^\+7\d{10}$"),
    "email": re.compile(r"^[\w\.-]+@[\w\.-]+\.\w+$"),
}


def match(name: str, value: str) -> bool:
    pattern = PRESETS.get(name)
    if pattern is None:
        raise KeyError(f"Unknown preset: {name}")
    return bool(pattern.match(value))
