"""Pydantic models for OSINT agent."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True, frozen=True)
class CompanyInfo:
    """Basic company information resolved from INN."""

    inn: str
    name: str = ""
    ogrn: str = ""
    registration_date: str = ""
    activity: str = ""
    address: str = ""


@dataclass(slots=True)
class OsintReport:
    """OSINT report for a company.

    Attributes:
        inn: Company INN.
        company_name: Resolved company name.
        report_date: Report generation date (ISO format).
        general_info: General company information.
        positive_mentions: List of positive mentions with sources.
        negative_mentions: List of negative mentions with sources.
        court_cases: List of court cases with details.
        financial_markers: List of financial markers.
        sources: List of source URLs.
        raw_text: Full report text (max 3000 chars).
    """

    inn: str
    company_name: str = ""
    report_date: str = ""
    general_info: str = ""
    positive_mentions: list[dict[str, str]] = field(default_factory=list)
    negative_mentions: list[dict[str, str]] = field(default_factory=list)
    court_cases: list[dict[str, str]] = field(default_factory=list)
    financial_markers: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    raw_text: str = ""
