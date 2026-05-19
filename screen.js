(function() {
    const state = window.__remoteLibraryServerPlugin || {
        installed: false,
        settings: {},
        status: null,
        songs: [],
        activity: [],
        searchTimer: null,
    };
    window.__remoteLibraryServerPlugin = state;

    function esc(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function formatBytes(bytes) {
        const value = Number(bytes || 0);
        if (!value) return '';
        if (value >= 1024 * 1024 * 1024) return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
        if (value >= 1024 * 1024) return `${Math.round(value / 1024 / 1024)} MB`;
        if (value >= 1024) return `${Math.round(value / 1024)} KB`;
        return `${value} B`;
    }

    function toneClass(value) {
        if (value === 'running' || value === true || value === 'started') return 'text-green-300 border-green-500/30 bg-green-500/10';
        if (value === 'failed' || value === false) return 'text-red-300 border-red-500/30 bg-red-500/10';
        return 'text-gray-300 border-gray-800 bg-dark-800';
    }

    function setMessage(message, tone) {
        const node = document.getElementById('remote-library-server-message');
        if (!node) return;
        node.textContent = message || '';
        node.className = `mt-3 text-sm ${tone === 'error' ? 'text-red-300' : tone === 'success' ? 'text-green-300' : 'text-gray-400'}`;
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

    function statusCard(label, value, detail, tone) {
        return `
            <div class="rounded-lg border px-3 py-3 ${toneClass(tone)}">
                <div class="text-xs uppercase text-gray-500">${esc(label)}</div>
                <div class="mt-1 truncate text-sm font-semibold text-white">${esc(value || 'Unknown')}</div>
                <div class="mt-1 truncate text-xs text-gray-400">${esc(detail || '')}</div>
            </div>
        `;
    }

    function setForm(settings) {
        const values = {
            'rls-enabled': Boolean(settings.enabled),
            'rls-host': settings.host || '127.0.0.1',
            'rls-port': settings.port || 8765,
            'rls-source-name': settings.sourceName || '',
            'rls-public-url': settings.publicUrl || '',
        };
        for (const [id, value] of Object.entries(values)) {
            const input = document.getElementById(id);
            if (!input) continue;
            if (input.type === 'checkbox') input.checked = Boolean(value);
            else input.value = value;
        }
    }

    function readForm() {
        return {
            enabled: Boolean(document.getElementById('rls-enabled')?.checked),
            host: document.getElementById('rls-host')?.value.trim() || '127.0.0.1',
            port: Number(document.getElementById('rls-port')?.value || 8765),
            sourceName: document.getElementById('rls-source-name')?.value.trim() || '',
            publicUrl: document.getElementById('rls-public-url')?.value.trim() || '',
        };
    }

    function renderStatus() {
        const status = state.status || {};
        const source = status.source || {};
        const server = status.server || {};
        const subtitle = document.getElementById('remote-library-server-subtitle');
        if (subtitle) {
            subtitle.textContent = `${source.sourceName || 'Local source'} | ${source.songCount || 0} songs`;
        }
        const node = document.getElementById('remote-library-server-status');
        if (node) {
            node.innerHTML = [
                statusCard('Server', server.running ? 'Running' : 'Stopped', `${server.host || ''}:${server.port || ''}`, server.running),
                statusCard('Local URL', server.url || '', server.protocol || '', server.running ? 'running' : 'stopped'),
                statusCard('Source', source.sourceId || '', `${source.songCount || 0} songs`, source.libraryRootConfigured),
            ].join('');
        }
    }

    function renderSongs() {
        const node = document.getElementById('remote-library-server-songs');
        if (!node) return;
        if (!state.songs.length) {
            node.innerHTML = '<div class="rounded-lg border border-gray-800 bg-dark-800 px-3 py-3 text-sm text-gray-400">No songs found.</div>';
            return;
        }
        node.innerHTML = state.songs.slice(0, 50).map(song => `
            <div class="rounded-lg border border-gray-800 bg-dark-800 px-3 py-3">
                <div class="truncate text-sm font-semibold text-white">${esc(song.title || 'Untitled')}</div>
                <div class="truncate text-xs text-gray-500">${esc(song.artist || 'Unknown artist')}${song.sizeBytes ? ` | ${esc(formatBytes(song.sizeBytes))}` : ''}</div>
            </div>
        `).join('');
    }

    function renderActivity() {
        const node = document.getElementById('remote-library-server-activity');
        if (!node) return;
        if (!state.activity.length) {
            node.innerHTML = '<div class="rounded-lg border border-gray-800 bg-dark-800 px-3 py-3 text-sm text-gray-400">No activity yet.</div>';
            return;
        }
        node.innerHTML = state.activity.slice(0, 20).map(item => `
            <div class="rounded-lg border border-gray-800 bg-dark-800 px-3 py-3">
                <div class="flex items-center justify-between gap-3">
                    <div class="min-w-0 truncate text-sm text-gray-200">${esc(item.message || item.eventType)}</div>
                    <span class="rounded-full border px-2 py-1 text-xs ${toneClass(item.outcome)}">${esc(item.outcome || 'event')}</span>
                </div>
                <div class="mt-1 text-xs text-gray-500">${esc(item.createdAt || '')}</div>
            </div>
        `).join('');
    }

    function renderAll() {
        renderStatus();
        renderSongs();
        renderActivity();
    }

    async function refresh() {
        const query = encodeURIComponent(document.getElementById('rls-search')?.value || '');
        const [settings, status, songs, activity] = await Promise.all([
            api('/settings'),
            api('/status'),
            api(`/local-songs?q=${query}&pageSize=50`),
            api('/activity'),
        ]);
        state.settings = settings;
        state.status = status;
        state.songs = songs.songs || [];
        state.activity = activity.events || [];
        setForm(settings);
        renderAll();
    }

    async function save() {
        state.settings = await api('/settings', { method: 'POST', body: JSON.stringify(readForm()) });
        setMessage('Settings saved.', 'success');
        await refresh();
    }

    async function start() {
        await api('/start', { method: 'POST', body: JSON.stringify({}) });
        setMessage('Server started.', 'success');
        await refresh();
    }

    async function stop() {
        await api('/stop', { method: 'POST', body: JSON.stringify({}) });
        setMessage('Server stopped.', 'success');
        await refresh();
    }

    function installHandlers() {
        if (state.installed) return;
        state.installed = true;
        document.addEventListener('click', async event => {
            const target = event.target.closest('[data-rls-refresh],[data-rls-save],[data-rls-start],[data-rls-stop],[data-rls-open-screen]');
            if (!target) return;
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
        document.addEventListener('input', event => {
            if (!event.target.matches('#rls-search')) return;
            window.clearTimeout(state.searchTimer);
            state.searchTimer = window.setTimeout(() => {
                refresh().catch(error => setMessage(error.message || 'Search failed.', 'error'));
            }, 200);
        });
    }

    function init() {
        installHandlers();
        if (document.getElementById('remote-library-server-root')) {
            refresh().catch(error => setMessage(error.message || 'Refresh failed.', 'error'));
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();