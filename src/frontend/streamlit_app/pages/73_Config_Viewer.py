"""Config Viewer — все настройки приложения с маскировкой секретов.

Маскирует значения полей, имена которых содержат паттерны:
``password``, ``secret``, ``token``, ``api_key``, ``private``, ``auth``.
Значения отображаются как ``***skb***``, чтобы можно было различить
"секрет проставлен" vs "секрет пустой".
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import streamlit as st

_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.frontend.streamlit_app.api_client import get_api_client

st.set_page_config(page_title="Config", page_icon=":gear:", layout="wide")
st.header(":gear: Config Viewer")

SECRET_PATTERNS = re.compile(
    r"(password|secret|token|api_key|private|auth|client_secret|bearer)", re.IGNORECASE
)


def mask_secrets(obj: Any, parent_key: str = "") -> Any:
    """Рекурсивно проходит структуру и заменяет значения секретных полей.

    Маскируются только значения — имена ключей не меняются. Если секрет
    пустой — отображается ``(empty)``, чтобы отличать "не задано" от "скрыто".
    """
    if isinstance(obj, dict):
        return {k: mask_secrets(v, parent_key=k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask_secrets(v, parent_key=parent_key) for v in obj]
    if SECRET_PATTERNS.search(parent_key or ""):
        if obj in (None, "", 0, False):
            return "(empty)"
        return "***"
    return obj


client = get_api_client()

try:
    config = client._request("GET", "/api/v1/admin/config")  # type: ignore[attr-defined]
except Exception as exc:  # noqa: BLE001
    config = {}
    st.error(f"Не удалось получить конфиг: {exc}")

if config:
    masked = mask_secrets(config)
    st.caption("Секреты скрыты. Фильтр по ключам:")
    filter_q = st.text_input("Поиск", value="")

    def _match(d: dict, q: str) -> dict:
        ql = q.lower()
        return {
            k: v
            for k, v in d.items()
            if ql in k.lower()
            or (isinstance(v, (str, int, float)) and ql in str(v).lower())
        }

    if filter_q and isinstance(masked, dict):
        masked = {
            k: _match(v, filter_q) if isinstance(v, dict) else v
            for k, v in masked.items()
            if filter_q.lower() in k.lower()
            or (isinstance(v, dict) and _match(v, filter_q))
        }

    st.json(masked)
else:
    st.info("Конфигурация недоступна.")

if st.button("Hot-reload config"):
    try:
        resp = client._request("POST", "/api/v1/admin/config/reload")  # type: ignore[attr-defined]
        st.success(f"Reload: {resp}")
    except Exception as exc:  # noqa: BLE001
        st.error(str(exc))
