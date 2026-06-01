"""Unit-тесты для :class:`PIIMaskProcessor` + :class:`PIIUnmaskProcessor` (S27 W2)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.agent_dsl.pii_mask import PIIMaskProcessor
from src.backend.dsl.engine.processors.agent_dsl.pii_unmask import PIIUnmaskProcessor


@dataclass
class _FakeMaskResult:
    masked_text: str
    token_map: dict[str, str] = field(default_factory=dict)
    pii_detected: bool = False


class _FakePIITokenizer:
    """Fake PIITokenizer для unit-тестов: маскирует email + телефон по regex."""

    EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
    PHONE_RE = re.compile(r"\+?\d[\d \-]{8,}\d")

    async def mask_reversible(
        self, text: str, language: str = "ru"
    ) -> _FakeMaskResult:
        del language
        token_map: dict[str, str] = {}

        def _replace_email(m: re.Match[str]) -> str:
            placeholder = f"[EMAIL_{len(token_map) + 1}]"
            token_map[placeholder] = m.group(0)
            return placeholder

        def _replace_phone(m: re.Match[str]) -> str:
            placeholder = f"[PHONE_{len(token_map) + 1}]"
            token_map[placeholder] = m.group(0)
            return placeholder

        masked = self.EMAIL_RE.sub(_replace_email, text)
        masked = self.PHONE_RE.sub(_replace_phone, masked)
        return _FakeMaskResult(
            masked_text=masked,
            token_map=token_map,
            pii_detected=bool(token_map),
        )

    async def unmask(self, text: str, token_map: dict[str, str]) -> str:
        for placeholder, original in token_map.items():
            text = text.replace(placeholder, original)
        return text


@pytest.fixture
def context() -> ExecutionContext:
    return ExecutionContext()


def test_pii_mask_init_requires_scope() -> None:
    with pytest.raises(ValueError, match="scope обязателен"):
        PIIMaskProcessor(scope="")


@pytest.mark.asyncio
async def test_pii_mask_masks_body_text(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    tokenizer = _FakePIITokenizer()
    monkeypatch.setattr(
        PIIMaskProcessor,
        "_resolve_tokenizer",
        staticmethod(lambda: tokenizer),
    )

    text = "Контакт: ivan@example.com или +7 999 123 45 67"
    ex: Exchange[Any] = Exchange(in_message=Message(body=text))
    proc = PIIMaskProcessor(scope="banking")
    await proc.process(ex, context)

    masked = ex.in_message.body
    assert "[EMAIL_1]" in masked
    assert "[PHONE_2]" in masked
    assert "ivan@example.com" not in masked
    assert "+7 999" not in masked

    token_map = ex.get_property("pii_token_map")
    assert token_map["[EMAIL_1]"] == "ivan@example.com"
    assert ex.get_property("pii_detected") is True


@pytest.mark.asyncio
async def test_pii_mask_unmask_round_trip(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    """mask(text=ФИО+email) → unmask(masked, token_map) восстанавливает оригинал."""
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    tokenizer = _FakePIITokenizer()
    monkeypatch.setattr(
        PIIMaskProcessor,
        "_resolve_tokenizer",
        staticmethod(lambda: tokenizer),
    )
    monkeypatch.setattr(
        PIIUnmaskProcessor,
        "_resolve_tokenizer",
        staticmethod(lambda: tokenizer),
    )

    original = "Контакт Иванова: petrov@bank.ru, +7 495 555 12 34"
    ex: Exchange[Any] = Exchange(in_message=Message(body=original))

    mask_proc = PIIMaskProcessor(scope="banking")
    await mask_proc.process(ex, context)

    assert ex.in_message.body != original  # masked

    unmask_proc = PIIUnmaskProcessor(scope="banking", strict=True)
    await unmask_proc.process(ex, context)

    assert ex.in_message.body == original


@pytest.mark.asyncio
async def test_pii_mask_no_pii_keeps_text(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    tokenizer = _FakePIITokenizer()
    monkeypatch.setattr(
        PIIMaskProcessor,
        "_resolve_tokenizer",
        staticmethod(lambda: tokenizer),
    )

    text = "обычный текст без PII"
    ex: Exchange[Any] = Exchange(in_message=Message(body=text))
    proc = PIIMaskProcessor(scope="banking")
    await proc.process(ex, context)

    assert ex.in_message.body == text
    assert ex.get_property("pii_detected") is False


@pytest.mark.asyncio
async def test_pii_unmask_strict_raises_on_missing_map(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)

    ex: Exchange[Any] = Exchange(in_message=Message(body="masked"))
    proc = PIIUnmaskProcessor(strict=True)
    await proc.process(ex, context)

    assert ex.error is not None
    assert "token_map отсутствует" in ex.error
    assert ex.stopped


@pytest.mark.asyncio
async def test_pii_unmask_non_strict_passes_through(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)

    original_text = "masked text"
    ex: Exchange[Any] = Exchange(in_message=Message(body=original_text))
    proc = PIIUnmaskProcessor(strict=False)
    await proc.process(ex, context)

    assert ex.error is None
    assert ex.in_message.body == original_text


@pytest.mark.asyncio
async def test_pii_mask_tokenizer_unavailable_pass_through(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    monkeypatch.setattr(
        PIIMaskProcessor,
        "_resolve_tokenizer",
        staticmethod(lambda: None),
    )

    text = "email: ivan@example.com"
    ex: Exchange[Any] = Exchange(in_message=Message(body=text))
    proc = PIIMaskProcessor(scope="banking")
    await proc.process(ex, context)

    assert ex.in_message.body == text  # pass-through
    assert ex.get_property("pii_detected") is False


@pytest.mark.asyncio
async def test_pii_mask_unmask_target_property(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    """``target_property`` отличный от source — masked-text идёт в другое место."""
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    tokenizer = _FakePIITokenizer()
    monkeypatch.setattr(
        PIIMaskProcessor,
        "_resolve_tokenizer",
        staticmethod(lambda: tokenizer),
    )

    text = "Контакт: email@x.com"
    ex: Exchange[Any] = Exchange(in_message=Message(body=text))
    proc = PIIMaskProcessor(
        scope="banking",
        source_property="body",
        target_property="masked_text",
    )
    await proc.process(ex, context)

    assert ex.in_message.body == text  # source unchanged
    assert "[EMAIL_1]" in ex.get_property("masked_text")


def test_pii_mask_to_spec_round_trip() -> None:
    proc = PIIMaskProcessor(
        scope="banking",
        source_property="property:llm_input",
        target_property="property:llm_input_masked",
        language="en",
    )
    spec = proc.to_spec()
    assert spec == {
        "pii_mask": {
            "scope": "banking",
            "source_property": "property:llm_input",
            "target_property": "property:llm_input_masked",
            "language": "en",
        }
    }


def test_pii_unmask_to_spec_round_trip() -> None:
    proc = PIIUnmaskProcessor(
        source_property="agent_result.content",
        target_property="agent_result.content_unmasked",
        scope="banking",
        strict=True,
    )
    spec = proc.to_spec()
    assert spec == {
        "pii_unmask": {
            "source_property": "agent_result.content",
            "target_property": "agent_result.content_unmasked",
            "scope": "banking",
            "strict": True,
        }
    }


@pytest.mark.asyncio
async def test_pii_mask_source_from_nested_body_field(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    """``source_property="body.text"`` — извлечение из nested dict."""
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    tokenizer = _FakePIITokenizer()
    monkeypatch.setattr(
        PIIMaskProcessor,
        "_resolve_tokenizer",
        staticmethod(lambda: tokenizer),
    )

    ex: Exchange[Any] = Exchange(
        in_message=Message(
            body={"meta": "x", "text": "email: alice@example.com"}
        )
    )
    proc = PIIMaskProcessor(
        scope="banking",
        source_property="body.text",
        target_property="body.text",
    )
    await proc.process(ex, context)

    body = ex.in_message.body
    assert isinstance(body, dict)
    assert "[EMAIL_1]" in body["text"]
    assert body["meta"] == "x"  # untouched


@pytest.mark.asyncio
async def test_pii_mask_source_from_property(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    """``source_property="prop_name"`` — извлечение из exchange.properties."""
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    tokenizer = _FakePIITokenizer()
    monkeypatch.setattr(
        PIIMaskProcessor,
        "_resolve_tokenizer",
        staticmethod(lambda: tokenizer),
    )

    ex: Exchange[Any] = Exchange()
    ex.set_property("llm_input", "phone: +7 800 555 12 34")
    proc = PIIMaskProcessor(
        scope="banking",
        source_property="llm_input",
        target_property="llm_input_masked",
    )
    await proc.process(ex, context)

    masked = ex.get_property("llm_input_masked")
    assert "[PHONE_1]" in masked
    assert "+7 800" not in masked


@pytest.mark.asyncio
async def test_pii_unmask_target_writes_to_body_field(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    """``target_property="body.unmasked"`` — запись в nested dict."""
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    tokenizer = _FakePIITokenizer()
    monkeypatch.setattr(
        PIIUnmaskProcessor,
        "_resolve_tokenizer",
        staticmethod(lambda: tokenizer),
    )

    ex: Exchange[Any] = Exchange(in_message=Message(body={"text": "[EMAIL_1]"}))
    ex.set_property("pii_token_map", {"[EMAIL_1]": "bob@example.com"})
    proc = PIIUnmaskProcessor(
        source_property="body.text",
        target_property="body.unmasked",
        strict=False,
    )
    await proc.process(ex, context)

    body = ex.in_message.body
    assert isinstance(body, dict)
    assert body["unmasked"] == "bob@example.com"


@pytest.mark.asyncio
async def test_pii_unmask_tokenizer_unavailable_pass_through(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    monkeypatch.setattr(
        PIIUnmaskProcessor,
        "_resolve_tokenizer",
        staticmethod(lambda: None),
    )

    ex: Exchange[Any] = Exchange(in_message=Message(body="[EMAIL_1]"))
    ex.set_property("pii_token_map", {"[EMAIL_1]": "x"})
    proc = PIIUnmaskProcessor(strict=False)
    await proc.process(ex, context)

    assert ex.in_message.body == "[EMAIL_1]"  # pass-through
    assert ex.error is None


@pytest.mark.asyncio
async def test_pii_mask_tokenizer_raises_pass_through(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    """Если tokenizer.mask_reversible() raises — pass-through + pii_detected=False."""
    from src.backend.core.config.features import feature_flags

    class _RaisingTokenizer:
        async def mask_reversible(
            self, text: str, language: str = "ru"
        ) -> None:
            del text, language
            raise RuntimeError("tokenizer kaboom")

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    monkeypatch.setattr(
        PIIMaskProcessor,
        "_resolve_tokenizer",
        staticmethod(lambda: _RaisingTokenizer()),
    )

    text = "email: x@x.com"
    ex: Exchange[Any] = Exchange(in_message=Message(body=text))
    proc = PIIMaskProcessor(scope="banking")
    await proc.process(ex, context)

    assert ex.in_message.body == text  # unchanged
    assert ex.get_property("pii_detected") is False
    assert ex.error is None
