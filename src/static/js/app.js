/**
 * GD Integration Tools — минимальный JS для главной страницы.
 * Динамический health check и отображение времени.
 */

(function () {
    'use strict';

    const healthDot = document.getElementById('health-dot');
    const healthText = document.getElementById('health-text');
    const timeEl = document.getElementById('current-time');

    /** Обновляет отображение текущего времени. */
    function updateTime() {
        if (!timeEl) return;
        const now = new Date();
        timeEl.textContent = now.toLocaleString('ru-RU', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
        });
    }

    /** Проверяет health endpoint и обновляет индикатор. */
    async function checkHealth() {
        if (!healthDot || !healthText) return;

        try {
            const response = await fetch('/api/v1/tech/healthcheck', {
                method: 'GET',
                signal: AbortSignal.timeout(5000),
            });

            if (response.ok) {
                healthDot.className = 'health-dot';
                healthText.textContent = 'Система работает';
            } else {
                healthDot.className = 'health-dot degraded';
                healthText.textContent = 'Частичная деградация';
            }
        } catch {
            healthDot.className = 'health-dot unhealthy';
            healthText.textContent = 'Система недоступна';
        }
    }

    // Инициализация
    updateTime();
    setInterval(updateTime, 1000);

    checkHealth();
    setInterval(checkHealth, 30000);
})();
