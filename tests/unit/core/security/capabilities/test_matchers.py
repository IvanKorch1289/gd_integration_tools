# ruff: noqa: S101
"""Тесты ScopeMatcher-strategies (ADR-044)."""

from __future__ import annotations

import pytest

from src.core.security.capabilities import (
    ExactAliasMatcher,
    GlobScopeMatcher,
    SegmentedGlobMatcher,
    URISchemeMatcher,
)


class TestExactAliasMatcher:
    def test_match_equal(self) -> None:
        assert ExactAliasMatcher().match("credit_db", "credit_db") is True

    def test_no_match_different(self) -> None:
        assert ExactAliasMatcher().match("credit_db", "audit_db") is False

    def test_no_match_substring(self) -> None:
        assert ExactAliasMatcher().match("credit_db_v2", "credit_db") is False


class TestGlobScopeMatcherDot:
    """sep=`.` — host/topic/workflow_id."""

    @pytest.mark.parametrize(
        ("requested", "declared", "expected"),
        [
            ("credit.events.scored", "credit.events.*", True),
            ("credit.events", "credit.events.*", False),
            # `*` ровно один сегмент — `.x.y` после `events.` это два.
            ("credit.events.x.y", "credit.events.*", False),
            ("api.cbr.ru", "*.cbr.ru", True),
            ("payments.bank.local", "*.bank.local", True),
            ("internal.api", "*.cbr.ru", False),
            # `**` рекурсивно — любой набор сегментов.
            ("credit.events.x.y", "credit.events.**", True),
            ("credit.events", "credit.events.**", True),
        ],
    )
    def test_match_table(self, requested: str, declared: str, expected: bool) -> None:
        assert GlobScopeMatcher().match(requested, declared) is expected


class TestSegmentedGlobMatcherSlash:
    """sep=`/` — file paths."""

    @pytest.mark.parametrize(
        ("requested", "declared", "expected"),
        [
            ("/var/lib/credit/123.csv", "/var/lib/credit/*", True),
            ("/var/lib/credit/sub/123.csv", "/var/lib/credit/*", False),
            ("/var/lib/credit/sub/x", "/var/lib/credit/**", True),
            ("/etc/passwd", "/var/lib/**", False),
        ],
    )
    def test_path(self, requested: str, declared: str, expected: bool) -> None:
        assert SegmentedGlobMatcher(sep="/").match(requested, declared) is expected


class TestSegmentedGlobMatcherColon:
    """sep=`:` — cache namespace."""

    def test_namespace(self) -> None:
        m = SegmentedGlobMatcher(sep=":")
        assert m.match("tenant:1:plugin:credit:k", "tenant:*:plugin:credit:*") is True
        assert m.match("tenant:1:plugin:audit:k", "tenant:*:plugin:credit:*") is False

    def test_invalid_sep_length(self) -> None:
        with pytest.raises(ValueError, match="exactly one char"):
            SegmentedGlobMatcher(sep="::")


class TestURISchemeMatcher:
    def test_same_scheme_glob_pass(self) -> None:
        assert (
            URISchemeMatcher().match("vault://credit/api_key", "vault://credit/*")
            is True
        )

    def test_cross_scheme_rejected(self) -> None:
        assert URISchemeMatcher().match("env://CREDIT_KEY", "vault://credit/*") is False

    def test_no_scheme_pass_through(self) -> None:
        assert URISchemeMatcher().match("plain_secret", "plain_secret") is True

    def test_kms_scheme(self) -> None:
        assert URISchemeMatcher().match("kms://k1/v2", "kms://k1/*") is True
