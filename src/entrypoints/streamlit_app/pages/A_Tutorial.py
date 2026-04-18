"""Interactive Onboarding Tutorial для джунов."""

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

st.set_page_config(page_title="Tutorial", page_icon=":mortar_board:", layout="wide")
st.header("Tutorial — создаём первый маршрут")

if "tutorial_step" not in st.session_state:
    st.session_state.tutorial_step = 1

STEPS = 5
progress = st.session_state.tutorial_step / STEPS
st.progress(progress, text=f"Шаг {st.session_state.tutorial_step} из {STEPS}")

step = st.session_state.tutorial_step

if step == 1:
    st.subheader("Шаг 1: Что такое DSL маршрут?")
    st.markdown("""
    **DSL маршрут** — это описание того, что должно произойти с данными:

    ```
    Данные → [Процессор 1] → [Процессор 2] → ... → Результат
    ```

    **Примеры задач:**
    - Получить заказ из БД, обогатить данными из API, отправить в очередь
    - Парсить сайт каждые 2 часа, сохранять результат в ClickHouse
    - Принять webhook, провалидировать, сохранить, отправить email

    Маршруты работают одинаково через все протоколы: REST, gRPC, GraphQL, MQ, Prefect.
    """)
    st.info("**Ключевая идея:** написал маршрут 1 раз → работает во всех протоколах.")

elif step == 2:
    st.subheader("Шаг 2: Анатомия маршрута")
    st.code("""
from app.dsl.builder import RouteBuilder

route = (
    RouteBuilder.from_(
        "orders.create",              # ID маршрута (уникальный)
        source="http:POST:/orders",   # Откуда приходят данные
        description="Создание заказа", # Описание
    )
    .validate(OrderSchemaIn)           # Шаг 1: проверить данные
    .dispatch_action("orders.add")     # Шаг 2: вызвать сервис
    .log()                             # Шаг 3: записать в лог
    .build()                           # Завершить описание
)
""", language="python")
    st.markdown("""
    **Ключевые элементы:**
    - `from_()` — откуда приходит запрос
    - `.validate()`, `.dispatch_action()`, `.log()` — шаги обработки
    - `.build()` — собирает готовый маршрут
    """)

elif step == 3:
    st.subheader("Шаг 3: Exchange — контейнер данных")
    st.markdown("""
    Данные между шагами передаются через **Exchange** — это ящик с несколькими отделениями:

    - `in_message.body` — основные данные (то, что пришло)
    - `in_message.headers` — заголовки (метаданные)
    - `properties` — временные значения между шагами
    - `out_message.body` — результат
    """)
    st.code("""
# В процессоре можно прочитать данные:
body = exchange.in_message.body
headers = exchange.in_message.headers

# И записать промежуточные результаты:
exchange.set_property("user_id", 123)
exchange.set_property("enriched_data", {...})

# Финальный результат:
exchange.set_out(body=result)
""", language="python")

elif step == 4:
    st.subheader("Шаг 4: Популярные процессоры")
    st.markdown("""
    **Основные строительные блоки:**
    """)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("""
        **Базовые:**
        - `.dispatch_action("x.y")` — вызвать сервис
        - `.validate(Schema)` — проверить данные
        - `.transform(expr)` — преобразовать
        - `.log()` — записать в лог
        - `.set_property(k, v)` — сохранить значение
        """)
    with col2:
        st.markdown("""
        **Продвинутые:**
        - `.retry(max_attempts=3)` — повтор при ошибке
        - `.choice(when=[...])` — условная логика
        - `.parallel(branches={...})` — параллельно
        - `.scatter_gather(routes)` — разослать много
        - `.export(format)` — экспорт Excel/PDF
        """)

    st.info("Полный список — в DSL Visual Editor (следующая страница)")

elif step == 5:
    st.subheader("Шаг 5: Готово!")
    st.success("Вы прошли основы DSL")
    st.markdown("""
    **Что дальше?**

    1. **DSL Visual Editor** — собери маршрут мышкой без кода
    2. **DSL Playground** — попробуй код в песочнице
    3. **Architecture Map** — посмотри общую карту проекта
    4. **Glossary & FAQ** — словарь терминов и частые вопросы
    5. **Code Examples Hub** — готовые примеры для копирования

    **Лайфхаки:**
    - При ошибке смотри `/api/v1/admin/traces` — там видно где упало
    - DSL Linter покажет проблемы до запуска
    - Шаблоны из `templates_library` покрывают 80% задач
    """)
    if st.button("Начать заново"):
        st.session_state.tutorial_step = 1
        st.rerun()

# Navigation

st.divider()
col_prev, col_next = st.columns(2)
with col_prev:
    if step > 1 and st.button("← Назад", use_container_width=True):
        st.session_state.tutorial_step -= 1
        st.rerun()
with col_next:
    if step < STEPS and st.button("Далее →", type="primary", use_container_width=True):
        st.session_state.tutorial_step += 1
        st.rerun()
