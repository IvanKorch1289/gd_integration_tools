"""Property-based tests для PIIMasker (hypothesis).

Critical properties verified:
    - Idempotency: mask_text(mask_text(x)) == mask_text(x)
    - No mutation: mask_dict does not mutate input
    - Email edge-cases: RFC-compatible emails are masked
"""

# ruff: noqa: S101

from __future__ import annotations

from hypothesis import HealthCheck, given, settings, strategies as st

from src.backend.core.security.pii_masker import PIIMasker


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(text=st.text(min_size=1, max_size=500))
def test_mask_idempotent(text: str) -> None:
    """mask_text(mask_text(x)) == mask_text(x).

    Double-masking must not introduce new patterns or unmask previously masked data.
    """
    masker = PIIMasker()
    once = masker.mask_text(text)
    twice = masker.mask_text(once)
    assert once == twice, f"Idempotency violated: first pass changed on second pass"


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    emails=st.lists(
        st.from_regex(
            r"[a-z][a-z0-9_.+-]{0,30}@[a-z0-9-]+\.[a-z]{2,6}",
            fullmatch=True,
        ),
        min_size=0,
        max_size=5,
    )
)
def test_emails_are_masked(emails: list[str]) -> None:
    """All RFC-compatible emails in text are masked (no raw @ remains after masking)."""
    masker = PIIMasker()
    text = " ".join(emails)
    masked = masker.mask_text(text)
    # After masking, no raw email pattern should remain
    import re

    raw_emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}", masked)
    assert raw_emails == [], f"Unmasked emails found: {raw_emails}"


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    data=st.dictionaries(
        keys=st.text(min_size=1, max_size=20),
        values=st.one_of(
            st.text(min_size=0, max_size=100),
            st.integers(),
            st.lists(st.text(min_size=0, max_size=50), max_size=5),
        ),
        min_size=0,
        max_size=10,
    )
)
def test_mask_dict_no_mutation(data: dict) -> None:
    """mask_dict must not mutate the input dictionary."""
    import copy

    masker = PIIMasker()
    original = copy.deepcopy(data)
    masker.mask_dict(data)
    assert data == original, "mask_dict mutated the input dictionary"
