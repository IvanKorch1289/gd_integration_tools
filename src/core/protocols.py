"""Протоколы (PEP 544) для ключевых абстракций приложения.

Модуль определяет `Protocol`-интерфейсы для основных семейств компонентов,
чтобы бизнес-логика не зависела от конкретных реализаций.

Все протоколы помечены ``@runtime_checkable`` для поддержки ``isinstance``-проверок
в DI-контейнере и тестах.

Использует PEP 695 generic-синтаксис (Python 3.12+) для параметризации.

Типовые сценарии замены реализаций:

* :class:`LLMProvider` — Claude → Gemini → Ollama → OpenWebUI → HuggingFace.
* :class:`BrowserAutomation` — Playwright → Selenium → Puppeteer.
* :class:`NotificationChannel` — Email → Express (BotX) → Telegram → SMS.
* :class:`Exporter` — CSV → Excel → PDF → JSON → Parquet.
* :class:`MemoryBackend` — Redis → Memcached → Postgres → in-memory.
* :class:`CDCStrategy` — polling → LogMiner (Oracle) → LISTEN/NOTIFY (PG).
* :class:`SoapClient` — zeep → suds → кастомный.
* :class:`PromptStore` — LangFuse → файловый реестр → БД.

Добавление новой реализации:

    1. Реализуйте методы протокола в конкретном классе.
    2. Зарегистрируйте реализацию в DI (``src/core/di.py``).
    3. Код-потребитель использует ``Protocol``-тип в сигнатуре, не конкретный класс.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Protocol, runtime_checkable

__all__ = (
    "LLMProvider",
    "BrowserAutomation",
    "NotificationChannel",
    "Exporter",
    "MemoryBackend",
    "CDCStrategy",
    "SoapClient",
    "PromptStore",
    "NotificationMessage",
    "CDCEvent",
)


# ──────────────────── AI / LLM ────────────────────


@runtime_checkable
class LLMProvider(Protocol):
    """Унифицированный интерфейс LLM-провайдера.

    Обеспечивает горячую замену моделей (Claude, Gemini, Ollama, OpenWebUI,
    HuggingFace) без изменения бизнес-кода.

    Метод :meth:`chat` возвращает raw dict-ответ провайдера (у каждого
    вендора своя структура — tool_calls, usage, finish_reason). Для получения
    чистого текста используйте :meth:`extract_text`. Такое разделение
    позволяет оставить единый Protocol без потери вендор-специфичных метаданных.

    Attributes:
        name: Человекочитаемое имя провайдера (для логов и метрик).
    """

    name: str

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Отправляет чат-запрос и возвращает raw dict-ответ провайдера."""
        ...

    def extract_text(self, response: dict[str, Any]) -> str:
        """Извлекает текстовое содержимое ответа из raw dict.

        У каждого вендора своя структура (OpenAI ``choices[0].message.content``,
        Anthropic ``content[0].text``, Gemini ``candidates[0].content.parts[0].text``).
        Метод инкапсулирует эту специфику.
        """
        ...

    async def embeddings(
        self, texts: list[str], *, model: str | None = None
    ) -> list[list[float]]:
        """Получает векторные представления для списка текстов."""
        ...


# ──────────────────── Web / Browser ────────────────────


@runtime_checkable
class BrowserAutomation(Protocol):
    """Интерфейс браузерной автоматизации (Playwright/Selenium/Puppeteer).

    Обеспечивает имитацию пользовательских действий на сайтах без API —
    например, кликнуть кнопку "Скачать договор" или заполнить форму.
    """

    async def navigate(self, url: str, *, wait_until: str = "load") -> None:
        """Переходит по URL и ожидает события ``wait_until``."""
        ...

    async def click(self, selector: str, *, timeout_ms: int = 30_000) -> None:
        """Кликает по элементу с CSS-селектором."""
        ...

    async def fill(self, selector: str, value: str) -> None:
        """Заполняет поле формы."""
        ...

    async def extract(self, selector: str) -> str:
        """Извлекает текст содержимого элемента."""
        ...

    async def screenshot(self, *, full_page: bool = False) -> bytes:
        """Делает скриншот страницы, возвращает PNG-байты."""
        ...

    async def download(self, selector: str) -> bytes:
        """Кликает по элементу и получает скачиваемый файл."""
        ...


# ──────────────────── Notifications ────────────────────


