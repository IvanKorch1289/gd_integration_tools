"""Unit-тесты маскирования секретов в HAR-кассетах (S10 Wave 1)."""

from __future__ import annotations

import json

from testkit.recorder.secrets_mask import (
    MASKED_VALUE,
    mask_request_body,
    mask_response_headers,
)


def test_header_mask_case_insensitive() -> None:
    """Маскирование headers идёт case-insensitive по списку известных имён."""
    headers = {
        "Authorization": "Bearer token-123",
        "Cookie": "sessionid=abc",
        "Content-Type": "application/json",
    }
    masked = mask_response_headers(headers)
    assert masked["Authorization"] == MASKED_VALUE
    assert masked["Cookie"] == MASKED_VALUE
    # Не-секретный header не трогаем.
    assert masked["Content-Type"] == "application/json"


def test_header_mask_idempotent() -> None:
    """Повторный вызов на уже замаскированных headers не меняет результат."""
    headers = {"X-API-Key": "secret-key", "Accept": "*/*"}
    once = mask_response_headers(headers)
    twice = mask_response_headers(once)
    assert once == twice
    assert once["X-API-Key"] == MASKED_VALUE


def test_header_mask_empty_and_none() -> None:
    """Пустой или None словарь возвращает пустой dict без ошибок."""
    assert mask_response_headers(None) == {}
    assert mask_response_headers({}) == {}


def test_header_mask_no_secret_keys_untouched() -> None:
    """Если в headers нет секретных ключей — словарь остаётся без изменений по содержанию."""
    headers = {"Accept": "application/json", "User-Agent": "tests/1.0"}
    masked = mask_response_headers(headers)
    assert masked == headers
    # Возвращаем копию, а не мутируем исходный.
    masked["X-Tag"] = "x"
    assert "X-Tag" not in headers


def test_body_mask_json_recursive() -> None:
    """JSON-body маскируется рекурсивно по nested-структурам."""
    body = json.dumps(
        {
            "username": "alice",
            "password": "p@ssw0rd",
            "nested": {"refresh_token": "rt-xxx", "other": 42},
            "list": [{"api_key": "k-1"}, {"public": "ok"}],
        }
    )
    result = mask_request_body(body, content_type="application/json")
    assert result is not None
    parsed = json.loads(result)
    assert parsed["username"] == "alice"
    assert parsed["password"] == MASKED_VALUE
    assert parsed["nested"]["refresh_token"] == MASKED_VALUE
    assert parsed["nested"]["other"] == 42
    assert parsed["list"][0]["api_key"] == MASKED_VALUE
    assert parsed["list"][1]["public"] == "ok"


def test_body_mask_form_urlencoded() -> None:
    """form-urlencoded body — маскируются только секретные поля."""
    body = "username=alice&password=secret&csrf=tok123"
    result = mask_request_body(body, content_type="application/x-www-form-urlencoded")
    assert result is not None
    # Гарантируем, что секрет заменён, а username сохранён.
    assert "password=%3Cmasked%3E" in result or f"password={MASKED_VALUE}" in result
    assert "username=alice" in result


def test_body_mask_autodetect_json_by_payload() -> None:
    """Без указания content_type алгоритм определяет JSON по символу `{`."""
    body = json.dumps({"token": "t-xxx", "value": 1})
    result = mask_request_body(body)
    assert result is not None
    parsed = json.loads(result)
    assert parsed["token"] == MASKED_VALUE
    assert parsed["value"] == 1


def test_body_mask_edge_cases() -> None:
    """None / пустая строка / malformed JSON / неизвестный content-type — без ошибок."""
    assert mask_request_body(None) is None
    assert mask_request_body("") == ""
    # Битый JSON — возвращается как есть (не выкидываем исключения).
    broken = "{not a json"
    assert mask_request_body(broken, content_type="application/json") == broken
    # Plain-text без секретов — возвращается без изменений.
    plain = "hello world"
    assert mask_request_body(plain, content_type="text/plain") == plain
