"""Page metadata registry — used by setup_page() to auto-resolve icons.

S171 (S2 optimization): Single source of truth for page labels + icons.
Pages no longer need to pass icon — setup_page() looks it up here.
"""

from __future__ import annotations

# Mapping: filename (without .py) → {"title": str, "icon": str}
# Used by setup_page() for auto-resolve.
PAGE_METADATA: dict[str, dict[str, str]] = {
    "00_Главная": {"title": "Главная", "icon": ":material/home:"},
    "00_Вход": {"title": "Вход", "icon": ":material/login:"},
    "04_Обучение": {"title": "Обучение", "icon": ":material/school:"},
    "10_Заказы": {"title": "Заказы", "icon": ":material/receipt_long:"},
    "11_Маршруты": {"title": "Маршруты", "icon": ":material/route:"},
    "12_Логи": {"title": "Логи", "icon": ":material/article:"},
    "13_Конструктор_Cron": {"title": "Конструктор Cron", "icon": ":material/schedule:"},
    "14_Панель_Cron": {"title": "Панель Cron", "icon": ":material/event:"},
    "15_Оценка_стоимости_Workflow": {"title": "Оценка стоимости Workflow", "icon": ":material/payments:"},
    "16_Воркфлоу": {"title": "Воркфлоу", "icon": ":material/account_tree:"},
    "17_Replay_Воркфлоу": {"title": "Replay Воркфлоу", "icon": ":material/replay:"},
    "18_Версионирование_Воркфлоу": {"title": "Версионирование Воркфлоу", "icon": ":material/history:"},
    "19_Saga_Компенсации": {"title": "Saga Компенсации", "icon": ":material/undo:"},
    "20_AI_Чат": {"title": "AI Чат", "icon": ":material/robot_2:"},
    "21_AI_Обратная_связь": {"title": "AI Обратная связь", "icon": ":material/feedback:"},
    "22_RAG_Консоль": {"title": "RAG Консоль", "icon": ":material/search:"},
    "23_AI_Учёт_затрат": {"title": "AI Учёт затрат", "icon": ":material/attach_money:"},
    "30_DSL_Площадка": {"title": "DSL Площадка", "icon": ":material/code:"},
    "31_DSL_Визуальный_редактор": {"title": "DSL Визуальный редактор", "icon": ":material/draw:"},
    "32_DSL_Конструктор": {"title": "DSL Конструктор", "icon": ":material/build:"},
    "33_DSL_Шаблоны": {"title": "DSL Шаблоны", "icon": ":material/collections:"},
    "34_DSL_Отладчик": {"title": "DSL Отладчик", "icon": ":material/bug_report:"},
    "35_Мастер_генерации_кода": {"title": "Мастер генерации кода", "icon": ":material/auto_awesome:"},
    "36_Экспресс_боты": {"title": "Экспресс-боты", "icon": ":material/smart_toy:"},
    "37_API_Вызовы": {"title": "API Вызовы", "icon": ":material/api:"},
    "38_Галерея_блюпринтов": {"title": "Галерея блюпринтов", "icon": ":material/photo_library:"},
    "39_Консоль_вызовов": {"title": "Консоль вызовов", "icon": ":material/terminal:"},
    "41_Поиск": {"title": "Поиск", "icon": ":material/search:"},
    "43_Логи_в_реальном_времени": {"title": "Логи в реальном времени", "icon": ":material/monitoring:"},
    "45_Админ": {"title": "Админ", "icon": ":material/admin_panel_settings:"},
    "46_DSL_Пробный_прогон": {"title": "DSL Пробный прогон", "icon": ":material/play_arrow:"},
    "47_AI_Безопасность": {"title": "AI Безопасность", "icon": ":material/security:"},
    "48_Лаборатория_промптов": {"title": "Лаборатория промптов", "icon": ":material/science:"},
    "49_Реестр_моделей": {"title": "Реестр моделей", "icon": ":material/storage:"},
    "50_Фича_флаги": {"title": "Фича-флаги", "icon": ":material/flag:"},
    "51_Проверка_здоровья": {"title": "Проверка здоровья", "icon": ":material/health_and_safety:"},
    "52_Устойчивость": {"title": "Устойчивость", "icon": ":material/shield:"},
    "53_Монитор_очереди": {"title": "Монитор очереди", "icon": ":material/queue:"},
    "54_Replay_DLQ": {"title": "Replay DLQ", "icon": ":material/refresh:"},
    "55_Монитор_пула": {"title": "Монитор пула", "icon": ":material/pool:"},
    "56_Процессы": {"title": "Процессы", "icon": ":material/memory:"},
    "57_Файлы_S3": {"title": "Файлы S3", "icon": ":material/folder:"},
    "58_Шина_действий": {"title": "Шина действий", "icon": ":material/alt_route:"},
    "59_Отладчик_маршрутов": {"title": "Отладчик маршрутов", "icon": ":material/track_changes:"},
    "60_Админ_кеша": {"title": "Админ кеша", "icon": ":material/cached:"},
    "61_Журнал_аудита": {"title": "Журнал аудита", "icon": ":material/assignment:"},
    "62_Админ_схем": {"title": "Админ схем", "icon": ":material/schema:"},
    "63_Вики": {"title": "Вики", "icon": ":material/menu_book:"},
    "64_SQL_Админ": {"title": "SQL Админ", "icon": ":material/database:"},
    "65_Сервисы": {"title": "Сервисы", "icon": ":material/dns:"},
    "66_Логи_Воркфлоу": {"title": "Логи Воркфлоу", "icon": ":material/list_alt:"},
    "67_Задачи": {"title": "Задачи", "icon": ":material/work:"},
    "68_Маркетплейс_плагинов": {"title": "Маркетплейс плагинов", "icon": ":material/storefront:"},
    "70_Тенанты": {"title": "Тенанты", "icon": ":material/apartment:"},
    "71_Возможности": {"title": "Возможности", "icon": ":material/extension:"},
    "72_HITL_Панель": {"title": "HITL Панель", "icon": ":material/groups:"},
    "73_Просмотр_конфига": {"title": "Просмотр конфига", "icon": ":material/settings:"},
    "75_Мастер_загрузки_RAG": {"title": "Мастер загрузки RAG", "icon": ":material/upload_file:"},
    "76_Подключение_плагинов": {"title": "Подключение плагинов", "icon": ":material/extension:"},
    "77_Каталог_процессоров": {"title": "Каталог процессоров", "icon": ":material/category:"},
    "78_Плавная_деградация": {"title": "Плавная деградация", "icon": ":material/trending_down:"},
    "79_Редактор_профиля_устойчивости": {"title": "Редактор профиля устойчивости", "icon": ":material/tune:"},
    "80_Параллелизм_конвейера": {"title": "Параллелизм конвейера", "icon": ":material/linear_scale:"},
    "81_Адаптивная_RAG_панель": {"title": "Адаптивная RAG панель", "icon": ":material/auto_awesome:"},
    "83_Инспекция_тенанта": {"title": "Инспекция тенанта", "icon": ":material/fact_check:"},
    "85_Массовая_загрузка_RAG": {"title": "Массовая загрузка RAG", "icon": ":material/cloud_upload:"},
    "86_Аудит_использования_DSL": {"title": "Аудит использования DSL", "icon": ":material/summarize:"},
    "88_Тенантные_фича_флаги": {"title": "Тенантные фича-флаги", "icon": ":material/flag_circle:"},
    "95_Покрытие_EIP": {"title": "Покрытие EIP", "icon": ":material/checklist:"},
    "96_Монитор_зависших_сообщений": {"title": "Outbox Stuck Monitor", "icon": ":material/warning:"},
}


def get_page_metadata(filename: str) -> dict[str, str] | None:
    """Get metadata for a page by its filename (without .py)."""
    return PAGE_METADATA.get(filename)