class NotificationMessage(Protocol):
    """Структура сообщения для отправки через :class:`NotificationChannel`."""

    subject: str
    body: str
    recipients: list[str]
    metadata: dict[str, Any]


@runtime_checkable
class NotificationChannel(Protocol):
    """Канал доставки уведомлений (email, Express, Telegram, SMS, push).

    Реализации регистрируются в :class:`NotificationHub`, который
    выбирает канал по правилам маршрутизации.
    """

    channel_name: str

    async def send(self, message: NotificationMessage) -> bool:
        """Отправляет сообщение. Возвращает True при успехе."""
        ...

    def supports_format(self, content_type: str) -> bool:
        """Поддерживает ли канал данный тип содержимого (text/plain, text/html, multipart)."""
        ...

    async def health(self) -> bool:
        """Проверяет работоспособность канала."""
        ...


# ──────────────────── Export / Format converters ────────────────────


@runtime_checkable
class Exporter[T](Protocol):
    """Преобразователь данных в конкретный формат (CSV/Excel/PDF/JSON/Parquet).

    Параметр ``T`` — тип входных данных (обычно ``list[dict]`` или DataFrame).
    """

    format_name: str
    mime_type: str

    def export(self, data: T, *, options: dict[str, Any] | None = None) -> bytes:
        """Возвращает сериализованное представление в целевом формате."""
        ...

    def get_extension(self) -> str:
        """Расширение файла без точки (``csv``, ``xlsx``, ``pdf``)."""
        ...


# ──────────────────── Memory (AI agent state) ────────────────────


@runtime_checkable
class MemoryBackend(Protocol):
    """Хранилище состояния AI-агента (Redis / Memcached / Postgres / in-memory)."""

    async def get_conversation(
        self, session_id: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Возвращает последние N сообщений диалога."""
        ...

    async def append_message(self, session_id: str, message: dict[str, Any]) -> None:
        """Добавляет сообщение в историю."""
        ...

    async def save_long_term(self, user_id: str, facts: dict[str, Any]) -> None:
        """Сохраняет долговременные факты о пользователе."""
        ...

    async def get_facts(self, user_id: str) -> dict[str, Any]:
        """Получает долговременные факты."""
        ...

    async def clear(self, session_id: str) -> None:
        """Очищает историю сессии."""
        ...


# ──────────────────── CDC (Change Data Capture) ────────────────────


class CDCEvent(Protocol):
    """Событие изменения данных, возвращаемое :class:`CDCStrategy`."""

    table: str
    operation: str  # INSERT / UPDATE / DELETE
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    timestamp: float


@runtime_checkable
class CDCStrategy(Protocol):
    """Стратегия Change Data Capture.

    Варианты реализации:

    * polling — опрос таблицы по timestamp-колонке (работает везде).
    * LISTEN/NOTIFY — PostgreSQL через ``asyncpg``.
    * LogMiner — Oracle через ``cx_Oracle``.
    * Debezium — внешний connector.
    """

    strategy_name: str

    async def subscribe(self, tables: list[str]) -> None:
        """Подписывается на изменения указанных таблиц."""
        ...

    def stream(self) -> AsyncIterator[CDCEvent]:
        """Асинхронный поток событий изменений."""
        ...

    async def stop(self) -> None:
        """Останавливает подписку."""
        ...


# ──────────────────── SOAP ────────────────────


@runtime_checkable
class SoapClient(Protocol):
    """Клиент SOAP (zeep / suds / кастомный).

    Инкапсулирует WSDL-загрузку и вызов методов.
    """

    async def call(self, method: str, **params: Any) -> Any:
        """Вызов SOAP-метода с параметрами."""
        ...

    def list_methods(self) -> list[str]:
        """Список доступных операций из WSDL."""
        ...


# ──────────────────── Prompt storage (AI) ────────────────────


@runtime_checkable
class PromptStore(Protocol):
    """Реестр промптов с версионированием (LangFuse / файловый / БД).

    Поддерживает:

    * получение промпта по имени и версии;
    * регистрацию новой версии;
    * history/rollback.
    """

    async def get(self, name: str, *, version: int | None = None) -> str:
        """Возвращает текст промпта. При ``version=None`` — последнюю версию."""
        ...

    async def register(
        self, name: str, content: str, *, metadata: dict[str, Any] | None = None
    ) -> int:
        """Регистрирует новую версию промпта, возвращает её номер."""
        ...

    async def list_versions(self, name: str) -> list[int]:
        """Список всех версий промпта."""
        ...
