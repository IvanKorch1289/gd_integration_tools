"""HTTP contract smoke на живом uvicorn-сервере (аудит 2026-11-20).

Юнит-тесты проверяют middleware изолированно (ASGI-вызовы), но HTTP-контракт
в проде формируется сервером: заголовки кэша, условный GET, SSE-стриминг и
сжатие ведут себя под h11 иначе, чем в тестовых вызовах. Этот тест поднимает
настоящий сервер с реальной цепочкой middleware проекта и проверяет контракт
настоящим HTTP-клиентом.

Обёртка над ``tools/checks/http_contract_smoke.py``: скрипт поднимает сервер
в фоновом потоке, выполняет проверки и останавливает сервер. Тест падает,
если хотя бы одна проверка не прошла — то есть если HTTP-контракт нарушен.

Проверки покрывают дефекты аудита §3.1-3.2: политика кэша (``public``
недопустим для персонализированного ответа, политика endpoint'а не
перетирается), инкрементальная доставка SSE, целостность сжатого тела,
пропуск больших ответов мимо кэша и отклонение несовпадения tenant.
"""

from __future__ import annotations

import pytest

from tools.checks import http_contract_smoke

pytestmark = [pytest.mark.smoke, pytest.mark.integration]


class TestHttpContractSmoke:
    """HTTP-контракт на реальном сервере."""

    @pytest.mark.parametrize(
        "argv", ([], ["--server", "granian"]), ids=("uvicorn", "granian")
    )
    def test_http_contract_smoke_passes(
        self, capsys: pytest.CaptureFixture[str], argv: list[str]
    ) -> None:
        """Все проверки HTTP-контракта проходят на живом сервере.

        Проверяется оба рантайма: uvicorn (dev) и Granian (прод, ADR-0059) —
        поведение SSE, gzip и условного GET зависит от HTTP-стека сервера,
        а не только от middleware (аудит 2026-11-23, ЭТАП 2.3).

        Args:
            capsys: Захват вывода.
            argv: Аргументы инструмента (рантайм).
        """
        code = http_contract_smoke.main(argv)
        captured = capsys.readouterr()
        assert code == 0, captured.out + captured.err
        assert "Все проверки пройдены" in captured.out
