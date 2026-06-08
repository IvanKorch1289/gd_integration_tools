"""Метаданные процессоров и YAML-шаблон для DSL Visual Editor.

Извлечено из ``31_DSL_Visual_Editor.py`` (S77 W3 refactor). Чистые
данные + один шаблонный генератор, не зависят от Streamlit API.

Wave: ``[wave:s77/w3-dsl-editor-split]``.
"""

from __future__ import annotations

__all__ = (
    "PROCESSOR_ICONS",
    "STEP_PALETTE",
    "VISUAL_PROCESSORS",
    "default_yaml",
)


# Палитра процессоров для drag-drop sidebar (legacy, до Canvas-режима).
STEP_PALETTE: dict[str, dict[str, str]] = {
    "log": {
        "title": "Log",
        "desc": "Логирование сообщений на указанном уровне (debug/info/warning/error)",
    },
    "validate": {
        "title": "Validate",
        "desc": "Валидация входных данных по JSON Schema",
    },
    "transform": {
        "title": "Transform",
        "desc": "Трансформация данных через expression (JQ-подобный синтаксис)",
    },
    "dispatch_action": {
        "title": "Dispatch Action",
        "desc": "Диспетчеризация действия по условию",
    },
    "retry": {
        "title": "Retry",
        "desc": "Повтор выполнения при ошибках с max_attempts и delay",
    },
    "redirect": {
        "title": "Redirect",
        "desc": "Редирект запроса на другой URL или endpoint",
    },
    "windowed_dedup": {
        "title": "Windowed Dedup",
        "desc": "Дедупликация по ключу в скользящем окне",
    },
    "windowed_collect": {
        "title": "Windowed Collect",
        "desc": "Сбор событий в окне с опциональной дедупликацией",
    },
    "multicast_routes": {
        "title": "Multicast Routes",
        "desc": "Отправка события в несколько маршрутов параллельно",
    },
    "express_send": {
        "title": "Express Send",
        "desc": "Отправка сообщения в Telegram бот",
    },
    "express_reply": {
        "title": "Express Reply",
        "desc": "Ответ на Telegram сообщение",
    },
    "notify": {
        "title": "Notify",
        "desc": "Уведомление в канал (email/slack/telegram)",
    },
}

# Иконки для UI (Emoji).
PROCESSOR_ICONS: dict[str, str] = {
    "log": "📋",
    "validate": "✅",
    "transform": "🔄",
    "dispatch_action": "🎯",
    "retry": "🔁",
    "redirect": "↗️",
    "windowed_dedup": "🗂️",
    "windowed_collect": "📥",
    "multicast_routes": "📡",
    "express_send": "📨",
    "express_reply": "📩",
    "notify": "🔔",
}

# Параметры каждого процессора для Visual-формы (Canvas-режим).
VISUAL_PROCESSORS: dict[str, list[str]] = {
    "log": ["level", "message"],
    "validate": ["schema"],
    "transform": ["expression"],
    "dispatch_action": ["action"],
    "retry": ["max_attempts", "delay"],
    "redirect": ["mode", "status_code", "target_url", "url_source", "source_key"],
    "windowed_dedup": ["key_from", "window_seconds", "mode"],
    "windowed_collect": [
        "key_from",
        "window_seconds",
        "dedup_by",
        "dedup_mode",
        "inject_as",
    ],
    "multicast_routes": ["route_ids", "strategy", "on_error", "timeout"],
    "express_send": ["bot", "chat_id_from", "body_from"],
    "express_reply": ["bot", "body_from"],
    "notify": ["channel", "to", "template"],
}


def default_yaml() -> str:
    """YAML-шаблон по умолчанию для нового маршрута.

    Возвращает минимальный, но валидный Pipeline-конфиг:
    ``route_id`` + ``source`` + ``description`` + один ``log`` шаг.
    """
    return (
        "route_id: my.route\n"
        "source: internal:my\n"
        "description: Новый маршрут\n"
        "processors:\n"
        "  - log:\n"
        "      level: info\n"
    )
