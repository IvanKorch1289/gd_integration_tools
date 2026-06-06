"""Tests for TD-013: jitter в exponential backoff.

Sprint 46 W2: добавлен ``jitter_ratio`` параметр в ``BaseAPIClient`` для
предотвращения thundering herd при одновременных retries.

Покрывает:
- Default ``jitter_ratio=0`` → deterministic (backward-compatible).
- ``jitter_ratio=0.1`` → backoff в диапазоне [base*0.9, base*1.1].
- ``jitter_ratio=0.5`` → backoff в диапазоне [base*0.5, base*1.5].
- Clamping: ``jitter_ratio > 1.0`` → 1.0; ``< 0.0`` → 0.0.
- Backoff остаётся > 0 даже при максимальном negative jitter.
- Разные attempts дают разный base, и jitter применяется к каждому.
- ``time.sleep`` получает jittered значение.
"""

from __future__ import annotations

import random
from unittest.mock import patch

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient


class TestJitterClamping:
    """Constructor должен clamp ``jitter_ratio`` к [0.0, 1.0]."""

    def test_default_is_zero(self) -> None:
        c = BaseAPIClient()
        assert c._jitter_ratio == 0.0

    def test_explicit_zero(self) -> None:
        c = BaseAPIClient(jitter_ratio=0.0)
        assert c._jitter_ratio == 0.0

    def test_positive_value_preserved(self) -> None:
        c = BaseAPIClient(jitter_ratio=0.3)
        assert c._jitter_ratio == 0.3

    def test_negative_clamped_to_zero(self) -> None:
        c = BaseAPIClient(jitter_ratio=-0.5)
        assert c._jitter_ratio == 0.0

    def test_above_one_clamped_to_one(self) -> None:
        c = BaseAPIClient(jitter_ratio=1.5)
        assert c._jitter_ratio == 1.0

    def test_one_preserved(self) -> None:
        c = BaseAPIClient(jitter_ratio=1.0)
        assert c._jitter_ratio == 1.0


class TestSleepBackoffJitter:
    """``_sleep_backoff`` применяет jitter корректно."""

    def test_no_jitter_sleeps_deterministic_value(self) -> None:
        """``jitter_ratio=0`` → ``time.sleep(base)`` без random."""
        c = BaseAPIClient(jitter_ratio=0.0, initial_backoff=0.5)
        with patch("src.frontend.streamlit_app.api_clients.base.time.sleep") as sleep:
            with patch(
                "src.frontend.streamlit_app.api_clients.base.random.uniform"
            ) as uniform:
                c._sleep_backoff(0)  # attempt 0 → base * 2^0 = 0.5
        sleep.assert_called_once_with(0.5)
        uniform.assert_not_called()

    def test_jitter_0_1_stays_in_range(self) -> None:
        """``jitter_ratio=0.1`` → backoff ∈ [0.45, 0.55] для base=0.5."""
        c = BaseAPIClient(jitter_ratio=0.1, initial_backoff=0.5)
        with patch("src.frontend.streamlit_app.api_clients.base.time.sleep") as sleep:
            c._sleep_backoff(0)
        called_with = sleep.call_args[0][0]
        # base=0.5, factor ∈ [0.9, 1.1] → result ∈ [0.45, 0.55]
        assert 0.45 <= called_with <= 0.55

    def test_jitter_0_5_stays_in_range(self) -> None:
        """``jitter_ratio=0.5`` → backoff ∈ [0.25, 0.75] для base=0.5."""
        c = BaseAPIClient(jitter_ratio=0.5, initial_backoff=0.5)
        with patch("src.frontend.streamlit_app.api_clients.base.time.sleep") as sleep:
            c._sleep_backoff(0)
        called_with = sleep.call_args[0][0]
        # base=0.5, factor ∈ [0.5, 1.5] → result ∈ [0.25, 0.75]
        assert 0.25 <= called_with <= 0.75

    def test_jitter_1_0_stays_in_range(self) -> None:
        """``jitter_ratio=1.0`` → backoff ∈ [0.0, 1.0] для base=0.5."""
        c = BaseAPIClient(jitter_ratio=1.0, initial_backoff=0.5)
        with patch("src.frontend.streamlit_app.api_clients.base.time.sleep") as sleep:
            c._sleep_backoff(0)
        called_with = sleep.call_args[0][0]
        # base=0.5, factor ∈ [0.0, 2.0] → result ∈ [0.0, 1.0]
        assert 0.0 <= called_with <= 1.0

    def test_backoff_never_negative(self) -> None:
        """Даже при max negative jitter backoff остаётся >= 0."""
        c = BaseAPIClient(jitter_ratio=1.0, initial_backoff=0.5)
        with patch("src.frontend.streamlit_app.api_clients.base.time.sleep") as sleep:
            # Force worst-case negative factor (0.0)
            with patch(
                "src.frontend.streamlit_app.api_clients.base.random.uniform",
                return_value=0.0,
            ):
                c._sleep_backoff(0)
        called_with = sleep.call_args[0][0]
        assert called_with >= 0.0

    def test_attempt_3_with_jitter(self) -> None:
        """attempt=3 → base * 2^3 = 0.5*8=4.0; jittered 4.0*0.9..1.1 = [3.6, 4.4]."""
        c = BaseAPIClient(jitter_ratio=0.1, initial_backoff=0.5)
        with patch("src.frontend.streamlit_app.api_clients.base.time.sleep") as sleep:
            c._sleep_backoff(3)
        called_with = sleep.call_args[0][0]
        # base=4.0, factor ∈ [0.9, 1.1] → [3.6, 4.4]
        assert 3.6 <= called_with <= 4.4

    def test_attempt_capped_at_max_backoff(self) -> None:
        """Backoff cap (8s) применяется до jitter (минимизирует выход за cap)."""
        c = BaseAPIClient(jitter_ratio=0.1, initial_backoff=0.5)
        with patch("src.frontend.streamlit_app.api_clients.base.time.sleep") as sleep:
            c._sleep_backoff(10)  # 0.5 * 2^10 = 512 → capped at 8
        called_with = sleep.call_args[0][0]
        # base=8.0 (capped), factor ∈ [0.9, 1.1] → [7.2, 8.8]
        assert 7.2 <= called_with <= 8.8

    def test_random_uniform_called_with_correct_range(self) -> None:
        """``random.uniform`` вызывается с (1-ratio, 1+ratio)."""
        c = BaseAPIClient(jitter_ratio=0.25)
        with patch("src.frontend.streamlit_app.api_clients.base.time.sleep"):
            with patch(
                "src.frontend.streamlit_app.api_clients.base.random.uniform",
                return_value=1.0,
            ) as uniform:
                c._sleep_backoff(0)
        uniform.assert_called_once_with(0.75, 1.25)


