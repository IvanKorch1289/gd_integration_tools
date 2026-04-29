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

    /** Загружает URL сервисов из конфигурации и проставляет в карточки. */
    async function loadServiceLinks() {
        try {
            const resp = await fetch('/api/v1/admin/config', {
                signal: AbortSignal.timeout(5000),
            });
            if (!resp.ok) return;
            const config = await resp.json();
            const app = config.app || {};
            const logging = config.logging || {};
            const storage = config.storage || {};
            const queue = config.queue || {};

            const links = {
                'link-logs': logging.host ? `${logging.host}:${logging.port}` : '',
                'link-storage': storage.interface_endpoint || '',
                'link-queue': queue.queue_ui_url || '',
                'link-langfuse': app.langfuse_url || '',
                'link-langgraph': app.langgraph_url || '',
            };

            for (const [id, url] of Object.entries(links)) {
                const el = document.getElementById(id);
                if (el && url) el.href = url;
            }
        } catch { /* config недоступен — карточки останутся с href="#" */ }
    }

    // Инициализация
    updateTime();
    setInterval(updateTime, 1000);

    checkHealth();
    setInterval(checkHealth, 30000);

    loadServiceLinks();
})();
