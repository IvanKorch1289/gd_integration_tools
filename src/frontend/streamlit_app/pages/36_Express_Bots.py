"""Express Bots — список ботов, тест-консоль и статистика.

Wave 4.2: единая страница администрирования Express-интеграции.

Возможности:
- Список ботов из ``express_settings`` (main + extra_bots).
- Тест-консоль: отправка тестового сообщения через ``ExpressBotClient.send_message``.
- Конструктор bubble/keyboard кнопок (генерация YAML-фрагмента).
- Статистика отправок (Prometheus-метрики ``express_messages_sent_total``).
"""

from __future__ import annotations

import asyncio
import json

import streamlit as st

st.set_page_config(
    page_title="Express Bots", page_icon=":speech_balloon:", layout="wide"
)
st.header(":speech_balloon: Express Bots")

try:
    from src.backend.core.config.express import express_settings
except Exception as exc:  # noqa: BLE001
    st.error(f"Не удалось загрузить настройки Express: {exc}")
    st.stop()

if not express_settings.enabled:
    st.warning(
        "Express интеграция отключена (``express_settings.enabled=False``). "
        "Включите через ENV ``EXPRESS_ENABLED=true`` или YAML-конфиг."
    )

bots = [
    {
        "name": "main_bot",
        "bot_id": express_settings.bot_id or "—",
        "botx_url": express_settings.botx_url,
        "default_chat_id": express_settings.default_chat_id or "—",
    }
]
for extra in express_settings.extra_bots:
    bots.append(
        {
            "name": extra.get("name", "—"),
            "bot_id": extra.get("bot_id", "—"),
            "botx_url": extra.get("base_url", "—"),
            "default_chat_id": extra.get("default_chat_id", "—"),
        }
    )

tab_list, tab_send, tab_buttons, tab_metrics = st.tabs(
    ["Боты", "Тест-консоль", "Конструктор кнопок", "Метрики"]
)

with tab_list:
    st.subheader("Зарегистрированные боты")
    st.dataframe(bots, use_container_width=True)
    st.caption(
        f"Callback URL: ``{express_settings.callback_url or '—'}`` · "
        f"BotX host: ``{express_settings.botx_host or '— (derived)'}``"
    )

with tab_send:
    st.subheader("Тестовое сообщение")
    if not express_settings.enabled:
        st.info("Включите Express в настройках, чтобы отправлять сообщения.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            bot_name = st.selectbox("Бот", options=[b["name"] for b in bots], index=0)
            chat_id = st.text_input(
                "group_chat_id",
                value=express_settings.default_chat_id or "",
                placeholder="UUID чата",
            )
        with col2:
            sync_send = st.toggle("Синхронный endpoint /direct/sync", value=False)
            status = st.selectbox("Статус", ["ok", "error"], index=0)

        body = st.text_area(
            "Текст сообщения", value="Привет! Это тест Express-интеграции."
        )

        if st.button(":rocket: Отправить", type="primary", use_container_width=True):
            if not chat_id or not body:
                st.error("Заполните chat_id и текст сообщения.")
            else:
                try:
                    from src.backend.core.di.providers import (
                        get_express_bot_client_factory_provider,
                        get_express_botx_message_class_provider,
                    )

                    get_express_client = get_express_bot_client_factory_provider()
                    BotxMessage = get_express_botx_message_class_provider()

                    async def _send() -> str:
                        client = get_express_client(bot_name)
                        async with client:
                            return await client.send_message(
                                BotxMessage(
                                    group_chat_id=chat_id, body=body, status=status
                                ),
                                sync=sync_send,
                            )

                    sync_id = asyncio.run(_send())
                    st.success(f"Отправлено. sync_id = ``{sync_id}``")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Ошибка отправки: {exc}")

with tab_buttons:
    st.subheader("Конструктор bubble / keyboard")
    kind = st.radio("Тип кнопок", ["bubble", "keyboard"], horizontal=True)
    rows = st.number_input("Кол-во рядов", min_value=1, max_value=5, value=1)

    grid: list[list[dict]] = []
    for i in range(int(rows)):
        st.markdown(f"**Ряд {i + 1}**")
        cols = st.columns(3)
        row: list[dict] = []
        for j, col in enumerate(cols):
            with col:
                command = st.text_input(
                    f"Команда [{i + 1}.{j + 1}]", key=f"cmd_{i}_{j}", value=""
                )
                label = st.text_input(
                    f"Label [{i + 1}.{j + 1}]", key=f"lbl_{i}_{j}", value=""
                )
                if command and label:
                    row.append({"command": command, "label": label})
        if row:
            grid.append(row)

    if grid:
        st.code(json.dumps({kind: grid}, ensure_ascii=False, indent=2), language="json")

with tab_metrics:
    st.subheader("Express метрики")
    st.markdown(
        "- ``express_messages_sent_total`` — количество отправок (label: bot, status)\n"
        "- ``express_commands_received_total`` — входящие команды\n"
        "- ``express_delivery_latency_seconds`` — задержка ``read_at - sent_at``\n"
    )
    st.info(
        "Открыть в Prometheus / Grafana: см. дашборд ``Integration Bots`` (Wave 5.2)."
    )
