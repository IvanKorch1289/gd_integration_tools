"""DSL Playground — интерактивная песочница для RouteBuilder."""

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.entrypoints.streamlit_app.api_client import get_api_client

st.set_page_config(page_title="DSL Playground", page_icon=":test_tube:", layout="wide")
st.header("DSL Playground")
st.caption("Напиши код → Запусти → Посмотри результат. Dry-run доступен.")

# ─────────── Example templates ───────────

EXAMPLES = {
    "Hello World": """# Простой маршрут
route = (
    RouteBuilder.from_("demo.hello", source="internal:demo")
    .set_property("greeting", "Привет, мир!")
    .log()
    .build()
)""",
    "ETL pipeline": """# ETL: получить → преобразовать → сохранить
route = (
    RouteBuilder.from_("demo.etl", source="cron:0 */2 * * *")
    .dispatch_action("external_db.query")
    .transform("data[*].{id: id, name: name}")
    .dispatch_action("analytics.insert_batch")
    .log("ETL complete")
    .build()
)""",
    "AI Q&A": """# AI Q&A с RAG + PII маскировкой
route = (
    RouteBuilder.from_("demo.ai_qa", source="internal:ai")
    .rag_search(query_field="question", top_k=5)
    .compose_prompt(
        template="Контекст:\\n{context}\\n\\nВопрос: {question}\\nОтвет:",
        context_property="vector_results",
    )
    .sanitize_pii()
    .call_llm(provider="perplexity")
    .restore_pii()
    .build()
)""",
    "Retry + DLQ": """# Безопасный вызов с retry и dead-letter queue
route = (
    RouteBuilder.from_("demo.safe", source="internal:safe")
    .do_try(
        try_processors=[
            DispatchActionProcessor(action="external.api_call"),
        ],
        catch_processors=[
            DispatchActionProcessor(action="fallback.local"),
        ],
    )
    .log("Done")
    .build()
)""",
}

col1, col2 = st.columns([1, 3])

with col1:
    st.subheader("Примеры")
    example_name = st.selectbox("Выбрать шаблон", list(EXAMPLES.keys()))
    if st.button("Загрузить"):
        st.session_state["dsl_code"] = EXAMPLES[example_name]

    st.divider()
    st.subheader("Действия")
    dry_run = st.checkbox("Dry-run (без side-effects)", value=True)

with col2:
    st.subheader("Код маршрута")
    code = st.text_area(
        "RouteBuilder code",
        value=st.session_state.get("dsl_code", EXAMPLES["Hello World"]),
        height=400,
        key="dsl_code",
    )

    col_run, col_lint, col_validate = st.columns(3)
    with col_run:
        run_btn = st.button("▶ Запустить", type="primary", use_container_width=True)
    with col_lint:
        lint_btn = st.button("Lint", use_container_width=True)
    with col_validate:
        validate_btn = st.button("Validate", use_container_width=True)

# ─────────── Execution ───────────

st.divider()
st.subheader("Результат")

if run_btn or lint_btn or validate_btn:
    try:
        endpoint = "/api/v1/admin/dsl/playground"
        mode = "dry_run" if dry_run else "execute"
        if lint_btn:
            mode = "lint"
        if validate_btn:
            mode = "validate"

        client = get_api_client()
        try:
            result = client._request(
                "POST", endpoint, json={"code": code, "mode": mode}
            )
        except Exception:
            result = {
                "status": "offline",
                "message": "API endpoint не реализован — работаем локально",
                "code_preview": code[:200],
            }

        if isinstance(result, dict):
            status = result.get("status", "ok")
            if status == "ok":
                st.success("Успешно")
            elif status == "offline":
                st.info(result.get("message", ""))
            else:
                st.error(result.get("message", "Ошибка"))
            st.json(result)
        else:
            st.code(str(result))
    except Exception as exc:
        st.error(f"Ошибка: {exc}")
