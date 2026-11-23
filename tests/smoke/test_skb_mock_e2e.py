"""Детерминированный mock-E2E бизнес-workflow'а СКБ (аудит 2026-11-20).

Обёртка над ``tools/checks/skb_mock_e2e.py``: скрипт поднимает mock внешнего
сервиса СКБ и приложение с реальным SKB-роутером, после чего прогоняет
workflow «создать заказ → получить id → дождаться результата → скачать
документ» и проверяет идемпотентность и recovery.

Тест падает, если workflow не пройден, — то есть это блокирующая
проверка целостности бизнес-пути, а не «зелёный фон».
"""

from __future__ import annotations

import pytest

from tools.checks import skb_mock_e2e

pytestmark = [pytest.mark.smoke, pytest.mark.integration]


class TestSkbMockE2E:
    """Бизнес-workflow СКБ на детерминированном mock'е."""

    def test_business_workflow_passes(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Полный workflow проходит: заказ → результат → документ.

        Args:
            capsys: Захват вывода.
        """
        code = skb_mock_e2e.main([])
        captured = capsys.readouterr()
        assert code == 0, captured.out + captured.err
        assert "Workflow пройден полностью" in captured.out
