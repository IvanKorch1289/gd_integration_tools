"""F-PII (CRITICAL): из N секретов в сообщении маскировался только последний.

Аудит 2026-10-05. ``AIDataSanitizer.sanitize_text`` для метки API-ключей
использовал **константный** плейсхолдер ``[REDACTED]`` без счётчика, тогда
как все остальные метки получали уникальные ``[LABEL_n]``.

Механика дефекта: совпадения сканируются первым циклом, а подстановка
выполняется вторым, уже по ``mapping``. Для двух разных секретов:

1. ``mapping["[REDACTED]"] = <секрет_1>``;
2. ``mapping["[REDACTED]"] = <секрет_2>`` — ключ тот же, значение
   перезаписано, ``секрет_1`` потерян навсегда;
3. цикл подстановки заменяет только ``секрет_2``.

Воспроизведено до фикса на реальном коде: из трёх ключей в тексте
``sk-proj-AAAAAAAAAAAAAAAA sk-proj-BBBBBBBBBBBBBBBB sk-proj-CCCCCCCCCCCCCCCC``
в санитизированную строку попадали **два из трёх в открытом виде**. То есть
значительная часть секретов уходила во внешний LLM незамаскированной — ровно
то, чего санитайзер существует, чтобы не допустить.

Тест закрывает регрессию: после фикса маскируются все совпадения, а
round-trip восстановления остаётся точным.
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure.security.ai_sanitizer import AIDataSanitizer

SECRETS = [
    "sk-proj-AAAAAAAAAAAAAAAA",
    "sk-proj-BBBBBBBBBBBBBBBB",
    "sk-proj-CCCCCCCCCCCCCCCC",
]


class TestAllSecretsMasked:
    """Каждое совпадение должно быть замаскировано, а не только последнее."""

    @pytest.mark.unit
    def test_no_secret_survives_in_sanitized_text(self) -> None:
        """Ни один секрет не должен остаться в открытом виде."""
        sanitizer = AIDataSanitizer()
        text = " ".join(SECRETS)

        result = sanitizer.sanitize_text(text)

        leaked = [secret for secret in SECRETS if secret in result.sanitized_text]
        assert not leaked, f"секреты утекли в санитизированный текст: {leaked}"

    @pytest.mark.unit
    def test_every_secret_has_its_own_placeholder(self) -> None:
        """У каждого секрета собственный плейсхолдер — иначе они неразличимы."""
        sanitizer = AIDataSanitizer()
        text = " ".join(SECRETS)

        result = sanitizer.sanitize_text(text)

        assert len(result.sanitized_text.split()) == len(SECRETS)
        for index in range(1, len(SECRETS) + 1):
            assert f"[REDACTED_{index}]" in result.sanitized_text

    @pytest.mark.unit
    def test_mapping_covers_all_secrets(self) -> None:
        """Маппинг хранит все секреты, а не только последний."""
        sanitizer = AIDataSanitizer()
        text = " ".join(SECRETS)

        result = sanitizer.sanitize_text(text)

        assert set(result._mapping.values()) == set(SECRETS)


class TestRoundTripPreserved:
    """Регрессия фикса: восстановление обязано остаться точным."""

    @pytest.mark.unit
    def test_restore_returns_original_text(self) -> None:
        """sanitize → restore возвращает исходный текст байт-в-байт."""
        sanitizer = AIDataSanitizer()
        text = "first={} second={} third={}".format(*SECRETS)

        result = sanitizer.sanitize_text(text)

        assert sanitizer.restore_text(result.sanitized_text, result._mapping) == text

    @pytest.mark.unit
    def test_single_secret_still_masked(self) -> None:
        """Контроль регрессии: одиночный секрет маскируется, как и раньше."""
        sanitizer = AIDataSanitizer()
        text = "use sk-proj-AAAAAAAAAAAAAAAA"

        result = sanitizer.sanitize_text(text)

        assert "sk-proj-AAAAAAAAAAAAAAAA" not in result.sanitized_text
        assert sanitizer.restore_text(result.sanitized_text, result._mapping) == text

    @pytest.mark.unit
    def test_non_secret_labels_still_use_counters(self) -> None:
        """Email-метки не должны пострадать от правки."""
        sanitizer = AIDataSanitizer()
        text = "пиши alice@corp.com и bob@corp.com"

        result = sanitizer.sanitize_text(text)

        assert "[EMAIL_1]" in result.sanitized_text
        assert "[EMAIL_2]" in result.sanitized_text
        assert sanitizer.restore_text(result.sanitized_text, result._mapping) == text
