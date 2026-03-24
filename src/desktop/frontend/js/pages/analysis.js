/**
 * Analysis page component.
 *
 * Main page for starting and monitoring stock analysis.
 */
const AnalysisPage = {
    template: `
<div class="page-analysis">
    <!-- Input Panel -->
    <div class="card input-card">
        <h2>开始分析</h2>
        <div class="input-form">
            <div class="form-row">
                <label class="form-label">股票</label>
                <div class="form-field stock-search-group">
                    <input
                        type="text"
                        v-model="tsCode"
                        placeholder="输入代码或名称，如 601288 或 农业银行"
                        :disabled="isRunning"
                        @input="onStockInput"
                        @keyup.enter="selectFirstOrStart"
                        @keydown.down.prevent="highlightNext"
                        @keydown.up.prevent="highlightPrev"
                        @blur="hideSuggestionsDelayed"
                        autocomplete="off"
                    />
                    <div class="stock-suggestions" v-if="showSuggestions && suggestions.length > 0">
                        <div
                            v-for="(s, idx) in suggestions"
                            :key="s.code"
                            class="suggestion-item"
                            :class="{ highlighted: idx === highlightIndex }"
                            @mousedown.prevent="selectStock(s)"
                        >
                            <span class="suggestion-code">{{ s.code }}</span>
                            <span class="suggestion-name">{{ s.name }}</span>
                        </div>
                    </div>
                </div>
            </div>
            <div class="form-hint" v-if="selectedStockName">
                已选择：{{ tsCode }} {{ selectedStockName }}
            </div>

            <div class="form-row">
                <label class="form-label">策略</label>
                <div class="form-field">
                    <select v-model="selectedStrategy" :disabled="isRunning">
                        <option value="" disabled>选择分析策略...</option>
                        <option
                            v-for="s in strategies"
                            :key="s.name"
                            :value="s.name"
                        >
                            {{ s.display_name }} ({{ s.chapter_count }}章)
                        </option>
                    </select>
                </div>
            </div>
            <div class="form-hint" v-if="currentStrategyDesc">
                {{ currentStrategyDesc }}
            </div>

            <!-- Industry route info -->
            <div class="form-hint route-hint" v-if="routeInfo.industry">
                行业识别: <strong>{{ routeInfo.industry }}</strong>
                <span v-if="routeInfo.routed" class="route-badge">已适配</span>
                <span v-if="routeInfo.skippedCount"> · 跳过 {{ routeInfo.skippedCount }} 个不适用算子</span>
                <span v-if="routeInfo.addedCount"> · 补充 {{ routeInfo.addedCount }} 个行业专用算子</span>
            </div>

            <div class="form-row">
                <label class="form-label"></label>
                <div class="form-field form-action-row">
                    <label class="auto-continue-check">
                        <input type="checkbox" v-model="autoConfirm" />
                        <span>自动继续（不检查数据）</span>
                    </label>
                    <button
                        class="btn btn-primary"
                        @click="startAnalysis"
                        :disabled="!canStart"
                    >
                        {{ isRunning ? '分析中...' : '▶ 开始分析' }}
                    </button>
                </div>
            </div>
        </div>
        <div class="error-msg" v-if="error">{{ error }}</div>

        <!-- Strategy Flow Preview -->
        <div class="flow-preview" v-if="previewChapters.length > 0 && !taskId">
            <div class="flow-timeline">
                <div
                    class="flow-step"
                    v-for="(ch, idx) in previewChapters"
                    :key="ch.id"
                    :class="{ expanded: expandedPreview[ch.id] }"
                    @click="togglePreview(ch.id)"
                >
                    <div class="flow-step-left">
                        <div class="flow-step-badge">{{ ch.chapter }}</div>
                        <div class="flow-step-line" v-if="idx < previewChapters.length"></div>
                    </div>
                    <div class="flow-step-content">
                        <div class="flow-step-header">
                            <span class="flow-step-title">第{{ ch.chapter }}步 · {{ ch.title }}</span>
                            <span class="flow-step-count">{{ (ch.operators || []).length }} 个算子</span>
                            <span class="flow-step-toggle">{{ expandedPreview[ch.id] ? '▾' : '▸' }}</span>
                        </div>
                        <div class="flow-step-deps" v-if="ch.dependencies && ch.dependencies.length">
                            ← 依赖：第{{ (ch.dependencies || []).map(d => previewChapterNum(d)).join(', ') }}步
                        </div>
                        <div class="flow-step-ops" v-if="expandedPreview[ch.id] && ch.operators">
                            <span class="flow-op" v-for="op in (ch.operators || [])" :key="op.id" :title="op.id"
                                :class="{ 'flow-op-added': ch.added && ch.added.some(a => a.id === op.id) }">
                                {{ op.name }}
                                <span v-if="ch.added && ch.added.some(a => a.id === op.id)" class="op-badge-new">行业专用</span>
                            </span>
                            <span class="flow-op flow-op-skipped" v-for="sk in (ch.skipped || [])" :key="'sk-'+sk.id" :title="sk.id">
                                <s>{{ sk.name }}</s> 已跳过
                            </span>
                        </div>
                    </div>
                </div>
                <!-- Synthesis -->
                <div class="flow-step flow-step-final">
                    <div class="flow-step-left">
                        <div class="flow-step-badge flow-badge-final">★</div>
                    </div>
                    <div class="flow-step-content">
                        <div class="flow-step-header">
                            <span class="flow-step-title">综合研判 · 思考步骤 → 评分 → 决策</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Progress Panel -->
    <div class="card progress-card" v-if="taskId">
        <h2>
            分析进度
            <span class="badge" :class="'badge-' + status">{{ statusText }}</span>
            <span class="elapsed-timer" v-if="elapsedDisplay">{{ elapsedDisplay }}</span>
            <span class="stock-label" v-if="stockName">
                {{ stockName }}
                <span v-if="industry" class="industry-tag">{{ industry }}</span>
            </span>
        </h2>

        <!-- Data preview -->
        <div class="snapshot-preview-bar" v-if="dataReady">
            <button class="btn btn-small btn-secondary" @click="toggleSnapshotPreview" :disabled="loadingPreview">
                {{ loadingPreview ? '加载中...' : (showSnapshotPreview ? '收起数据' : '查看分析数据') }}
            </button>
            <span class="snapshot-hint" v-if="!showSnapshotPreview && !waitingConfirm">LLM 分析时看到的完整数据快照</span>
            <template v-if="waitingConfirm">
                <button class="btn btn-primary" @click="confirmAndContinue">✓ 数据确认，继续分析</button>
                <button class="btn btn-small btn-danger" @click="cancelAndStop">✕ 取消</button>
            </template>
        </div>
        <div class="snapshot-preview-content" v-if="showSnapshotPreview && snapshotPreview">
            <pre class="snapshot-md">{{ snapshotPreview }}</pre>
        </div>

        <div class="chapter-list">
            <div
                v-for="ch in chapterProgress"
                :key="ch.id"
                class="chapter-item"
                :class="'chapter-' + ch.status"
            >
                <div class="chapter-header" @click="toggleChapter(ch.id)">
                    <span class="chapter-icon">
                        <span v-if="ch.status === 'complete'">&#10003;</span>
                        <span v-else-if="ch.status === 'running'" class="spinner-inline"></span>
                        <span v-else>&#9679;</span>
                    </span>
                    <span class="chapter-title">
                        第{{ ch.chapter }}章: {{ ch.title }}
                    </span>
                    <span class="chapter-status-text">{{ ch.statusText }}</span>
                    <span class="chapter-expand-btn" v-if="ch.status === 'complete' && (ch.summaryLine || ch.conclusions)">
                        {{ ch.expanded ? '收起' : '展开' }}
                    </span>
                </div>
                <div class="chapter-summary-line" v-if="ch.status === 'complete' && ch.summaryLine && !ch.expanded">
                    <span class="summary-arrow">→</span> {{ ch.summaryLine }}
                </div>
                <div class="chapter-body" v-if="ch.expanded && ch.conclusions">
                    <pre class="chapter-conclusions">{{ ch.conclusions }}</pre>
                </div>
            </div>

            <!-- Synthesis -->
            <div
                v-if="synthesisStatus !== 'pending'"
                class="chapter-item"
                :class="'chapter-' + synthesisStatus"
            >
                <div class="chapter-header">
                    <span class="chapter-icon">
                        <span v-if="synthesisStatus === 'complete'">&#10003;</span>
                        <span v-else-if="synthesisStatus === 'running'" class="spinner-inline"></span>
                        <span v-else>&#9679;</span>
                    </span>
                    <span class="chapter-title">综合研判</span>
                    <span class="chapter-status-text">
                        {{ synthesisStatus === 'complete' ? '完成' : '分析中...' }}
                    </span>
                </div>
            </div>
        </div>
    </div>

    <!-- Result Panel -->
    <div class="card result-card" v-if="result">
        <h2>分析结论</h2>

        <div class="result-summary">
            <div class="result-score" :class="scoreClass">
                <div class="score-number">{{ result.synthesis['综合评分'] || result.synthesis.score || '--' }}</div>
                <div class="score-label">综合评分</div>
            </div>
            <div class="result-recommendation" :class="recommendationClass">
                {{ result.synthesis['最终建议'] || result.synthesis.recommendation || '--' }}
            </div>
            <div class="result-confidence">
                信心: {{ result.synthesis['信心水平'] || result.synthesis.confidence || '--' }}
            </div>
        </div>

        <div class="result-details">
            <div class="result-field" v-for="(value, key) in synthesisDisplay" :key="key">
                <div class="field-label">{{ key }}</div>
                <div class="field-value">{{ value }}</div>
            </div>
        </div>

        <div class="result-meta">
            <span>模型: {{ result.metadata.model }}</span>
            <span>耗时: {{ result.metadata.elapsed_seconds }}秒</span>
            <span>章节: {{ result.metadata.chapters_completed }}章</span>
        </div>

        <!-- Full Report Toggle -->
        <div class="report-toggle">
            <button class="btn btn-secondary" @click="showFullReport = !showFullReport">
                {{ showFullReport ? '收起完整报告' : '查看完整报告' }}
            </button>
        </div>
        <div class="full-report" v-if="showFullReport">
            <div v-for="(text, chId) in result.chapter_texts" :key="chId" class="report-chapter">
                <h3>{{ chId }}</h3>
                <pre class="report-text">{{ text }}</pre>
            </div>
        </div>
    </div>
</div>
    `,

    data() {
        return {
            tsCode: '',
            selectedStockName: '',
            suggestions: [],
            showSuggestions: false,
            highlightIndex: -1,
            searchTimer: null,
            selectedStrategy: '',
            previewChapters: [],
            expandedPreview: {},
            routeInfo: { industry: '', routed: false, skippedCount: 0, addedCount: 0 },
            strategies: [],
            taskId: null,
            status: 'idle',
            error: null,
            stockName: '',
            industry: '',
            chapterDefs: [],
            chapterStates: {},
            synthesisStatus: 'pending',
            autoConfirm: true,
            waitingConfirm: false,
            pendingSnapshot: null,
            dataReady: false,
            showSnapshotPreview: false,
            snapshotPreview: '',
            loadingPreview: false,
            result: null,
            showFullReport: false,
            expandedChapters: {},
            chapterOutputs: {},
            startTime: null,
            elapsedDisplay: '',
            elapsedTimer: null,
            ws: null,
        };
    },

    computed: {
        isRunning() {
            return ['preparing_data', 'running'].includes(this.status);
        },

        canStart() {
            return !this.isRunning;
        },

        currentStrategyDesc() {
            const s = this.strategies.find(s => s.name === this.selectedStrategy);
            return s ? s.description : '';
        },

        statusText() {
            const map = {
                idle: '就绪',
                preparing_data: '准备数据...',
                running: '分析中',
                completed: '已完成',
                failed: '失败',
            };
            return map[this.status] || this.status;
        },

        chapterProgress() {
            return this.chapterDefs.map(ch => {
                const state = this.chapterStates[ch.id] || 'pending';
                const statusTextMap = {
                    pending: '等待中',
                    running: '分析中...',
                    complete: '完成',
                };
                return {
                    ...ch,
                    status: state,
                    statusText: statusTextMap[state] || state,
                    expanded: this.expandedChapters[ch.id] || false,
                    conclusions: this.getChapterConclusions(ch.id),
                    summaryLine: this.getChapterSummaryLine(ch.id),
                };
            });
        },

        scoreClass() {
            const score = parseInt(this.result?.synthesis?.['综合评分'] || this.result?.synthesis?.score || 0);
            if (score >= 75) return 'score-buy';
            if (score >= 50) return 'score-watch';
            return 'score-avoid';
        },

        recommendationClass() {
            const rec = this.result?.synthesis?.['最终建议'] || this.result?.synthesis?.recommendation || '';
            if (rec.includes('买入') || rec.includes('建仓') || rec.includes('值得深入')) return 'rec-buy';
            if (rec.includes('观望')) return 'rec-watch';
            return 'rec-avoid';
        },

        synthesisDisplay() {
            if (!this.result?.synthesis) return {};
            const skip = ['综合评分', 'score', '最终建议', 'recommendation', '信心水平', 'confidence'];
            const display = {};
            for (const [key, value] of Object.entries(this.result.synthesis)) {
                if (!skip.includes(key) && value) {
                    display[key] = typeof value === 'object' ? JSON.stringify(value, null, 2) : value;
                }
            }
            return display;
        },
    },

    watch: {
        async selectedStrategy(val) {
            if (val) {
                try {
                    const data = await api.getChapters(val);
                    this.previewChapters = (data.chapters || []).map(ch => ({
                        ...ch,
                        operators: (ch.operators || []).map(op =>
                            typeof op === 'string' ? { id: op, name: op } : op
                        ),
                        skipped: [],
                        added: [],
                    }));
                    this.expandedPreview = {};
                } catch (e) {
                    this.previewChapters = [];
                }
                this.fetchIndustryRoute();
            } else {
                this.previewChapters = [];
                this.expandedPreview = {};
                this.routeInfo = { industry: '', routed: false, skippedCount: 0, addedCount: 0 };
            }
        },
    },

    async created() {
        await this.loadStrategies();
        // Restore running task if any
        await this.restoreTask();
    },

    beforeUnmount() {
        this.closeWebSocket();
        this.stopElapsedTimer();
    },

    methods: {
        async restoreTask() {
            const saved = localStorage.getItem('current_task');
            if (!saved) return;

            try {
                const { taskId, tsCode, strategy, startTime: savedStartTime } = JSON.parse(saved);
                if (!taskId) return;

                // Check if task still exists
                const status = await api.getAnalysisStatus(taskId);
                if (!status) {
                    localStorage.removeItem('current_task');
                    return;
                }

                // Restore state
                this.taskId = taskId;
                this.tsCode = tsCode || '';
                this.selectedStrategy = strategy || '';
                this.status = status.status || 'running';
                this.stockName = status.stock_name || '';
                this.industry = status.industry || '';

                // Restore chapter defs
                await this.loadChapterDefs();

                // Restore chapter states from status
                if (status.chapters) {
                    for (const ch of status.chapters) {
                        this.chapterStates = { ...this.chapterStates, [ch.id]: ch.status };
                    }
                }

                if (status.synthesis_status) {
                    this.synthesisStatus = status.synthesis_status;
                }

                // If completed, load result
                if (status.status === 'completed') {
                    try {
                        this.result = await api.getAnalysisResult(taskId);
                    } catch (e) {}
                } else if (['preparing_data', 'running'].includes(status.status)) {
                    // Still running, reconnect WebSocket and restart timer
                    this.connectWebSocket(taskId);
                    // Restore timer from saved state or server
                    if (savedStartTime) {
                        this.startTime = savedStartTime;
                    } else if (status.created_at) {
                        this.startTime = status.created_at * 1000;
                    } else {
                        this.startTime = Date.now() - 30000;
                    }
                    this.elapsedTimer = setInterval(() => this.updateElapsed(), 1000);
                    this.updateElapsed();
                }
            } catch (e) {
                localStorage.removeItem('current_task');
            }
        },

        saveTaskState() {
            if (this.taskId) {
                localStorage.setItem('current_task', JSON.stringify({
                    taskId: this.taskId,
                    startTime: this.startTime,
                    tsCode: this.tsCode,
                    strategy: this.selectedStrategy,
                }));
            }
        },

        clearTaskState() {
            localStorage.removeItem('current_task');
        },

        async confirmAndContinue() {
            this.waitingConfirm = false;
            try {
                await api.confirmAnalysis(this.taskId);
            } catch (e) {
                this.error = '继续分析失败: ' + e.message;
            }
        },

        async cancelAndStop() {
            this.waitingConfirm = false;
            try {
                await api.cancelAnalysis(this.taskId);
                this.status = 'failed';
                this.error = '已取消分析';
                this.clearTaskState();
                this.stopElapsedTimer();
            } catch (e) {
                this.error = '取消失败: ' + e.message;
            }
        },

        async toggleSnapshotPreview() {
            if (this.showSnapshotPreview) {
                this.showSnapshotPreview = false;
                return;
            }
            this.loadingPreview = true;
            try {
                const resp = await fetch(`/api/analysis/snapshot-preview?ts_code=${encodeURIComponent(this.tsCode.trim())}`);
                const data = await resp.json();
                this.snapshotPreview = data.content || '（无预览数据，分析完成后自动生成）';
                this.showSnapshotPreview = true;
            } catch (e) {
                this.snapshotPreview = '加载失败: ' + e.message;
                this.showSnapshotPreview = true;
            } finally {
                this.loadingPreview = false;
            }
        },

        async fetchIndustryRoute() {
            const code = this.tsCode.trim();
            const strategy = this.selectedStrategy;
            if (!code || !strategy) {
                this.routeInfo = { industry: '', routed: false, skippedCount: 0, addedCount: 0 };
                return;
            }
            try {
                const resp = await fetch(`/api/analysis/industry-route?ts_code=${encodeURIComponent(code)}&strategy=${encodeURIComponent(strategy)}`);
                const data = await resp.json();
                let skippedCount = 0, addedCount = 0;
                for (const ch of (data.chapters || [])) {
                    skippedCount += (ch.skipped || []).length;
                    addedCount += (ch.added || []).length;
                }
                this.routeInfo = {
                    industry: data.industry || '',
                    routed: data.routed || false,
                    skippedCount,
                    addedCount,
                };
                // Update preview chapters with routed operators
                if (data.chapters && data.chapters.length > 0) {
                    this.previewChapters = data.chapters.map(ch => ({
                        ...ch,
                        operators: (ch.operators || []).map(op =>
                            typeof op === 'string' ? { id: op, name: op } : op
                        ),
                        skipped: ch.skipped || [],
                        added: ch.added || [],
                    }));
                }
            } catch (e) {
                console.error('Failed to fetch industry route:', e);
            }
        },

        togglePreview(chId) {
            this.expandedPreview = {
                ...this.expandedPreview,
                [chId]: !this.expandedPreview[chId],
            };
        },

        previewChapterNum(depId) {
            const ch = this.previewChapters.find(c => c.id === depId);
            return ch ? ch.chapter : '?';
        },

        onStockInput() {
            clearTimeout(this.searchTimer);
            this.highlightIndex = -1;
            this.selectedStockName = '';
            const q = this.tsCode.trim();
            if (q.length < 1) {
                this.suggestions = [];
                this.showSuggestions = false;
                return;
            }
            this.searchTimer = setTimeout(async () => {
                try {
                    const resp = await fetch(`/api/analysis/stocks/search?q=${encodeURIComponent(q)}&limit=8`);
                    this.suggestions = await resp.json();
                    this.showSuggestions = this.suggestions.length > 0;
                } catch (e) {
                    this.suggestions = [];
                    this.showSuggestions = false;
                }
            }, 200);
        },

        selectStock(s) {
            this.tsCode = s.code;
            this.selectedStockName = s.name;
            this.showSuggestions = false;
            this.suggestions = [];
            this.fetchIndustryRoute();
        },

        selectFirstOrStart() {
            if (this.showSuggestions && this.suggestions.length > 0 && this.highlightIndex >= 0) {
                this.selectStock(this.suggestions[this.highlightIndex]);
            } else if (this.showSuggestions && this.suggestions.length > 0) {
                this.selectStock(this.suggestions[0]);
            } else {
                this.startAnalysis();
            }
        },

        highlightNext() {
            if (this.suggestions.length === 0) return;
            this.highlightIndex = Math.min(this.highlightIndex + 1, this.suggestions.length - 1);
        },

        highlightPrev() {
            this.highlightIndex = Math.max(this.highlightIndex - 1, 0);
        },

        hideSuggestionsDelayed() {
            setTimeout(() => { this.showSuggestions = false; }, 150);
        },

        async loadStrategies() {
            try {
                this.strategies = await api.listStrategies();
                if (this.strategies.length > 0 && !this.selectedStrategy) {
                    // Default to v6_enhanced if available, else first
                    const enhanced = this.strategies.find(s => s.name === 'v6_enhanced');
                    this.selectedStrategy = enhanced ? enhanced.name : this.strategies[0].name;
                }
            } catch (e) {
                this.error = `Failed to load strategies: ${e.message}`;
            }
        },

        async loadChapterDefs() {
            if (!this.selectedStrategy) return;
            try {
                const data = await api.getChapters(this.selectedStrategy);
                this.chapterDefs = data.chapters || [];
                // Reset states
                this.chapterStates = {};
                this.chapterDefs.forEach(ch => {
                    this.chapterStates[ch.id] = 'pending';
                });
            } catch (e) {
                console.error('Failed to load chapters:', e);
            }
        },

        async startAnalysis() {
            if (!this.canStart) return;

            this.error = null;
            // Update global context for chat assistant
            window._appContext = { stock_code: this.tsCode.trim(), strategy: this.selectedStrategy };

            // 前置校验：股票代码
            if (!this.tsCode.trim()) {
                this.error = '请输入股票代码';
                return;
            }

            // 前置校验：策略
            if (!this.selectedStrategy) {
                this.error = '请选择分析策略';
                return;
            }

            // 前置校验：API Key
            try {
                const settings = await api.getSettings();
                if (!settings.llm_api_key_set) {
                    this.error = '请先在「设置」页面配置 LLM API Key';
                    return;
                }
            } catch (e) {
                // 设置接口异常，不阻断
            }

            this.result = null;
            this.showFullReport = false;
            this.synthesisStatus = 'pending';
            this.dataReady = false;
            this.showSnapshotPreview = false;
            this.snapshotPreview = '';
            this.stockName = '';
            this.industry = '';
            this.expandedChapters = {};
            this.chapterOutputs = {};
            this.startTime = null;
            this.elapsedDisplay = '';
            this.stopElapsedTimer();

            await this.loadChapterDefs();

            try {
                const resp = await api.startAnalysis(this.tsCode.trim(), this.selectedStrategy, this.autoConfirm);
                this.taskId = resp.task_id;
                this.status = 'preparing_data';

                // Save task state for page recovery
                this.saveTaskState();

                // Connect WebSocket for real-time updates
                this.connectWebSocket(resp.task_id);
            } catch (e) {
                this.error = e.message;
                this.status = 'failed';
            }
        },

        connectWebSocket(taskId) {
            this.closeWebSocket();

            this.ws = api.connectProgress(taskId);

            this.ws.onmessage = (event) => {
                try {
                    const msg = JSON.parse(event.data);
                    this.handleProgressEvent(msg);
                } catch (e) {
                    console.error('Failed to parse WS message:', e);
                }
            };

            this.ws.onerror = (event) => {
                console.error('WebSocket error:', event);
            };

            this.ws.onclose = () => {
                this.ws = null;
            };
        },

        closeWebSocket() {
            if (this.ws) {
                try { this.ws.close(); } catch {}
                this.ws = null;
            }
        },

        handleProgressEvent(msg) {
            const { event, chapter_id, data } = msg;

            switch (event) {
                case 'preparing_data':
                    this.status = 'preparing_data';
                    break;

                case 'data_ready':
                    this.stockName = data.stock_name || '';
                    this.industry = data.industry || '';
                    this.dataReady = true;
                    break;

                case 'data_warnings':
                    break;

                case 'waiting_confirm':
                    this.waitingConfirm = true;
                    this.showSnapshotPreview = true;
                    this.toggleSnapshotPreview();  // Auto load preview
                    break;

                case 'analysis_start':
                    this.status = 'running';
                    this.waitingConfirm = false;
                    this.showSnapshotPreview = false;
                    this.stockName = data.stock_name || this.stockName;
                    this.startElapsedTimer();
                    break;

                case 'snapshot_done':
                    break;

                case 'chapter_start':
                    if (chapter_id) {
                        this.chapterStates = { ...this.chapterStates, [chapter_id]: 'running' };
                    }
                    break;

                case 'chapter_done':
                    if (chapter_id) {
                        this.chapterStates = { ...this.chapterStates, [chapter_id]: 'complete' };
                        if (data) {
                            this.chapterOutputs = { ...this.chapterOutputs, [chapter_id]: data };
                        }
                    }
                    break;

                case 'synthesis_start':
                    this.synthesisStatus = 'running';
                    break;

                case 'synthesis_done':
                    this.synthesisStatus = 'complete';
                    break;

                case 'analysis_complete':
                    this.status = 'completed';
                    this.stopElapsedTimer();
                    this.clearTaskState();
                    break;

                case 'result':
                    this.result = data;
                    break;

                case 'error':
                    this.status = 'failed';
                    this.error = data.message || 'Analysis failed';
                    this.stopElapsedTimer();
                    this.clearTaskState();
                    break;

                case 'ping':
                    break;

                default:
                    console.log('Unknown event:', event, data);
            }
        },

        getChapterConclusions(chId) {
            const output = this.chapterOutputs[chId] || this.result?.chapter_outputs?.[chId];
            if (!output) return null;
            if (typeof output === 'object' && Object.keys(output).length > 0) {
                return JSON.stringify(output, null, 2);
            }
            return null;
        },

        getChapterSummaryLine(chId) {
            const output = this.chapterOutputs[chId] || this.result?.chapter_outputs?.[chId];
            if (!output || typeof output !== 'object') return '';
            // Pick top 3 key-value pairs that have short string values
            const parts = [];
            for (const [key, value] of Object.entries(output)) {
                if (parts.length >= 3) break;
                const val = typeof value === 'object' ? null : String(value);
                if (val && val.length <= 30) {
                    parts.push(key + ': ' + val);
                }
            }
            return parts.join(' | ');
        },

        startElapsedTimer() {
            if (!this.startTime) this.startTime = Date.now();
            this.stopElapsedTimer();
            this.updateElapsed();
            this.elapsedTimer = setInterval(() => this.updateElapsed(), 1000);
        },

        stopElapsedTimer() {
            if (this.elapsedTimer) {
                clearInterval(this.elapsedTimer);
                this.elapsedTimer = null;
            }
            // Keep final display
            this.updateElapsed();
        },

        updateElapsed() {
            if (!this.startTime) { this.elapsedDisplay = ''; return; }
            const sec = Math.floor((Date.now() - this.startTime) / 1000);
            const m = Math.floor(sec / 60);
            const s = sec % 60;
            this.elapsedDisplay = m > 0 ? `已用时 ${m}m ${s}s` : `已用时 ${s}s`;
        },

        toggleChapter(chId) {
            this.expandedChapters = {
                ...this.expandedChapters,
                [chId]: !this.expandedChapters[chId],
            };
        },
    },
};
