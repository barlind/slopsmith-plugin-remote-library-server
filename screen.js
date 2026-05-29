(function() {
    const state = window.__remoteLibraryServerPlugin || {
        installed: false,
        settings: {},
        status: null,
        defaults: {},
        loading: false,
        busyAction: '',
        lastError: '',
    };
    window.__remoteLibraryServerPlugin = state;
    if (typeof state.loading !== 'boolean') state.loading = false;
    if (typeof state.busyAction !== 'string') state.busyAction = '';
    if (typeof state.lastError !== 'string') state.lastError = '';

    function esc(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function setMessage(message, tone) {
        const node = document.getElementById('remote-library-server-message');
        if (!node) return;
        node.textContent = message || '';
        node.className = `mt-3 text-sm ${tone === 'error' ? 'text-red-300' : tone === 'success' ? 'text-green-300' : 'text-gray-400'}`;
    }

    function setBusyState(next = {}) {
        if (typeof next.loading === 'boolean') state.loading = next.loading;
        if (typeof next.busyAction === 'string') state.busyAction = next.busyAction;
        syncActionButtons();
    }

    function syncActionButtons() {
        const busy = state.loading || !!state.busyAction;
        document.querySelectorAll('[data-rls-refresh],[data-rls-save],[data-rls-start],[data-rls-stop]').forEach(button => {
            button.disabled = busy;
            button.classList.toggle('opacity-60', busy);
            button.classList.toggle('cursor-not-allowed', busy);
        });
    }

    async function api(path, options) {
        const response = await fetch(`/api/plugins/remote_library_server${path}`, {
            headers: { 'Content-Type': 'application/json' },
            ...(options || {}),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || data.error || response.statusText);
        return data;
    }

    function defaultValue(key) {
        const fallback = { host: '127.0.0.1', port: 8765, sourceName: '' };
        return state.defaults[key] || fallback[key] || '';
    }

    function setForm(settings) {
        const values = {
            'rls-enabled': Boolean(settings.enabled),
            'rls-share-nam-tone-assets': Boolean(settings.shareNamToneAssets),
            'rls-source-name': settings.sourceName || '',
            'rls-host': settings.host || '',
            'rls-port': settings.port || '',
        };
        const placeholders = {
            'rls-source-name': defaultValue('sourceName'),
            'rls-host': defaultValue('host'),
            'rls-port': defaultValue('port'),
        };
        for (const [id, value] of Object.entries(values)) {
            const input = document.getElementById(id);
            if (!input) continue;
            if (input.type === 'checkbox') input.checked = Boolean(value);
            else input.value = value;
            if (placeholders[id]) input.placeholder = String(placeholders[id]);
        }
    }

    function readForm() {
        return {
            enabled: Boolean(document.getElementById('rls-enabled')?.checked),
            shareNamToneAssets: Boolean(document.getElementById('rls-share-nam-tone-assets')?.checked),
            sourceName: document.getElementById('rls-source-name')?.value.trim() || defaultValue('sourceName'),
            host: document.getElementById('rls-host')?.value.trim() || defaultValue('host'),
            port: Number(document.getElementById('rls-port')?.value || defaultValue('port')),
        };
    }

    function powerIcon() {
        return '<svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v9m6.36-6.36a9 9 0 1 1-12.72 0"/></svg>';
    }

    function renderStatus() {
        const status = state.status || {};
        const server = status.server || {};
        const source = status.source || {};
        const scan = status.scan || {};
        const running = Boolean(server.running);
        const waiting = Boolean(server.waitingForScan);
        const node = document.getElementById('remote-library-server-status');
        const subtitle = document.getElementById('remote-library-server-subtitle');
        const stateLabel = state.loading && !state.status ? 'Loading...' : waiting ? 'Waiting for library scan' : running ? 'Running' : 'Stopped';
        const detail = waiting
            ? `Scan ${scan.stage || 'starting'}${scan.total ? ` ${scan.done || 0}/${scan.total}` : ''}`
            : running
                ? server.url || ''
                : 'Direct server is not listening';

        if (subtitle) {
            subtitle.textContent = state.lastError && !state.status
                ? 'Server status unavailable'
                : `${source.sourceName || defaultValue('sourceName') || 'Remote Library'} | ${source.songCount || 0} songs`;
        }
        if (!node) return;
        if (state.lastError && !state.status) {
            node.innerHTML = `
                <div class="rounded-lg border border-red-500/30 bg-red-500/10 p-4">
                    <div class="text-xs uppercase text-red-200">Server</div>
                    <div class="mt-1 text-lg font-semibold text-white">Unavailable</div>
                    <div class="mt-1 text-sm text-red-200">${esc(state.lastError)}</div>
                </div>
            `;
            return;
        }
        const panelClass = running
            ? 'border-green-500/30 bg-green-500/10'
            : waiting
                ? 'border-amber-500/30 bg-amber-500/10'
                : 'border-red-500/30 bg-red-500/10';
        const buttonAction = running ? 'stop' : 'start';
        const buttonClass = running
            ? 'bg-red-500/20 text-red-100 hover:bg-red-500/30'
            : 'bg-green-500/20 text-green-100 hover:bg-green-500/30';
        node.innerHTML = `
            <div class="rounded-lg border ${panelClass} p-4">
                <div class="flex items-center justify-between gap-4">
                    <div class="min-w-0">
                        <div class="text-xs uppercase text-gray-400">Server</div>
                        <div class="mt-1 text-2xl font-semibold text-white">${esc(stateLabel)}</div>
                        <div class="mt-1 truncate text-sm text-gray-300">${esc(detail)}</div>
                    </div>
                    <button class="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-full ${buttonClass} transition" data-rls-${buttonAction} aria-label="${running ? 'Stop server' : 'Start server'}" title="${running ? 'Stop server' : 'Start server'}">
                        ${powerIcon()}
                    </button>
                </div>
            </div>
        `;
        syncActionButtons();
    }

    async function refresh() {
        state.lastError = '';
        setBusyState({ loading: true, busyAction: 'refresh' });
        renderStatus();
        try {
            const [settings, status] = await Promise.all([
                api('/settings'),
                api('/status'),
            ]);
            state.settings = settings;
            state.status = status;
            state.defaults = status.defaults || state.defaults || {};
            setForm(settings);
        } catch (error) {
            state.lastError = error.message || 'Refresh failed.';
            throw error;
        } finally {
            setBusyState({ loading: false, busyAction: '' });
            renderStatus();
        }
    }

    async function save() {
        setBusyState({ busyAction: 'save' });
        try {
            await api('/settings', { method: 'POST', body: JSON.stringify(readForm()) });
            setMessage('Settings saved.', 'success');
            await refresh();
        } finally {
            setBusyState({ busyAction: '' });
        }
    }

    async function start() {
        setBusyState({ busyAction: 'start' });
        try {
            await api('/start', { method: 'POST', body: JSON.stringify({}) });
            setMessage('Server started.', 'success');
            await refresh();
        } finally {
            setBusyState({ busyAction: '' });
        }
    }

    async function stop() {
        setBusyState({ busyAction: 'stop' });
        try {
            await api('/stop', { method: 'POST', body: JSON.stringify({}) });
            setMessage('Server stopped.', 'success');
            await refresh();
        } finally {
            setBusyState({ busyAction: '' });
        }
    }

    function installHandlers() {
        if (state.installed) return;
        state.installed = true;
        document.addEventListener('click', async event => {
            const target = event.target.closest('[data-rls-refresh],[data-rls-save],[data-rls-start],[data-rls-stop],[data-rls-open-screen]');
            if (!target || target.disabled) return;
            try {
                if (target.matches('[data-rls-refresh]')) await refresh();
                if (target.matches('[data-rls-save]')) await save();
                if (target.matches('[data-rls-start]')) await start();
                if (target.matches('[data-rls-stop]')) await stop();
                if (target.matches('[data-rls-open-screen]')) window.location.hash = '#remote-library-server';
            } catch (error) {
                setMessage(error.message || 'Action failed.', 'error');
            }
        });
    }

    function init() {
        installHandlers();
        if (document.getElementById('remote-library-server-root')) {
            setBusyState({ loading: true });
            renderStatus();
            refresh().catch(error => setMessage(error.message || 'Refresh failed.', 'error'));
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();