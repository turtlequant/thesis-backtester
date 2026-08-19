/**
 * Context Agent — a persistent, page-aware assistant in the right workspace.
 *
 * The central page remains the source of truth. When the model proposes a
 * change, it emits a standard request for an existing structured-editing API;
 * this component renders the request and applies it through the same apiFetch
 * path used by the manual editors.
 */
const ChatAssistant = {
    props: {
        currentPage: { type: String, default: '' },
        currentWorkspace: { type: String, default: '' },
        pageContext: { type: Object, default: () => ({}) },
        open: { type: Boolean, default: false },
    },
    emits: ['toggle'],

    setup(props, { emit }) {
        const histories = Vue.reactive({});
        const drafts = Vue.reactive({});
        const loadingStates = Vue.reactive({});
        const loadedStates = Vue.reactive({});
        const messagesContainer = ref(null);

        const conversationId = computed(() => {
            const workspace = props.currentWorkspace || 'workspace';
            const page = props.currentPage || 'page';
            return `${workspace}:${page}`;
        });

        function ensureHistory(id) {
            if (!Array.isArray(histories[id])) histories[id] = [];
            return histories[id];
        }

        const messages = computed(() => histories[conversationId.value] || []);
        const inputText = computed({
            get: () => drafts[conversationId.value] || '',
            set: value => { drafts[conversationId.value] = value; },
        });
        const isLoading = computed(() => Boolean(loadingStates[conversationId.value]));

        function historyUrl(id) {
            return `/api/chat/history?conversation_id=${encodeURIComponent(id)}`;
        }

        const pageLabels = {
            analysis: '个股分析',
            'qualitative-latest': '最新研判',
            'qualitative-validation': '框架验证',
            reports: '报告',
            frameworks: '研究框架',
            operators: '算子库',
            datasources: '数据',
            settings: '设置',
            'screening-strategies': '策略构建',
            'screening-current': '截面选股',
            'screening-backtest': '历史验证',
        };

        const workspaceLabels = {
            infrastructure: '基础设施',
            qualitative: '结构化投研',
            cross_section: '截面筛选',
        };

        const pageLabel = computed(() => pageLabels[props.currentPage] || 'Thesis Backtester');

        const contextTitle = computed(() => {
            const ctx = props.pageContext || {};
            if (ctx.operator_name) return ctx.operator_name;
            if (ctx.framework_name) return ctx.framework_name;
            if (ctx.report_title) return ctx.report_title;
            if (ctx.stock_code) return ctx.stock_code;
            if (ctx.screening_strategy?.name) return ctx.screening_strategy.name;
            return '尚未选择具体对象';
        });

        const emptyTips = computed(() => {
            if (props.currentPage === 'frameworks') {
                return ['解释当前框架结构', '调整分析方向与依赖', '组合或新增算子'];
            }
            if (props.currentPage === 'operators') {
                return ['解释当前算子的研究方法', '完善分析步骤与输出', '创建新的用户算子'];
            }
            if (props.currentPage === 'analysis') {
                return ['解释当前分析进度', '说明章节结论', '排查数据与运行问题'];
            }
            if (props.currentPage === 'qualitative-latest') {
                return ['检查当前批量方案', '解释研判结果差异', '梳理共同风险'];
            }
            if (props.currentPage === 'qualitative-validation') {
                return ['解释框架增量效果', '检查历史可用性', '比较筛选与研判贡献'];
            }
            if (props.currentPage === 'reports') {
                return ['解释报告结论', '梳理关键证据', '比较风险与估值判断'];
            }
            if (props.currentPage === 'screening-strategies') {
                return ['解释筛选字段口径', '检查条件与排名是否冲突', '建议数值规则组合'];
            }
            if (props.currentPage === 'screening-current') {
                return ['解释当前选股结果', '检查筛选漏斗', '说明入选股票指标'];
            }
            if (props.currentPage === 'screening-backtest') {
                return ['解释历史验证结果', '说明筛选池与基准差异', '检查回测口径'];
            }
            return ['理解当前页面', '解答平台使用问题', '定位配置或数据问题'];
        });

        function togglePanel() {
            emit('toggle');
            if (!props.open) Vue.nextTick(() => scrollToBottom());
        }

        function scrollToBottom() {
            const el = messagesContainer.value;
            if (el) el.scrollTop = el.scrollHeight;
        }

        function parseActions(content) {
            const actions = [];
            const pattern = /```app-action\s*([\s\S]*?)```/g;
            let match;
            while ((match = pattern.exec(content || '')) !== null) {
                try {
                    const parsed = JSON.parse(match[1].trim());
                    const items = Array.isArray(parsed) ? parsed : [parsed];
                    for (const item of items) {
                        if (item && item.method && item.path) {
                            const path = String(item.path).replace(
                                /^\/api\/screening-strategies(?=\/|$)/,
                                '/api/research/screening-strategies',
                            );
                            actions.push({ ...item, path, status: 'pending', error: '' });
                        }
                    }
                } catch (error) {
                    console.warn('Invalid app-action payload:', error);
                }
            }
            return actions;
        }

        function visibleContent(content) {
            return (content || '').replace(/```app-action\s*[\s\S]*?```/g, '').trim();
        }

        function isAllowedAction(action) {
            const method = String(action.method || '').toUpperCase();
            const path = String(action.path || '');
            const operatorPath = /^\/api\/operators(?:\/[A-Za-z0-9_-]+)?$/;
            const frameworkPath = /^\/api\/frameworks(?:\/[A-Za-z0-9_-]+)?$/;
            const screeningCollection = '/api/research/screening-strategies';
            const screeningItem = /^\/api\/research\/screening-strategies\/[A-Za-z0-9_-]+$/;
            const standardEditorAction = ['POST', 'PUT'].includes(method) &&
                (operatorPath.test(path) || frameworkPath.test(path));
            const screeningAction = ['screening-strategies', 'screening-current', 'screening-backtest'].includes(props.currentPage) && (
                (method === 'POST' && path === screeningCollection) ||
                (method === 'PUT' && screeningItem.test(path))
            );
            return standardEditorAction || screeningAction;
        }

        function prepareActionBody(action) {
            const body = { ...(action.body || {}) };
            const path = String(action.path || '');
            if (!path.startsWith('/api/research/screening-strategies')) return body;

            const context = { ...(props.pageContext || {}), ...(window._appContext || {}) };
            const current = context.screening_strategy || null;
            const method = String(action.method || '').toUpperCase();
            const itemMatch = path.match(/^\/api\/research\/screening-strategies\/([A-Za-z0-9_-]+)$/);

            if (method === 'PUT') {
                if (!current?.id || !itemMatch || itemMatch[1] !== current.id) {
                    throw new Error('修改目标与中央页面当前策略不一致，请重新生成操作。');
                }
                body.name = body.name || current.name;
                body.description = body.description ?? current.description ?? '';
                body.definition = body.definition || current.definition;
            } else if (method === 'POST' && current) {
                body.name = body.name || `${current.name} 副本`;
                body.description = body.description ?? current.description ?? '';
                body.definition = body.definition || current.definition;
            }

            if (!body.name || !body.definition) {
                throw new Error('筛选策略操作缺少名称或完整规则定义。');
            }

            const availableIds = new Set((context.available_fields || []).map(field => field.id));
            const rules = [
                ...(body.definition.filters || []),
                ...(body.definition.ranking || []),
            ];
            const unknown = [...new Set(rules.map(rule => rule.field).filter(id => availableIds.size && !availableIds.has(id)))];
            if (unknown.length) {
                throw new Error(`策略包含不可用字段：${unknown.join('、')}`);
            }
            for (const rule of body.definition.filters || []) {
                if (['total_mv', 'circ_mv'].includes(rule.field)) {
                    const values = [rule.min, rule.max].filter(value => Number.isFinite(Number(value)));
                    if (values.some(value => Number(value) > 100000000)) {
                        throw new Error(`${rule.field} 的单位是万元，当前数值异常偏大，请换算后重新生成操作。`);
                    }
                }
            }
            return body;
        }

        async function applyAction(action) {
            if (!isAllowedAction(action)) {
                action.status = 'failed';
                action.error = '该操作不属于当前页面允许的结构化编辑 API。';
                return;
            }

            action.status = 'applying';
            action.error = '';
            try {
                const body = prepareActionBody(action);
                const result = await apiFetch(action.path, {
                    method: String(action.method).toUpperCase(),
                    body: JSON.stringify(body),
                });
                action.status = 'applied';
                window.dispatchEvent(new CustomEvent('app-resource-updated', {
                    detail: { action, result },
                }));
            } catch (error) {
                action.status = 'failed';
                action.error = error.message || String(error);
            }
        }

        async function sendMessage() {
            const text = inputText.value.trim();
            const activeConversation = conversationId.value;
            if (!text || loadingStates[activeConversation]) return;

            const activeHistory = ensureHistory(activeConversation);
            activeHistory.push({
                role: 'user',
                content: text,
                timestamp: Date.now() / 1000,
            });
            inputText.value = '';
            loadingStates[activeConversation] = true;
            Vue.nextTick(scrollToBottom);

            const context = {
                page: props.currentPage || '',
                workspace: props.currentWorkspace || '',
                ...(props.pageContext || {}),
                ...(window._appContext || {}),
            };
            const assistantMsg = {
                role: 'assistant',
                content: '',
                actions: [],
                timestamp: Date.now() / 1000,
            };
            activeHistory.push(assistantMsg);

            try {
                const response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        message: text,
                        context,
                        conversation_id: activeConversation,
                    }),
                });
                if (!response.ok || !response.body) {
                    throw new Error(`HTTP ${response.status}`);
                }

                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop() || '';

                    for (const line of lines) {
                        if (!line.startsWith('data: ')) continue;
                        const payload = line.slice(6).trim();
                        if (payload === '[DONE]') continue;
                        try {
                            const data = JSON.parse(payload);
                            if (data.delta) {
                                assistantMsg.content += data.delta;
                                Vue.nextTick(scrollToBottom);
                            }
                        } catch (_) {}
                    }
                }
                assistantMsg.actions = parseActions(assistantMsg.content);
            } catch (error) {
                if (!assistantMsg.content) {
                    assistantMsg.content = `网络错误，请检查服务是否正常运行。${error.message || ''}`;
                }
            } finally {
                loadingStates[activeConversation] = false;
                loadedStates[activeConversation] = true;
                if (conversationId.value === activeConversation) {
                    Vue.nextTick(scrollToBottom);
                }
            }
        }

        async function clearHistory() {
            const activeConversation = conversationId.value;
            try {
                await apiFetch(historyUrl(activeConversation), { method: 'DELETE' });
                histories[activeConversation] = [];
                loadedStates[activeConversation] = true;
            } catch (error) {
                console.error('Failed to clear history:', error);
            }
        }

        async function loadHistory(id = conversationId.value) {
            if (loadingStates[id]) return;
            try {
                const data = await apiFetch(historyUrl(id));
                if (Array.isArray(data)) {
                    histories[id] = data.map(msg => ({
                        ...msg,
                        // 历史动作不重复提供“应用”，避免重启后误提交旧修改。
                        actions: [],
                    }));
                    loadedStates[id] = true;
                    if (conversationId.value === id) Vue.nextTick(scrollToBottom);
                }
            } catch (_) {}
        }

        function handleKeydown(event) {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                sendMessage();
            }
        }

        function formatTime(timestamp) {
            if (!timestamp) return '';
            return new Date(timestamp * 1000).toLocaleTimeString('zh-CN', {
                hour: '2-digit', minute: '2-digit',
            });
        }

        function renderMd(content) {
            const visible = visibleContent(content);
            if (!visible) return '';
            try {
                return marked.parse(visible);
            } catch (_) {
                return visible;
            }
        }

        onMounted(() => loadHistory(conversationId.value));
        Vue.watch(conversationId, id => {
            if (!loadedStates[id]) loadHistory(id);
            Vue.nextTick(scrollToBottom);
        });

        return {
            messages,
            inputText,
            isLoading,
            messagesContainer,
            pageLabel,
            workspaceLabels,
            contextTitle,
            emptyTips,
            togglePanel,
            sendMessage,
            clearHistory,
            handleKeydown,
            formatTime,
            renderMd,
            visibleContent,
            applyAction,
        };
    },

    template: `
<button
    v-if="!open"
    class="agent-rail-button"
    @click="togglePanel"
    title="打开投研助手"
>
    <span class="agent-rail-icon">AI</span>
    <span class="agent-rail-text">投研助手</span>
</button>

<aside class="agent-panel" :class="{ 'agent-panel-open': open }" v-show="open">
    <header class="agent-panel-header">
        <div>
            <div class="agent-panel-title">投研助手</div>
            <div class="agent-panel-subtitle">辅助操作，不改变分析管线</div>
        </div>
        <div class="agent-panel-actions">
            <button class="agent-icon-button" @click="clearHistory" title="清除对话">&#128465;</button>
            <button class="agent-icon-button" @click="togglePanel" title="收起">&#10095;</button>
        </div>
    </header>

    <section class="agent-context">
        <span class="agent-context-page">{{ workspaceLabels[currentWorkspace] || pageLabel }}</span>
        <span class="agent-context-object" :title="contextTitle">{{ contextTitle }}</span>
    </section>

    <div class="chat-messages" ref="messagesContainer">
        <div v-if="messages.length === 0" class="chat-empty">
            <div class="chat-empty-icon">&#10022;</div>
            <div class="chat-empty-text">我会结合当前页面协助你</div>
            <button
                v-for="tip in emptyTips"
                :key="tip"
                class="agent-suggestion"
                @click="inputText = tip"
            >{{ tip }}</button>
        </div>

        <div
            v-for="(msg, idx) in messages"
            :key="idx"
            class="chat-msg"
            :class="'chat-msg-' + msg.role"
        >
            <div class="chat-msg-bubble" v-if="msg.role === 'user'">{{ msg.content }}</div>
            <div
                class="chat-msg-bubble chat-md"
                v-else-if="visibleContent(msg.content)"
                v-html="renderMd(msg.content)"
            ></div>

            <div class="agent-action-list" v-if="msg.actions && msg.actions.length">
                <div class="agent-action-card" v-for="(action, actionIdx) in msg.actions" :key="actionIdx">
                    <div class="agent-action-title">{{ action.title || action.summary || '结构化修改' }}</div>
                    <div class="agent-action-meta">{{ action.method.toUpperCase() }} {{ action.path }}</div>
                    <div class="agent-action-description" v-if="action.description">{{ action.description }}</div>
                    <button
                        class="btn btn-small btn-primary"
                        v-if="action.status === 'pending'"
                        @click="applyAction(action)"
                    >应用修改</button>
                    <span class="agent-action-state applying" v-else-if="action.status === 'applying'">正在应用…</span>
                    <span class="agent-action-state applied" v-else-if="action.status === 'applied'">已应用到中央工作区</span>
                    <span class="agent-action-state failed" v-else>失败：{{ action.error }}</span>
                </div>
            </div>
            <div class="chat-msg-time">{{ formatTime(msg.timestamp) }}</div>
        </div>

        <div v-if="isLoading" class="chat-msg chat-msg-assistant">
            <div class="chat-msg-bubble chat-typing">
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
            </div>
        </div>
    </div>

    <div class="chat-input-area">
        <textarea
            class="chat-input"
            v-model="inputText"
            @keydown="handleKeydown"
            :placeholder="'询问或修改当前' + pageLabel + '…'"
            rows="2"
            :disabled="isLoading"
        ></textarea>
        <button class="chat-btn-send" @click="sendMessage" :disabled="isLoading || !inputText.trim()">&#10148;</button>
    </div>
</aside>
    `,
};
