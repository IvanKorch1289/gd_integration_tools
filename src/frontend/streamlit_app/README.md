# GD Integration Tools — Streamlit Developer Portal

Интерфейс разработчика для мониторинга и управления интеграционной шиной.

## Структура

```
streamlit_app/
├── app.py                  # Главный entrypoint
├── config.py               # Конфигурация Streamlit
├── api_clients/            # API клиенты для backend
│   ├── base.py             # Базовый HTTP клиент
│   ├── admin.py            # Admin API
│   ├── orders.py           # Orders API
│   ├── workflows.py        # Workflows API
│   └── ...
├── components/             # Переиспользуемые UI компоненты
├── pages/                  # Streamlit pages (нумерация 00-99)
│   ├── 00_Home.py          # Dashboard
│   ├── 10_Orders.py        # Orders management
│   ├── 20_AI_Chat.py       # AI чат
│   ├── 30_DSL_*.py         # DSL инструменты
│   ├── 50_ADM*.py          # Admin панели
│   └── ...
├── services/               # Бизнес-логика для UI
├── shared/                 # Общие утилиты
└── hooks/                  # Streamlit hooks
```

## Страницы (69 штук)

| Диапазон | Категория |
|----------|-----------|
| 00-09 | Home, Onboarding |
| 10-19 | Orders, Routes, Logs, Cron, Workflows |
| 20-29 | AI Chat, RAG, Cost Tracking |
| 30-39 | DSL Playground, Visual Editor, Builder, Templates |
| 40-49 | (reserved) |
| 50-59 | Admin: Action Bus, Feature Flags, Tenants |
| 60-69 | Wiki, Plugins, MCP, Workflow Logs |
| 70-79 | (reserved) |
| 80-89 | Observability, Metrics |
| 90-99 | Outbox Monitor, System Info |

## Запуск

```bash
# Из корня проекта
make run-streamlit

# Или напрямую
cd src/frontend/streamlit_app
streamlit run app.py
```

## API Clients

Frontend использует API клиенты (`api_clients/`) для взаимодействия с backend:

```python
from api_clients.base import BaseAPIClient
from api_clients.orders import OrdersClient

client = BaseAPIClient(base_url="http://localhost:8000")
orders = OrdersClient(client)
data = await orders.list_orders()
```

## Архитектура

- **API-first**: Все данные берутся через REST API (не прямые импорты backend)
- **Компоненты**: Переиспользуемые UI элементы в `components/`
- **Hooks**: Кастомные Streamlit hooks в `hooks/`

## Известные ограничения

1. **40 backend imports** — часть страниц использует прямые импорты из `src/backend/` (архитектурное нарушение). Планируется миграция на API клиенты.
2. **Нет unit-тестов** — тестирование через ручное тестирование.
