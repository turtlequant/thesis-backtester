/**
 * API client utilities for the desktop frontend.
 */

const API_BASE = window.location.origin;

/**
 * Make an API request with error handling.
 */
async function apiFetch(path, options = {}) {
    const url = `${API_BASE}${path}`;
    const defaults = {
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
    };
    const merged = { ...defaults, ...options };

    let response;
    try {
        response = await fetch(url, merged);
    } catch (error) {
        throw new Error(`网络连接失败：${error.message || String(error)}`);
    }

    if (!response.ok) {
        let detail = `HTTP ${response.status}`;
        try {
            const body = await response.json();
            if (Array.isArray(body.detail)) {
                detail = body.detail.map(item => {
                    const location = Array.isArray(item.loc) ? item.loc.filter(part => part !== 'body').join('.') : '';
                    return `${location ? `${location}：` : ''}${item.msg || JSON.stringify(item)}`;
                }).join('；');
            } else if (typeof body.detail === 'string') {
                detail = body.detail;
            } else if (body.detail) {
                detail = JSON.stringify(body.detail);
            }
        } catch {}
        if (response.status === 401 && detail === 'LAN login required') {
            window.dispatchEvent(new CustomEvent('lan-auth-required'));
        }
        throw new Error(detail);
    }

    return await response.json();
}

/**
 * API client object with typed methods.
 */
const api = {
    // ---- Network access ----
    getNetworkSession() {
        return apiFetch('/api/network/session');
    },

    loginNetwork(accessToken) {
        return apiFetch('/api/network/login', {
            method: 'POST',
            body: JSON.stringify({ access_token: accessToken }),
        });
    },

    logoutNetwork() {
        return apiFetch('/api/network/logout', { method: 'POST' });
    },

    // ---- Analysis ----
    startAnalysis(tsCode, strategy, autoConfirm = true) {
        return apiFetch('/api/analysis/start', {
            method: 'POST',
            body: JSON.stringify({ ts_code: tsCode, strategy, auto_confirm: autoConfirm }),
        });
    },

    confirmAnalysis(taskId) {
        return apiFetch(`/api/analysis/${taskId}/confirm`, { method: 'POST' });
    },

    cancelAnalysis(taskId) {
        return apiFetch(`/api/analysis/${taskId}/cancel`, { method: 'POST' });
    },

    getAnalysisStatus(taskId) {
        return apiFetch(`/api/analysis/${taskId}/status`);
    },

    getAnalysisResult(taskId) {
        return apiFetch(`/api/analysis/${taskId}/result`);
    },

    /**
     * Connect to WebSocket for real-time progress.
     * Returns a WebSocket instance.
     */
    connectProgress(taskId) {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/api/analysis/${taskId}/ws`;
        return new WebSocket(wsUrl);
    },

    // ---- Strategies ----
    listStrategies() {
        return apiFetch('/api/strategies');
    },

    getChapters(strategyName) {
        return apiFetch(`/api/strategies/${strategyName}/chapters`);
    },

    // ---- Reports ----
    listReports(params = {}) {
        const search = new URLSearchParams();
        for (const [key, value] of Object.entries(params)) {
            if (value !== '' && value !== null && value !== undefined) search.set(key, String(value));
        }
        const query = search.toString();
        return apiFetch(`/api/reports${query ? `?${query}` : ''}`);
    },

    getReport(reportId) {
        return apiFetch(`/api/reports/${reportId}`);
    },

    deleteReport(reportId) {
        return apiFetch(`/api/reports/${reportId}`, { method: 'DELETE' });
    },

    // ---- Operators ----
    listOperators() {
        return apiFetch('/api/operators');
    },

    getOperator(opId) {
        return apiFetch(`/api/operators/${opId}`);
    },

    updateOperator(opId, data) {
        return apiFetch(`/api/operators/${opId}`, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    },

    createOperator(data) {
        return apiFetch('/api/operators', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    },

    // ---- Frameworks ----
    listFrameworks() {
        return apiFetch('/api/frameworks');
    },

    getFramework(name) {
        return apiFetch(`/api/frameworks/${name}`);
    },

    createFramework(data) {
        return apiFetch('/api/frameworks', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    },

    updateFramework(name, data) {
        return apiFetch(`/api/frameworks/${name}`, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    },

    // ---- Settings ----
    getAppInfo() {
        return apiFetch('/api/settings/app-info');
    },

    getSettings() {
        return apiFetch('/api/settings');
    },

    updateSettings(data) {
        return apiFetch('/api/settings', {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    },

    // ---- Local data management ----
    listDataProviders() {
        return apiFetch('/api/datasources/providers');
    },

    getDataStatus(provider) {
        return apiFetch(`/api/datasources/status?provider=${encodeURIComponent(provider)}`);
    },

    testDataProvider(provider) {
        return apiFetch(`/api/datasources/test/${encodeURIComponent(provider)}`, { method: 'POST' });
    },

    startDataJob(data) {
        return apiFetch('/api/datasources/jobs', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    },

    listDataJobs() {
        return apiFetch('/api/datasources/jobs');
    },

    getDataJob(jobId) {
        return apiFetch(`/api/datasources/jobs/${jobId}`);
    },

    cancelDataJob(jobId) {
        return apiFetch(`/api/datasources/jobs/${jobId}/cancel`, { method: 'POST' });
    },

    // ---- Research workspaces ----
    listCrossSectionPresets() {
        return apiFetch('/api/research/cross-section/presets');
    },

    startCrossSectionRun(data) {
        return apiFetch('/api/research/cross-section/start', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    },

    listResearchJobs(kind = 'cross_section') {
        return apiFetch(`/api/research/jobs?kind=${encodeURIComponent(kind)}`);
    },

    getResearchJob(jobId) {
        return apiFetch(`/api/research/jobs/${jobId}`);
    },

};

// Export for use in Vue components
window.api = api;

// ---- Chat ----
api.sendChatMessage = function(message, context, conversationId = 'qualitative:analysis') {
    return apiFetch('/api/chat', {
        method: 'POST',
        body: JSON.stringify({ message, context, conversation_id: conversationId }),
    });
};

api.getChatHistory = function(conversationId = 'qualitative:analysis') {
    return apiFetch(`/api/chat/history?conversation_id=${encodeURIComponent(conversationId)}`);
};

api.clearChatHistory = function(conversationId = 'qualitative:analysis') {
    const url = `/api/chat/history?conversation_id=${encodeURIComponent(conversationId)}`;
    return apiFetch(url, { method: 'DELETE' });
};
