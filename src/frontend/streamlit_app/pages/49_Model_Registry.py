"""Streamlit page Model Registry UI (Sprint 11 K4 W6).

Подключается к ``/admin/model-registry/*`` REST endpoint'ам.
Активна только при ``feature_flags.ai_model_registry_ui=True``.
"""

from __future__ import annotations

import streamlit as st

try:
    from src.frontend.streamlit_app.api_client import APIClient
except ImportError:  # pragma: no cover
    APIClient = None

st.set_page_config(page_title="Model Registry", page_icon="🧬", layout="wide")
st.title("🧬 AI Model Registry")
st.caption(
    "Composite MLflow + Hugging Face Hub. "
    "Активируется feature-flag `ai_model_registry_ui`."
)


def _client() -> "APIClient":
    if APIClient is None:
        st.error("APIClient недоступен (frontend split). Используйте REST напрямую.")
        st.stop()
    return APIClient()


def _list_models() -> list[dict]:
    try:
        resp = _client().get("/admin/model-registry/models")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось получить модели: {exc}")
        return []
    if not isinstance(resp, dict):
        return []
    return resp.get("models", []) or []


def main() -> None:
    models = _list_models()
    if not models:
        st.info(
            "Моделей нет. Проверьте, что mlflow или huggingface_hub установлен и "
            "feature-flag ai_model_registry_ui=True."
        )
        return

    col_list, col_detail = st.columns([1, 1])
    with col_list:
        st.subheader(f"Найдено моделей: {len(models)}")
        choices = {
            f"{m['name']}@{m['version']} ({m['extra'].get('backend', '')})": m
            for m in models
        }
        choice_key = st.selectbox("Выберите модель", list(choices.keys()))
        chosen = choices[choice_key]

    with col_detail:
        st.subheader(chosen["name"])
        st.write(f"**Version**: `{chosen['version']}`")
        st.write(f"**Stage**: `{chosen['stage']}`")
        st.write(f"**Backend**: `{chosen['extra'].get('backend', 'unknown')}`")
        if chosen.get("artifact_uri"):
            st.code(chosen["artifact_uri"], language="text")

        st.markdown("**Метаданные**")
        st.json(chosen.get("tags", {}))

        if st.button("📋 Use in route", type="primary"):
            try:
                resp = _client().post(
                    f"/admin/model-registry/models/{chosen['name']}/use-in-route",
                    json={"version": chosen["version"]},
                )
                st.success("Сгенерирован DSL snippet:")
                st.code(resp.get("snippet", ""), language="python")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Ошибка: {exc}")


main()