class TestJitterDistribution:
    """Sanity: jitter реально даёт разнообразие при многократных вызовах."""

    def test_multiple_calls_produce_different_values(self) -> None:
        """100 вызовов с jitter=0.5 дают хотя бы 5 разных значений."""
        c = BaseAPIClient(jitter_ratio=0.5, initial_backoff=0.5)
        values: set[float] = set()
        with patch("src.frontend.streamlit_app.api_clients.base.time.sleep") as sleep:
            for _ in range(100):
                c._sleep_backoff(0)
                values.add(sleep.call_args[0][0])
        # С 100 calls в диапазоне [0.25, 0.75] должны быть десятки уникальных
        assert len(values) >= 5  # conservative lower bound

    def test_extreme_jitter_spreads_widely(self) -> None:
        """jitter=1.0 → 100 calls дают широкий диапазон значений."""
        c = BaseAPIClient(jitter_ratio=1.0, initial_backoff=1.0)
        values: list[float] = []
        with patch("src.frontend.streamlit_app.api_clients.base.time.sleep") as sleep:
            for _ in range(100):
                c._sleep_backoff(0)
                values.append(sleep.call_args[0][0])
        # Range должен покрывать значительную часть [0.0, 2.0]
        assert max(values) - min(values) > 0.5  # at least 0.5 spread

    def test_no_jitter_produces_identical_values(self) -> None:
        """jitter=0 → все вызовы дают одно и то же значение."""
        c = BaseAPIClient(jitter_ratio=0.0, initial_backoff=0.5)
        with patch("src.frontend.streamlit_app.api_clients.base.time.sleep") as sleep:
            for _ in range(5):
                c._sleep_backoff(0)
        # Все 5 вызовов должны быть одинаковыми
        values = [call.args[0] for call in sleep.call_args_list]
        assert all(v == 0.5 for v in values)


class TestJitterRealRandom:
    """Используем настоящий ``random.uniform`` для smoke-test (без seed)."""

    def test_real_random_stays_in_bounds(self) -> None:
        """100 реальных случайных jittered backoffs — все в ожидаемом диапазоне."""
        c = BaseAPIClient(jitter_ratio=0.3, initial_backoff=1.0)
        for attempt in range(5):
            with patch("src.frontend.streamlit_app.api_clients.base.time.sleep") as sleep:
                c._sleep_backoff(attempt)
            called_with = sleep.call_args[0][0]
            # base=1.0*2^attempt (capped at 8), factor ∈ [0.7, 1.3]
            base = min(1.0 * (2 ** attempt), 8.0)
            assert base * 0.7 <= called_with <= base * 1.3

    def test_seeded_random_is_deterministic(self) -> None:
        """С seed random результат воспроизводим (для тестирования)."""
        c1 = BaseAPIClient(jitter_ratio=0.5, initial_backoff=1.0)
        c2 = BaseAPIClient(jitter_ratio=0.5, initial_backoff=1.0)
        with patch("src.frontend.streamlit_app.api_clients.base.time.sleep") as sleep1:
            random.seed(42)
            c1._sleep_backoff(0)
            v1 = sleep1.call_args[0][0]
        with patch("src.frontend.streamlit_app.api_clients.base.time.sleep") as sleep2:
            random.seed(42)
            c2._sleep_backoff(0)
            v2 = sleep2.call_args[0][0]
        assert v1 == v2
