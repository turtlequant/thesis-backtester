/**
 * Main Vue 3 application.
 *
 * Uses CDN-loaded Vue 3 (no build step).
 * Simple client-side routing via reactive currentPage state.
 */
const { createApp, ref, computed, onMounted } = Vue;

const App = {
    components: {
        'page-analysis': AnalysisPage,
        'page-reports': ReportsPage,
        'page-operators': OperatorsPage,
        'page-frameworks': FrameworksPage,
        'page-datasources': DataSourcesPage,
        'page-settings': SettingsPage,
        'chat-assistant': ChatAssistant,
    },

    setup() {
        const currentPage = ref('analysis');

        const pages = [
            { id: 'analysis', label: '分析', icon: '&#128269;' },
            { id: 'reports', label: '报告', icon: '&#128196;' },
            { id: 'operators', label: '算子', icon: '&#9881;' },
            { id: 'frameworks', label: '编排', icon: '&#128230;' },
            { id: 'datasources', label: '数据', icon: '&#128451;' },
            { id: 'settings', label: '设置', icon: '&#128295;' },
        ];

        function navigate(pageId) {
            currentPage.value = pageId;
        }

        // Context for chat assistant (auto-detected from current page state)
        // Global context store — pages update this via window._appContext
        window._appContext = window._appContext || {};
        const pageContext = computed(() => {
            return { ...(window._appContext || {}) };
        });

        return {
            currentPage,
            pages,
            navigate,
            pageContext,
        };
    },

    template: `
<div class="app-layout">
    <!-- Sidebar -->
    <aside class="sidebar">
        <div class="sidebar-brand">
            <div class="brand-icon">
                <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
                    <rect x="2" y="6" width="4" height="18" rx="1" fill="currentColor" opacity="0.5"/>
                    <rect x="8" y="10" width="4" height="14" rx="1" fill="currentColor" opacity="0.7"/>
                    <rect x="14" y="4" width="4" height="20" rx="1" fill="currentColor" opacity="0.85"/>
                    <rect x="20" y="2" width="4" height="22" rx="1" fill="currentColor"/>
                </svg>
            </div>
            <span class="brand-text">投研分析</span>
        </div>

        <nav class="sidebar-nav">
            <a
                v-for="p in pages"
                :key="p.id"
                class="nav-item"
                :class="{ active: currentPage === p.id }"
                @click="navigate(p.id)"
            >
                <span class="nav-icon" v-html="p.icon"></span>
                <span class="nav-label">{{ p.label }}</span>
            </a>
        </nav>

        <div class="sidebar-footer">
            <div class="version-tag">v1.0.0</div>
        </div>
    </aside>

    <!-- Main Content -->
    <main class="main-content">
        <page-analysis v-if="currentPage === 'analysis'" />
        <page-reports v-if="currentPage === 'reports'" />
        <page-operators v-if="currentPage === 'operators'" />
        <page-frameworks v-if="currentPage === 'frameworks'" />
        <page-datasources v-if="currentPage === 'datasources'" />
        <page-settings v-if="currentPage === 'settings'" />
    </main>

    <!-- Chat Assistant (always mounted) -->
    <chat-assistant :current-page="currentPage" :page-context="pageContext" />
</div>
    `,
};

// Mount the app
const app = createApp(App);
app.mount('#app');
