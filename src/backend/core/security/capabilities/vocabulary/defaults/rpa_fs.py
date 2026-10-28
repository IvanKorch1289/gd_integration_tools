"""RPA / FS / connector capabilities (Cycle 172, Wave 5).

Audit 2026-10-22 (HIGH-16) обнаружил, что ``rpa.directory.scan`` не
зарегистрирован в vocabulary → ``CapabilityGate.check()`` падал с
``CapabilityNotFoundError`` → deny-by-default → ``exchange.stop()`` на
каждом вызове. Реальный размах оказался шире: **53** capability,
на которые ссылаются ``required_capability`` процессоров, отсутствовали
в vocabulary — весь RPA-сегмент (``rpa.*``), плюс connector-имена
(``s3.write``, ``http.send``, ``mqtt.write``, ...).

Список ниже — не выдуман: он извлечён из
``required_capability: ClassVar[str | None] = "..."`` по всему
``src/backend``. Регистрация даёт возможность **объявить** capability в
``route.toml`` / ``plugin.toml`` (иначе validator режет по грамматике)
и проверять её в рантайме.

Naming: ``<namespace>.<resource>.<verb>`` — например ``rpa.file.list``.
Грамматика capability расширена в ``models.py`` до 2+ сегментов
(Cycle 172, Wave 5).

Scope: для ``rpa.*`` scope — glob по пути/цели операции (например
``/data/incoming/*.csv``); для коннекторов — ресурс/топик. Матчер
``path_glob`` (sep='/') для файловых и ``dot_glob`` для остальных.
"""

from __future__ import annotations

from src.backend.core.security.capabilities.matchers import (
    GlobScopeMatcher,
    SegmentedGlobMatcher,
)
from src.backend.core.security.capabilities.vocabulary.models import CapabilityDef
from src.backend.core.security.capabilities.vocabulary.vocabulary import (
    CapabilityVocabulary,
)

__all__ = ("register",)

_dot_glob = GlobScopeMatcher()
_path_glob = SegmentedGlobMatcher(sep="/")

# RPA-операции: имя → краткое описание. Порядок не важен.
_RPA_CAPABILITIES: dict[str, str] = {
    # Файловая система
    "rpa.archive.execute": "Создание/распаковка архива (tar/zip) RPA-процессором.",
    "rpa.directory.scan": "Сканирование директории с фильтром (DirectoryScan/FilteredDirectoryScan).",
    "rpa.file.csv.read": "Чтение CSV-файла RPA-процессором.",
    "rpa.file.csv.write": "Запись CSV-файла RPA-процессором.",
    "rpa.file.delete": "Удаление файла RPA-процессором.",
    "rpa.file.list": "Листинг файлов в директории RPA-процессором.",
    "rpa.file.move": "Перемещение/переименование файла RPA-процессором.",
    "rpa.file.watch": "Наблюдение за файловой системой через watchdog RPA-процессором.",
    # Документы
    "rpa.excel.read": "Чтение XLSX-документа RPA-процессором.",
    "rpa.pdf.merge": "Объединение PDF-документов RPA-процессором.",
    "rpa.pdf.read": "Чтение PDF-документа RPA-процессором.",
    "rpa.word.read": "Чтение DOCX-документа RPA-процессором.",
    "rpa.word.write": "Запись DOCX-документа RPA-процессором.",
    # Почта
    "rpa.email.extract": "Извлечение вложений из письма RPA-процессором.",
    "rpa.email.read": "Чтение письма по IMAP RPA-процессором.",
    "rpa.email.send": "Отправка письма по SMTP RPA-процессором.",
    # Браузер / desktop
    "rpa.browser.click": "Клик по элементу страницы (rpa_browser).",
    "rpa.browser.extract": "Извлечение данных со страницы (rpa_browser).",
    "rpa.browser.fill": "Заполнение полей формы (rpa_browser).",
    "rpa.browser.launch": "Запуск браузера (rpa_browser).",
    "rpa.browser.navigate": "Навигация по URL (rpa_browser).",
    "rpa.browser.pdf": "Сохранение страницы в PDF (rpa_browser).",
    "rpa.browser.screenshot": "Скриншот страницы (rpa_browser).",
    "rpa.browser.wait": "Ожидание элемента на странице (rpa_browser).",
    "rpa.desktop.automate": "Автоматизация desktop-приложений (pyautogui).",
    "rpa.desktop.invoke": "Вызов desktop-приложения RPA-процессором.",
    "rpa.keystroke.replay": "Воспроизведение клавиатурной последовательности.",
    # Крипто / хеши / шаблоны / regex
    "rpa.crypto.decrypt": "Расшифровка данных RPA-процессором.",
    "rpa.crypto.encrypt": "Шифрование данных RPA-процессором.",
    "rpa.hash.compute": "Вычисление хеша файла/данных RPA-процессором.",
    "rpa.regex.execute": "Применение regex к тексту RPA-процессором.",
    "rpa.template.render": "Рендеринг шаблона RPA-процессором.",
    # Изображения / OCR
    "rpa.image.ocr": "Распознавание текста на изображении (OCR).",
    "rpa.image.resize": "Изменение размера изображения RPA-процессором.",
    # Сеть / shell / передача файлов
    "rpa.appium.invoke": "Вызов Appium-драйвера (мобильная автоматизация).",
    "rpa.citrix.invoke": "Вызов Citrix-клиента RPA-процессором.",
    "rpa.ftp.upload": "Выгрузка файла по FTP/SFTP RPA-процессором.",
    "rpa.http.request": "HTTP-запрос из RPA-процессора.",
    "rpa.shell.exec": "Выполнение shell-команды RPA-процессором.",
    "rpa.terminal3270.invoke": "Вызов 3270-терминала RPA-процессором.",
    # AI-решения
    "rpa.ai.decide": "AI-принятие решения внутри RPA-сценария.",
}

# Коннекторы и прочие интеграционные операции.
_CONNECTOR_CAPABILITIES: dict[str, str] = {
    "agent.run": "Запуск AI-агента (langgraph_agent).",
    "ai.tool.dispatch": "Диспетчеризация вызова AI-инструмента.",
    "data.export": "Выгрузка данных во внешний формат (export-процессор).",
    "event.publish": "Публикация события в шину (integration-процессор).",
    "llm.stream": "Streaming-вызов LLM (streaming_llm-процессор).",
    "mcp.call": "Вызов MCP-инструмента (mcp_tool-процессор).",
    "secret.read": "Чтение секрета из Vault (vault_secret-процессор).",
    "security.waf.check": "Проверка запроса WAF-движком.",
    "web_search.perplexity.invoke": "Веб-поиск через Perplexity.",
    "web_search.tavily.invoke": "Веб-поиск через Tavily.",
    "workflow.convert.format": "Конвертация формата в workflow-процессоре.",
    "workflow.subprocess.invoke": "Запуск subprocess в workflow-процессоре.",
}


def register(vocab: CapabilityVocabulary) -> None:
    """Зарегистрировать RPA/FS/connector capability.

    Args:
        vocab: :class:`CapabilityVocabulary` — registry для регистрации.

    """
    for name, description in _RPA_CAPABILITIES.items():
        vocab.register(
            CapabilityDef(
                name=name,
                matcher=_path_glob if ".file." in name or ".directory." in name else _dot_glob,
                description=description,
            )
        )
    for name, description in _CONNECTOR_CAPABILITIES.items():
        vocab.register(
            CapabilityDef(
                name=name,
                matcher=_dot_glob,
                description=description,
            )
        )
