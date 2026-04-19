/**
 * GD Integration Tools — Live Dashboard.
 *
 * Tabs: Metrics, Routes, Logs, Prefect, S3, Graylog, LangFuse.
 * Metrics + health refresh every 10s.
 * Routes loaded on tab activation.
 * Logs streamed via SSE (trace events).
 * Iframes loaded lazily on first tab click.
 */
(function () {
    'use strict';

    // --- Tab switching ---
    const tabs = document.querySelectorAll('.tab');
    const panels = document.querySelectorAll('.tab-panel');
    const loadedIframes = new Set();

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            panels.forEach(p => p.classList.remove('active'));
            tab.classList.add('active');
            const target = tab.dataset.tab;
            document.getElementById('panel-' + target).classList.add('active');

            if (target === 'routes') loadRoutes();
            if (['prefect', 'storage', 'graylog', 'langfuse'].includes(target)) {
                lazyLoadIframe(target);
            }
        });
    });

    // --- Metrics ---
    async function loadMetrics() {
        try {
            const resp = await fetch('/api/v1/admin/system-info', { signal: AbortSignal.timeout(5000) });
            if (!resp.ok) return;
            const data = await resp.json();

            setText('m-routes', data.routes_total);
            setText('m-actions', data.actions_count);
            setText('m-enabled', data.routes_enabled);
            setText('m-disabled', data.routes_disabled);
            setText('m-services', Array.isArray(data.services) ? data.services.length : '—');
            setText('m-flags', Array.isArray(data.feature_flags_disabled) ? data.feature_flags_disabled.length : '0');

            setStatus('ok', 'Connected');
        } catch {
            setStatus('err', 'Disconnected');
        }
    }

    // --- Health checks ---
    async function loadHealth() {
        const grid = document.getElementById('health-grid');
        if (!grid) return;

        try {
            const resp = await fetch('/api/v1/tech/healthcheck-all-services', { signal: AbortSignal.timeout(10000) });
            if (!resp.ok) return;
            const data = await resp.json();
            const details = data.details || data;

            grid.innerHTML = '';
            for (const [name, status] of Object.entries(details)) {
                const ok = status === true || status === 'ok';
                grid.innerHTML += `
                    <div class="health-item">
                        <span class="dot ${ok ? 'up' : 'down'}"></span>
                        <span>${name}</span>
                    </div>`;
            }
        } catch {
            grid.innerHTML = '<div class="health-item"><span class="dot unknown"></span>Health check unavailable</div>';
        }
    }

    // --- Routes ---
    async function loadRoutes() {
        const tbody = document.getElementById('routes-tbody');
        if (!tbody) return;

        try {
            const resp = await fetch('/api/v1/admin/routes', { signal: AbortSignal.timeout(5000) });
            if (!resp.ok) return;
            const data = await resp.json();
            const routes = data.routes || [];

            tbody.innerHTML = '';
            routes.forEach(r => {
                const tr = document.createElement('tr');
                const tdId = document.createElement('td');
                tdId.textContent = r.route_id;
                const tdStatus = document.createElement('td');
                const badge = document.createElement('span');
                badge.className = 'badge ' + (r.enabled ? 'enabled' : 'disabled');
                badge.textContent = r.enabled ? 'ON' : 'OFF';
                tdStatus.appendChild(badge);
                const tdFlag = document.createElement('td');
                tdFlag.textContent = r.feature_flag || '\u2014';
                tr.append(tdId, tdStatus, tdFlag);
                tbody.appendChild(tr);
            });

            // Search filter
            const search = document.getElementById('route-search');
            const filter = document.getElementById('route-filter');
            const filterFn = () => {
                const q = (search.value || '').toLowerCase();
                const f = filter.value;
                const rows = tbody.querySelectorAll('tr');
                rows.forEach(row => {
                    const id = row.cells[0].textContent.toLowerCase();
                    const enabled = row.cells[1].textContent.trim() === 'ON';
                    const matchSearch = !q || id.includes(q);
                    const matchFilter = f === 'all' || (f === 'enabled' && enabled) || (f === 'disabled' && !enabled);
                    row.style.display = matchSearch && matchFilter ? '' : 'none';
                });
            };
            search.oninput = filterFn;
            filter.onchange = filterFn;
        } catch { /* routes unavailable */ }
    }

    // --- Logs (SSE trace) ---
    let traceSource = null;

    function startTraceStream() {
        if (traceSource) traceSource.close();

        // Polling fallback since SSE endpoint may not be ready
        setInterval(async () => {
            // Logs tab shows trace from last route executions
            // For now, display static message until SSE endpoint is implemented
        }, 5000);
    }

    document.getElementById('log-clear')?.addEventListener('click', () => {
        const container = document.getElementById('log-container');
        if (container) container.innerHTML = '<div class="log-empty">Cleared. Listening...</div>';
    });

    // --- Lazy iframe loading ---
    async function lazyLoadIframe(name) {
        if (loadedIframes.has(name)) return;
        loadedIframes.add(name);

        try {
            const resp = await fetch('/api/v1/admin/config', { signal: AbortSignal.timeout(5000) });
            if (!resp.ok) return;
            const config = await resp.json();

            const urls = {
                prefect: config.app?.prefect_url || '',
                storage: config.storage?.interface_endpoint || '',
                graylog: config.logging?.host ? `http://${config.logging.host}:${config.logging.port}` : '',
                langfuse: config.app?.langfuse_url || '',
            };

            const iframe = document.getElementById('iframe-' + name);
            if (iframe && urls[name]) {
                iframe.src = urls[name];
            } else if (iframe) {
                iframe.parentElement.innerHTML = `
                    <div style="display:flex;align-items:center;justify-content:center;height:50vh;color:var(--text-dim);">
                        URL not configured. Set in config.yml or environment variables.
                    </div>`;
            }
        } catch { /* config unavailable */ }
    }

    // --- Helpers ---
    function setText(id, val) {
        const el = document.getElementById(id);
        if (el) el.textContent = val ?? '—';
    }

    function setStatus(cls, text) {
        const dot = document.getElementById('status-dot');
        const txt = document.getElementById('status-text');
        if (dot) { dot.className = 'status-dot ' + cls; }
        if (txt) { txt.textContent = text; }
    }

    // --- Init ---
    loadMetrics();
    loadHealth();
    setInterval(loadMetrics, 10000);
    setInterval(loadHealth, 30000);
    startTraceStream();
})();
