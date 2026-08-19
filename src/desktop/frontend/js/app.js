/**
 * Main Vue 3 application.
 *
 * Uses CDN-loaded Vue 3 (no build step).
 * Simple client-side routing via reactive currentPage state.
 */
const { createApp, ref, computed, onMounted } = Vue;

const WorkspacePageHeader = {
    props: {
        eyebrow: { type: String, required: true },
        title: { type: String, required: true },
        description: { type: String, required: true },
    },
    template: `
<header class="page-header">
    <div class="page-header-copy">
        <div class="page-header-eyebrow">{{ eyebrow }}</div>
        <h1>{{ title }}</h1>
        <p>{{ description }}</p>
    </div>
    <div class="page-header-aside" v-if="$slots.meta || $slots.actions">
        <div class="page-header-meta" v-if="$slots.meta"><slot name="meta"></slot></div>
        <div class="page-header-actions" v-if="$slots.actions"><slot name="actions"></slot></div>
    </div>
</header>`,
};

const App = {
    components: {
        'page-analysis': AnalysisPage,
        'page-reports': ReportsPage,
        'page-latest-judgement': LatestJudgementPage,
        'page-framework-validation': FrameworkValidationPage,
        'page-operators': OperatorsPage,
        'page-frameworks': FrameworksPage,
        'page-datasources': DataSourcesPage,
        'page-factors': FactorsPage,
        'page-settings': SettingsPage,
        'page-screening-workbench': ScreeningWorkbenchPage,
        'page-screening-current': ScreeningCurrentPage,
        'page-screening-backtest': ScreeningBacktestPage,
        'chat-assistant': ChatAssistant,
        'product-guide': ProductGuide,
    },

    setup() {
        const workspaces = [
            {
                id: 'infrastructure',
                label: '基础设施',
                description: '数据与研究方法',
                defaultPage: 'datasources',
                pages: [
                    { id: 'datasources', label: '数据维护', icon: '&#128451;' },
                    { id: 'factors', label: '因子库', icon: '&#129518;' },
                    { id: 'operators', label: '算子库', icon: '&#9881;' },
                    { id: 'frameworks', label: '研究框架', icon: '&#128230;' },
                    { id: 'settings', label: '系统设置', icon: '&#128295;' },
                ],
            },
            {
                id: 'cross_section',
                label: '截面筛选',
                description: '构建策略、执行选股、验证历史',
                defaultPage: 'screening-strategies',
                pages: [
                    { id: 'screening-strategies', label: '策略构建', icon: '&#9881;' },
                    { id: 'screening-current', label: '截面选股', icon: '&#128269;' },
                    { id: 'screening-backtest', label: '历史验证', icon: '&#128200;' },
                ],
            },
            {
                id: 'qualitative',
                label: '结构化投研',
                description: '个股分析、最新研判与框架验证',
                defaultPage: 'analysis',
                pages: [
                    { id: 'analysis', label: '个股分析', icon: '&#128269;' },
                    { id: 'qualitative-latest', label: '最新研判', icon: '&#128202;' },
                    { id: 'qualitative-validation', label: '框架验证', icon: '&#128200;' },
                    { id: 'reports', label: '分析报告', icon: '&#128196;' },
                ],
            },
        ];

        const savedWorkspace = localStorage.getItem('research-workspace');
        const initialWorkspace = workspaces.find(item => item.id === savedWorkspace)
            || workspaces.find(item => item.id === 'qualitative')
            || workspaces[0];
        const currentWorkspace = ref(initialWorkspace.id);
        const currentPage = ref(initialWorkspace.defaultPage);
        const agentOpen = ref(true);
        const pageContext = ref({});
        const guideOpen = ref(false);
        const guideMode = ref('full');
        const guideData = ref({});
        const appInfo = ref({});
        const networkSession = ref({ loading: true, required: false, authenticated: false });
        const networkAccessToken = ref('');
        const networkLoginError = ref('');
        const networkLoginBusy = ref(false);

        const activeWorkspace = computed(() => (
            workspaces.find(item => item.id === currentWorkspace.value) || workspaces[0]
        ));
        const pages = computed(() => activeWorkspace.value.pages);

        function resetContext() {
            pageContext.value = {};
            window._appContext = {};
        }

        function switchWorkspace() {
            const workspace = activeWorkspace.value;
            currentPage.value = workspace.defaultPage;
            localStorage.setItem('research-workspace', workspace.id);
            resetContext();
            agentOpen.value = true;
        }

        function selectWorkspace(workspaceId, event) {
            event?.currentTarget?.blur();
            if (!workspaces.some(item => item.id === workspaceId)) return;
            if (currentWorkspace.value === workspaceId) return;
            currentWorkspace.value = workspaceId;
            switchWorkspace();
        }

        function navigate(pageId) {
            currentPage.value = pageId;
            resetContext();
            agentOpen.value = true;
        }

        function toggleAgent() {
            agentOpen.value = !agentOpen.value;
        }

        async function loadProductGuide() {
            try {
                guideData.value = await apiFetch('/api/guide');
                if (!guideData.value.seen) {
                    guideMode.value = 'intro';
                    guideOpen.value = true;
                }
            } catch (error) {
                console.warn('Failed to load product guide:', error);
            }
        }

        async function loadAppInfo() {
            try {
                appInfo.value = await api.getAppInfo();
            } catch (error) {
                console.warn('Failed to load application version:', error);
            }
        }

        async function markGuideSeen() {
            const version = guideData.value.version;
            if (!version || guideData.value.seen) return;
            guideData.value.seen = true;
            try {
                await apiFetch('/api/guide/seen', {
                    method: 'PUT',
                    body: JSON.stringify({ version }),
                });
            } catch (error) {
                guideData.value.seen = false;
                console.warn('Failed to persist product guide state:', error);
            }
        }

        function openGuide() {
            guideMode.value = 'full';
            guideOpen.value = true;
        }

        function closeGuide() {
            guideOpen.value = false;
            markGuideSeen();
        }

        function showFullGuide() {
            guideMode.value = 'full';
            markGuideSeen();
        }

        async function initializeApp() {
            networkLoginError.value = '';
            try {
                const session = await api.getNetworkSession();
                networkSession.value = { ...session, loading: false };
                if (session.authenticated) {
                    await Promise.all([loadProductGuide(), loadAppInfo()]);
                }
            } catch (error) {
                networkSession.value = { loading: false, required: true, authenticated: false };
                networkLoginError.value = `无法确认访问状态：${error.message}`;
            }
        }

        async function loginNetwork() {
            const token = networkAccessToken.value.trim();
            if (!token) {
                networkLoginError.value = '请输入访问口令';
                return;
            }
            networkLoginBusy.value = true;
            networkLoginError.value = '';
            try {
                await api.loginNetwork(token);
                networkAccessToken.value = '';
                networkSession.value = { loading: false, required: true, authenticated: true };
                await Promise.all([loadProductGuide(), loadAppInfo()]);
            } catch (error) {
                networkLoginError.value = error.message === 'Access token is invalid'
                    ? '访问口令不正确'
                    : error.message;
            } finally {
                networkLoginBusy.value = false;
            }
        }

        function requireNetworkLogin() {
            networkSession.value = { loading: false, required: true, authenticated: false };
            networkLoginError.value = '局域网会话已失效，请重新输入访问口令。';
        }

        // 页面和助手共享同一份响应式上下文。保留 _appContext 兼容旧页面。
        window._appContext = window._appContext || {};
        window.setAppContext = (context = {}) => {
            const normalized = { ...context };
            window._appContext = normalized;
            pageContext.value = normalized;
        };

        onMounted(() => {
            window.addEventListener('lan-auth-required', requireNetworkLogin);
            initializeApp();
        });

        return {
            currentPage,
            currentWorkspace,
            workspaces,
            activeWorkspace,
            pages,
            navigate,
            switchWorkspace,
            selectWorkspace,
            pageContext,
            agentOpen,
            toggleAgent,
            guideOpen,
            guideMode,
            guideData,
            appInfo,
            openGuide,
            closeGuide,
            showFullGuide,
            networkSession,
            networkAccessToken,
            networkLoginError,
            networkLoginBusy,
            loginNetwork,
        };
    },

    template: `
<div v-if="networkSession.loading" class="network-access-screen">
    <div class="network-access-card network-access-loading">正在确认访问状态…</div>
</div>

<div v-else-if="!networkSession.authenticated" class="network-access-screen">
    <form class="network-access-card" @submit.prevent="loginNetwork">
        <div class="network-access-brand">THESIS BACKTESTER</div>
        <h1>局域网访问</h1>
        <p>请输入桌面端“系统设置”中生成的访问口令。</p>
        <label for="network-access-token">访问口令</label>
        <input
            id="network-access-token"
            v-model="networkAccessToken"
            type="password"
            autocomplete="current-password"
            autofocus
            placeholder="输入访问口令"
        />
        <div class="network-access-error" v-if="networkLoginError">{{ networkLoginError }}</div>
        <button class="btn btn-primary" type="submit" :disabled="networkLoginBusy">
            {{ networkLoginBusy ? '正在验证…' : '进入 Thesis Backtester' }}
        </button>
    </form>
</div>

<div v-else class="app-layout">
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
            <div class="brand-copy">
                <span class="brand-text">THESIS BACKTESTER</span>
                <span class="brand-tagline">结构化投研引擎</span>
            </div>
        </div>

        <div class="workspace-switcher">
            <label>当前工作区</label>
            <div class="workspace-select-wrap">
                <button class="workspace-select-trigger" type="button" aria-haspopup="listbox">
                    <span>{{ activeWorkspace.label }}</span>
                    <span class="workspace-select-chevron" aria-hidden="true">⌄</span>
                </button>
                <div class="workspace-option-menu" role="listbox" aria-label="切换工作区">
                    <button
                        v-for="workspace in workspaces"
                        :key="workspace.id"
                        type="button"
                        class="workspace-option"
                        :class="{ active: currentWorkspace === workspace.id }"
                        :aria-selected="currentWorkspace === workspace.id"
                        role="option"
                        @click="selectWorkspace(workspace.id, $event)"
                    >
                        <span>{{ workspace.label }}</span>
                        <small>{{ workspace.description }}</small>
                    </button>
                </div>
            </div>
            <div class="workspace-switch-description">{{ activeWorkspace.description }}</div>
        </div>

        <nav class="sidebar-nav">
            <div class="sidebar-nav-caption">功能</div>
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
            <button class="guide-sidebar-button" @click="openGuide">
                <span class="guide-sidebar-icon">?</span>
                <span>功能指引</span>
            </button>
            <div class="sidebar-footer-meta">
                <div class="version-tag">{{ appInfo.display_version || '—' }}</div>
                <a
                    class="github-sidebar-link"
                    href="https://github.com/turtlequant/thesis-backtester"
                    target="_blank"
                    rel="noopener noreferrer"
                    title="打开 GitHub 仓库"
                >
                    <svg class="github-sidebar-icon" viewBox="0 0 24 24" aria-hidden="true">
                        <path fill="currentColor" d="M12 .7a11.5 11.5 0 0 0-3.64 22.4c.58.1.79-.25.79-.56v-2.23c-3.22.7-3.9-1.37-3.9-1.37-.52-1.34-1.29-1.69-1.29-1.69-1.05-.72.08-.71.08-.71 1.17.08 1.78 1.2 1.78 1.2 1.04 1.78 2.72 1.27 3.38.97.1-.75.4-1.27.74-1.56-2.57-.29-5.27-1.29-5.27-5.68 0-1.26.45-2.28 1.19-3.09-.12-.29-.52-1.47.11-3.05 0 0 .97-.31 3.16 1.18a10.96 10.96 0 0 1 5.76 0c2.2-1.49 3.16-1.18 3.16-1.18.63 1.58.23 2.76.11 3.05.74.81 1.19 1.83 1.19 3.09 0 4.4-2.71 5.38-5.29 5.67.42.36.79 1.06.79 2.14v3.18c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .7Z"/>
                    </svg>
                    <span>GitHub</span>
                    <span class="github-sidebar-arrow" aria-hidden="true">↗</span>
                </a>
            </div>
            <p class="sidebar-disclaimer">仅供研究与回测，不构成任何投资建议；使用者应独立判断并自行承担风险。</p>
        </div>
    </aside>

    <!-- Main Content -->
    <main class="main-content" :class="{ 'main-content-with-agent': agentOpen }">
        <page-analysis v-if="currentPage === 'analysis'" />
        <page-latest-judgement v-if="currentPage === 'qualitative-latest'" />
        <page-framework-validation v-if="currentPage === 'qualitative-validation'" />
        <page-reports v-if="currentPage === 'reports'" />
        <page-operators v-if="currentPage === 'operators'" />
        <page-frameworks v-if="currentPage === 'frameworks'" />
        <page-datasources v-if="currentPage === 'datasources'" />
        <page-factors v-if="currentPage === 'factors'" />
        <page-settings v-if="currentPage === 'settings'" />
        <page-screening-workbench v-if="currentPage === 'screening-strategies'" />
        <page-screening-current v-if="currentPage === 'screening-current'" />
        <page-screening-backtest v-if="currentPage === 'screening-backtest'" />
    </main>

    <!-- Context Agent (always mounted, participates in the desktop layout) -->
    <chat-assistant
        :current-page="currentPage"
        :current-workspace="currentWorkspace"
        :page-context="pageContext"
        :open="agentOpen"
        @toggle="toggleAgent"
    />

    <product-guide
        :open="guideOpen"
        :mode="guideMode"
        :guide="guideData"
        :current-page="currentPage"
        @close="closeGuide"
        @show-full="showFullGuide"
    />
</div>
    `,
};

// Mount the app
const app = createApp(App);
app.component('workspace-page-header', WorkspacePageHeader);
app.mount('#app');
