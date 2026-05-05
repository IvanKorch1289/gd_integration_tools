"""Error Explainer — конвертация технических ошибок в понятные объяснения.

Превращает:
    ConnectionRefusedError('[Errno 111] Connection refused')

в:
    Что случилось: Не удалось подключиться к сервису.
    Почему: Сервис недоступен (не запущен / неверный адрес / заблокирован файрволом).
    Как исправить:
    1. Проверьте запущен ли сервис: systemctl status postgres
    2. Проверьте адрес в config_profiles/<APP_PROFILE>.yml (database.host)
    3. Проверьте доступность порта: telnet <host> 5432
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ("ErrorExplainer", "ExplainedError", "explain_error", "error_explainer")


@dataclass(slots=True)
class ExplainedError:
    title: str
    what_happened: str
    why: str
    how_to_fix: list[str]
    original: str = ""
    docs_url: str = ""


_ERROR_PATTERNS: dict[str, ExplainedError] = {
    "ConnectionRefusedError": ExplainedError(
        title="Сервис недоступен",
        what_happened="Не удалось подключиться к сервису — соединение отклонено",
        why="Сервис не запущен, неверный адрес/порт, или заблокирован файрволом",
        how_to_fix=[
            "Проверьте запущен ли сервис",
            "Проверьте host/port в config_profiles/<APP_PROFILE>.yml",
            "Проверьте доступность сети: telnet <host> <port>",
        ],
        docs_url="docs/TROUBLESHOOTING.md#connection-refused",
    ),
    "TimeoutError": ExplainedError(
        title="Превышен таймаут",
        what_happened="Операция не завершилась за отведённое время",
        why="Сервис перегружен, медленная сеть, или неправильно настроен таймаут",
        how_to_fix=[
            "Увеличьте таймаут в настройках",
            "Проверьте нагрузку на внешний сервис",
            "Разбейте большой запрос на батчи",
        ],
    ),
    "IntegrityError": ExplainedError(
        title="Нарушение целостности данных",
        what_happened="Не удалось сохранить данные в БД",
        why="Дубликат уникального поля, отсутствует связанный объект, или NOT NULL нарушен",
        how_to_fix=[
            "Проверьте не существует ли уже запись с таким же ключом",
            "Убедитесь что все обязательные поля заполнены",
            "Проверьте foreign keys",
        ],
    ),
    "ValidationError": ExplainedError(
        title="Ошибка валидации данных",
        what_happened="Входные данные не прошли проверку",
        why="Данные не соответствуют Pydantic-схеме",
        how_to_fix=[
            "Проверьте структуру body запроса",
            "Убедитесь что все обязательные поля переданы",
            "Проверьте типы данных (string vs int)",
        ],
    ),
    "KeyError": ExplainedError(
        title="Отсутствует обязательное поле",
        what_happened="Попытка обратиться к несуществующему ключу в словаре",
        why="В данных нет ожидаемого поля",
        how_to_fix=[
            "Проверьте структуру входных данных",
            "Используйте .get() с default вместо [key]",
            "Добавьте ValidateProcessor в начало pipeline",
        ],
    ),
    "RouteDisabledError": ExplainedError(
        title="Маршрут отключён",
        what_happened="Маршрут заблокирован feature-флагом",
        why="Feature flag для этого маршрута находится в состоянии disabled",
        how_to_fix=[
            "Включите feature flag через админку",
            "Проверьте runtime_state.disabled_feature_flags",
            "Или запустите action напрямую без DSL",
        ],
    ),
    "CircuitBreakerOpenError": ExplainedError(
        title="Circuit Breaker открыт",
        what_happened="Сервис временно заблокирован из-за серии ошибок",
        why="Защитный механизм активировался после превышения порога ошибок",
        how_to_fix=[
            "Подождите recovery_timeout (обычно 30 сек)",
            "Проверьте логи основной ошибки выше",
            "Устраните причину ошибок (недоступный сервис, неверный ключ)",
        ],
    ),
    "InvalidSignatureError": ExplainedError(
        title="Неверная подпись webhook",
        what_happened="HMAC-подпись не совпадает или timestamp вне окна",
        why="Неверный secret key, подделанный запрос, или рассинхронизация времени",
        how_to_fix=[
            "Проверьте что используется правильный shared secret",
            "Синхронизируйте время: ntpdate -u pool.ntp.org",
            "Проверьте что payload не был модифицирован",
        ],
    ),
}


class ErrorExplainer:
    """Превращает технические ошибки в понятные объяснения."""

    def explain(self, exc: Exception | str) -> ExplainedError:
        """Объясняет ошибку на русском.

        Args:
            exc: Exception или её строковое представление.

        Returns:
            ExplainedError с title/what/why/how_to_fix.
        """
        if isinstance(exc, Exception):
            error_type = type(exc).__name__
            error_msg = str(exc)
        else:
            error_msg = str(exc)
            error_type = "UnknownError"
            for pattern in _ERROR_PATTERNS:
                if pattern.lower() in error_msg.lower():
                    error_type = pattern
                    break

        explanation = _ERROR_PATTERNS.get(error_type)
        if explanation is None:
            explanation = self._fallback_explanation(error_type, error_msg)

        return ExplainedError(
            title=explanation.title,
            what_happened=explanation.what_happened,
            why=explanation.why,
            how_to_fix=explanation.how_to_fix,
            original=f"{error_type}: {error_msg}",
            docs_url=explanation.docs_url,
        )

    def _fallback_explanation(self, error_type: str, msg: str) -> ExplainedError:
        return ExplainedError(
            title=f"Ошибка: {error_type}",
            what_happened=msg[:200],
            why="Подробное объяснение не доступно — см. логи",
            how_to_fix=[
                "Проверьте логи приложения",
                "Посмотрите trace в /api/v1/admin/traces",
                "Обратитесь в чат разработчиков",
            ],
        )

    def register(self, error_type: str, explanation: ExplainedError) -> None:
        """Регистрирует кастомное объяснение."""
        _ERROR_PATTERNS[error_type] = explanation


error_explainer = ErrorExplainer()


def explain_error(exc: Exception | str) -> ExplainedError:
    """Shortcut для глобального explainer."""
    return error_explainer.explain(exc)
