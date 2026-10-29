"""Регрессия: ReDoS в EMAIL-регексе (ADR-0392, кластер G3 — логирование).

До фикса ``EMAIL = re.compile(r"[\\w.+-]+@[\\w-]+\\.[\\w.-]+")`` давал
квадратичный бэктрекинг на строках БЕЗ ``@``:

    10 KB → 238 мс, 50 KB → 6.1 с, 100 KB → 27 с

Каждый такой вызов — блокировка event loop (маскирование тела ответа в
``entrypoints/middlewares/data_masking.py`` и PII-фильтр в логах).

Контракт после фикса:

* квантификаторы ограничены (RFC 5321: local ≤ 64, домен ≤ 255, label ≤ 63);
* possessiv-группы исключают бэктрекинг внутри групп;
* fast-path ``if "@" not in value`` — без ``@`` email невозможен, regex
  не запускается вовсе.

Тесты проверяют ЛИНЕЙНОСТЬ (через ``timeit``, без ``sleep``): при
квадратичном росте время на 64 KB было бы ~64x времени на 8 KB, при
линейном — ~8x.
"""

from __future__ import annotations

import re
import timeit

import pytest

from src.backend.core.security.pii_patterns import EMAIL, sub_email

#: Порог (сек) для одного прохода regex по 64 KB «мусора» без ``@``.
#: После фикса реальное время ≈ 0.02 с, до фикса ≈ 13 с.
ABSOLUTE_LIMIT_SEC = 1.0

#: Допустимое превышение линейного роста (линейно = 8x на 8x данных).
LINEAR_RATIO_LIMIT = 12.0


def _scan_seconds(payload: str, number: int = 5) -> float:
    """Среднее время одного прохода ``EMAIL.sub`` по ``payload``."""
    return timeit.timeit(lambda: EMAIL.sub("<masked>", payload), number=number) / number


@pytest.mark.unit
class TestEmailPatternNoRedos:
    """EMAIL-регекс не должен давать квадратичный бэктрекинг."""

    def test_long_string_without_at_is_fast(self) -> None:
        """64 KB строки без ``@`` — обработка за доли секунды."""
        payload = "a" * 64_000
        assert _scan_seconds(payload) < ABSOLUTE_LIMIT_SEC

    def test_scan_scales_linearly_with_input_size(self) -> None:
        """Рост времени линейный по размеру входа (8x данных → ~8x времени).

        Квадратичный regex дал бы ~64x — такой рост и ловится.
        """
        small = "a" * 8_000
        large = "a" * 64_000

        t_small = _scan_seconds(small)
        t_large = _scan_seconds(large)

        assert t_large <= LINEAR_RATIO_LIMIT * t_small + 0.05, (
            f"EMAIL-скан нелинеен: 8KB={t_small:.4f}s, 64KB={t_large:.4f}s "
            f"(ожидается линейный рост)"
        )

    def test_long_string_with_at_is_fast(self) -> None:
        """Строка С ``@`` (и без домена) тоже не должна вызывать катастрофу."""
        payload = ("a" * 32_000) + "@" + ("b" * 32_000)
        assert _scan_seconds(payload) < ABSOLUTE_LIMIT_SEC

    def test_many_at_signs_are_fast(self) -> None:
        """Много ``@`` подряд — тоже линейно (нет вложенного бэктрекинга)."""
        payload = "a@" * 32_000
        assert _scan_seconds(payload) < ABSOLUTE_LIMIT_SEC


@pytest.mark.unit
class TestEmailPatternSemantics:
    """Ограничение квантификаторов не сломало распознавание email."""

    @pytest.mark.parametrize(
        "value",
        [
            "user@example.com",
            "user+tag@example.co.uk",
            "first.last@sub.domain.example.com",
            "user_name@example-host.io",
            "USER@EXAMPLE.COM",
        ],
    )
    def test_valid_emails_still_match(self, value: str) -> None:
        """Валидные адреса по-прежнему распознаются."""
        match = EMAIL.search(value)
        assert match is not None
        assert "@" in match.group(0)

    @pytest.mark.parametrize("value", ["not_an_email", "user@", "@example.com"])
    def test_invalid_emails_do_not_match(self, value: str) -> None:
        """Мусор не распознаётся как email."""
        assert EMAIL.search(value) is None


@pytest.mark.unit
class TestSubEmailFastPath:
    """``sub_email`` — fast-path для строк без ``@``."""

    def test_fast_path_returns_input_unchanged(self) -> None:
        """Без ``@`` строка возвращается как есть (и быстро)."""
        payload = "a" * 200_000
        result = sub_email("<masked>", payload)
        assert result == payload

    def test_fast_path_is_cheap_for_long_payload(self) -> None:
        """Fast-path не сканирует строку regex'ом — время O(n) константа."""
        payload = "a" * 500_000
        elapsed = timeit.timeit(lambda: sub_email("<masked>", payload), number=20) / 20
        assert elapsed < 0.05

    def test_sub_email_masks_when_at_present(self) -> None:
        """При наличии ``@`` — обычная замена совпадений."""
        assert sub_email("<masked>", "mail bob@example.com now") == (
            "mail <masked> now"
        )

    def test_sub_email_supports_callable_replacement(self) -> None:
        """Замена-функция поддерживается (как в ``re.sub``)."""

        def _repl(match: re.Match[str]) -> str:
            return f"<{match.group(0).count('@')}>"

        assert sub_email(_repl, "a@b.c") == "<1>"
