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
    };
    const merged = { ...defaults, ...options };

    try {
        const response = await fetch(url, merged);

        if (!response.ok) {
            let detail = `HTTP ${response.status}`;
            try {
                const body = await response.json();
                detail = body.detail || detail;
            } catch {}
            throw new Error(detail);
        }

        return await response.json();
    } catch (error) {
        if (error.message.startsWith('HTTP')) {
            throw error;
        }
        throw new Error(`Network error: ${error.message}`);
    }
}

/**
 * API client object with typed methods.
 */
const api = {
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
    listReports() {
        return apiFetch('/api/reports');
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
    getSettings() {
        return apiFetch('/api/settings');
    },

    updateSettings(data) {
        return apiFetch('/api/settings', {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    },
};

// Export for use in Vue components
window.api = api;

// ---- Chat ----
api.sendChatMessage = function(message, context) {
    return apiFetch('/api/chat', {
        method: 'POST',
        body: JSON.stringify({ message, context }),
    });
};

api.getChatHistory = function() {
    return apiFetch('/api/chat/history');
};

api.clearChatHistory = function() {
    return apiFetch('/api/chat/history', { method: 'DELETE' });
};
