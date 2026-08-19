/**
 * Data sources page component.
 *
 * Browse available data sources and test data fetching.
 */
const DataSourcesPage = {
    template: `
<div class="page-datasources">
    <workspace-page-header eyebrow="基础设施 · 数据基线" title="数据维护" description="维护当前数据源的本地历史基线、增量任务与覆盖状态。">
        <template #meta>
            <div class="page-header-control">
                <label>当前数据源</label>
                <select v-model="managementProvider" @change="changeProvider">
                    <option v-for="provider in providers" :key="provider.name" :value="provider.name">
                        {{ provider.label }}（{{ provider.access_mode }}）
                    </option>
                </select>
            </div>
        </template>
    </workspace-page-header>

    <div class="card data-manager-card">
        <div class="provider-summary" v-if="currentProvider">
            <div><strong>{{ currentProvider.label }}</strong> · {{ currentProvider.description }}</div>
            <div class="setting-hint" v-if="currentProvider.limitations.length">
                数据边界：{{ currentProvider.limitations.join('；') }}
            </div>
            <div class="setting-hint" v-if="!currentProvider.supports_download">
                此数据源用于即时分析，不建立历史本地库。
            </div>
        </div>

        <template v-if="currentProvider && currentProvider.supports_download">
            <div class="data-download-form">
                <div class="setting-item">
                    <label>开始日期</label>
                    <input type="date" v-model="download.start_date" />
                </div>
                <div class="setting-item">
                    <label>结束日期</label>
                    <input type="date" v-model="download.end_date" />
                </div>
                <div class="setting-item data-code-input">
                    <label>股票代码（可选）</label>
                    <input type="text" v-model="download.codes" placeholder="601288.SH, 000001.SZ；留空为全市场" />
                </div>
            </div>

            <div class="data-action-row">
                <button class="btn btn-secondary" @click="startJob('basic')" :disabled="hasRunningJob">初始化基础数据</button>
                <button class="btn btn-primary" @click="startJob('market')" :disabled="hasRunningJob">下载行情</button>
                <button class="btn btn-secondary" @click="startJob('financials')" :disabled="hasRunningJob">下载财务</button>
                <button class="btn btn-secondary" @click="startJob('full')" :disabled="hasRunningJob">完整初始化</button>
                <button class="btn btn-secondary" @click="startJob('incremental')" :disabled="hasRunningJob">立即增量更新</button>
                <button class="btn btn-small" @click="testManagedProvider" :disabled="testingProvider">
                    {{ testingProvider ? '测试中...' : '测试连接' }}
                </button>
            </div>
            <div class="save-status" v-if="actionMessage" :class="actionSuccess ? 'success' : 'error'">{{ actionMessage }}</div>
        </template>

        <div class="data-job-progress" v-if="activeJob">
            <div class="data-job-progress-head">
                <span>{{ workflowTitle }} · {{ workflowCurrentJob.message }}</span>
                <span>阶段进度 {{ workflowPercent }}%</span>
            </div>
            <div class="data-job-phases" v-if="workflowFactorJob">
                <span class="data-job-phase complete">1 · 数据更新</span>
                <span class="data-job-phase" :class="workflowPhaseClass">2 · 因子同步（{{ workflowFactorJob.codes.length }} 个）</span>
            </div>
            <div class="data-progress-track"><div class="data-progress-fill" :style="{ width: workflowPercent + '%' }"></div></div>
            <div class="setting-hint">
                {{ workflowPhaseLabel }}<template v-if="workflowCurrentJob.total"> · {{ workflowCurrentJob.current || 0 }} / {{ workflowCurrentJob.total }}</template>
                · 整体状态：{{ statusLabel(workflowStatus) }}
            </div>
            <button class="btn btn-small" v-if="['queued', 'running'].includes(workflowCurrentJob.status)" @click="cancelJob(workflowCurrentJob.id)">取消任务</button>
            <div class="error" v-if="workflowCurrentJob.error">{{ workflowCurrentJob.error }}</div>
        </div>

        <div class="data-storage-summary" v-if="storageStatus">
            <div><strong>SQLite：</strong><span class="mono">{{ storageStatus.path }}</span></div>
            <div><strong>数据库大小：</strong>{{ formatBytes(storageStatus.size_bytes) }}</div>
            <div><strong>数据集：</strong>{{ (storageStatus.datasets || []).length }} 个</div>
        </div>

        <div class="table-container" v-if="storageStatus && storageStatus.datasets && storageStatus.datasets.length">
            <table class="data-status-table">
                <thead><tr><th>数据集</th><th>记录数</th><th>分区</th><th>最新日期</th><th>更新时间</th></tr></thead>
                <tbody>
                    <tr v-for="dataset in storageStatus.datasets" :key="dataset.category + '/' + dataset.sub">
                        <td class="mono">{{ dataset.category }}/{{ dataset.sub || '-' }}</td>
                        <td>{{ dataset.row_count.toLocaleString() }}</td>
                        <td>{{ dataset.partition_count }}</td>
                        <td>{{ dataset.latest_date || '-' }}</td>
                        <td>{{ dataset.updated_at }}</td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>

    <div class="card">
        <h2>数据源</h2>
        <p class="ds-subtitle">当前口径下的可用数据集（共 {{ total }} 个），算子通过声明 data_needed 引用这些数据。</p>

        <!-- Category tabs -->
        <div class="ds-category-tabs">
            <button
                class="ds-cat-tab"
                :class="{ active: selectedCategory === '' }"
                @click="selectedCategory = ''"
            >全部 ({{ total }})</button>
            <button
                class="ds-cat-tab"
                :class="{ active: selectedCategory === cat }"
                v-for="cat in categories"
                :key="cat"
                @click="selectedCategory = cat"
            >{{ cat }} ({{ (grouped[cat] || []).length }})</button>
        </div>
    </div>

    <!-- Data source cards -->
    <div class="ds-grid">
        <div
            class="ds-card"
            v-for="ds in filteredSources"
            :key="ds.id"
            :class="{ 'ds-card-expanded': expandedId === ds.id, 'ds-card-unavailable': !ds.available }"
            @click="toggleExpand(ds.id)"
        >
            <div class="ds-card-header">
                <div class="ds-card-icon">
                    <span v-if="ds.category === '财报'">📊</span>
                    <span v-else-if="ds.category === '行情'">📈</span>
                    <span v-else-if="ds.category === '股东'">👥</span>
                    <span v-else-if="ds.category === '分红'">💰</span>
                    <span v-else-if="ds.category === '风险'">⚠️</span>
                    <span v-else-if="ds.category === '市场'">🌐</span>
                    <span v-else-if="ds.category === '业务'">🏢</span>
                    <span v-else>📋</span>
                </div>
                <div class="ds-card-info">
                    <div class="ds-card-name">{{ ds.name }}</div>
                    <div class="ds-card-id">{{ ds.id }}</div>
                </div>
                <span class="ds-card-cat">{{ ds.category }}</span>
            </div>
            <div class="ds-card-desc">{{ ds.description }}</div>
            <div class="setting-hint" v-if="!ds.available">当前数据口径不可用</div>

            <!-- Expanded detail -->
            <div class="ds-card-detail" v-if="expandedId === ds.id">
                <div class="ds-detail-row" v-if="ds.source">
                    <span class="ds-detail-label">数据来源</span>
                    <span class="ds-detail-value">{{ ds.source }}</span>
                </div>
                <div class="ds-detail-row" v-if="ds.snapshot_field">
                    <span class="ds-detail-label">Snapshot 字段</span>
                    <span class="ds-detail-value mono">{{ ds.snapshot_field }}</span>
                </div>
                <div class="ds-detail-row" v-if="ds.key_columns">
                    <span class="ds-detail-label">关键列</span>
                    <div class="ds-detail-columns">
                        <span class="ds-col-tag" v-for="col in ds.key_columns" :key="col">{{ col }}</span>
                    </div>
                </div>
                <div class="ds-detail-row" v-if="ds.always_available">
                    <span class="ds-detail-label">可用性</span>
                    <span class="ds-detail-value" style="color: var(--success-color)">始终可用</span>
                </div>
            </div>
        </div>
    </div>

    <!-- Test fetch -->
    <div class="card ds-test-card">
        <h3>测试数据获取</h3>
        <div class="ds-test-row">
            <div class="stock-search-group" style="flex:1;max-width:300px;">
                <input
                    type="text"
                    v-model="testCode"
                    placeholder="输入代码或名称，如 601288 或 农业银行"
                    @input="onStockInput"
                    @keyup.enter="selectFirstOrFetch"
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
            <button class="btn btn-primary" @click="testFetch" :disabled="testing">
                {{ testing ? '获取中...' : '测试获取' }}
            </button>
        </div>
        <div class="ds-test-stock-name" v-if="selectedStockName">已选择：{{ testCode }} {{ selectedStockName }}</div>
        <div class="ds-test-result" v-if="testResult">
            <div class="ds-test-summary">
                <span :class="testResult.success ? 'success' : 'error'">
                    {{ testResult.success ? '✓ 获取成功' : '✗ 获取失败' }}
                </span>
                <span v-if="testResult.elapsed">耗时 {{ testResult.elapsed }}s</span>
            </div>
            <div class="ds-test-sources" v-if="testResult.sources">
                <div
                    class="ds-test-source"
                    v-for="src in testResult.sources"
                    :key="src.name"
                >
                    <span class="ds-test-icon" :class="src.ok ? 'ok' : 'fail'">
                        {{ src.ok ? '✓' : '✗' }}
                    </span>
                    <span class="ds-test-name">{{ src.name }}</span>
                    <span class="ds-test-rows" v-if="src.rows !== undefined">{{ src.rows }} 行</span>
                    <span class="ds-test-error" v-if="src.error">{{ src.error }}</span>
                </div>
            </div>
        </div>
    </div>
</div>
    `,

    data() {
        return {
            categories: [],
            grouped: {},
            allSources: [],
            total: 0,
            selectedCategory: '',
            expandedId: null,
            testCode: '',
            selectedStockName: '',
            suggestions: [],
            showSuggestions: false,
            highlightIndex: -1,
            searchTimer: null,
            testing: false,
            testResult: null,
            providers: [],
            managementProvider: 'baostock',
            storageStatus: null,
            download: {
                start_date: '2015-01-01',
                end_date: new Intl.DateTimeFormat('en-CA').format(new Date()),
                codes: '',
            },
            jobs: [],
            activeJob: null,
            workflowRootId: null,
            refreshedJobId: null,
            pollTimer: null,
            actionMessage: '',
            actionSuccess: false,
            testingProvider: false,
        };
    },

    computed: {
        filteredSources() {
            if (!this.selectedCategory) return this.allSources;
            return this.grouped[this.selectedCategory] || [];
        },
        currentProvider() {
            return this.providers.find(p => p.name === this.managementProvider) || null;
        },
        hasRunningJob() {
            return this.jobs.some(job =>
                job.provider === this.managementProvider && ['queued', 'running'].includes(job.status)
            ) || (this.activeJob && ['queued', 'running'].includes(this.activeJob.status));
        },
        workflowRootJob() {
            if (!this.activeJob) return null;
            const rootId = this.workflowRootId || this.activeJob.parent_job_id || this.activeJob.id;
            return this.jobs.find(job => job.id === rootId) || (
                this.activeJob.id === rootId ? this.activeJob : null
            );
        },
        workflowFactorJob() {
            const root = this.workflowRootJob;
            if (!root || root.job_type === 'factors') return null;
            return this.jobs.find(job =>
                job.parent_job_id === root.id && job.job_type === 'factors'
            ) || null;
        },
        workflowCurrentJob() {
            const root = this.workflowRootJob;
            const factor = this.workflowFactorJob;
            if (factor && root && root.status === 'completed') return factor;
            return root || this.activeJob;
        },
        workflowTitle() {
            return this.jobTypeLabel(this.workflowRootJob?.job_type || this.activeJob?.job_type);
        },
        workflowPercent() {
            return Math.max(0, Math.min(100, Number(this.workflowCurrentJob?.percent || 0)));
        },
        workflowStatus() {
            return this.workflowFactorJob?.status || this.workflowRootJob?.status || this.activeJob?.status;
        },
        workflowPhaseLabel() {
            if (this.workflowFactorJob && this.workflowCurrentJob?.job_type === 'factors') {
                return '阶段 2/2 · 因子同步';
            }
            if (this.workflowFactorJob) return '阶段 1/2 · 数据更新';
            return this.workflowCurrentJob?.job_type === 'factors' ? '因子同步' : '数据更新';
        },
        workflowPhaseClass() {
            const status = this.workflowFactorJob?.status;
            return {
                active: ['queued', 'running'].includes(status),
                complete: status === 'completed',
                failed: ['failed', 'cancelled', 'interrupted'].includes(status),
            };
        },
    },

    created() {
        this.loadDataSources();
        this.loadManagement();
        this.pollTimer = setInterval(() => this.refreshJobs(), 2000);
    },

    unmounted() {
        if (this.pollTimer) clearInterval(this.pollTimer);
    },

    methods: {
        async loadDataSources() {
            try {
                const resp = await fetch('/api/datasources');
                const data = await resp.json();
                this.categories = data.categories || [];
                this.grouped = data.sources || {};
                this.allSources = data.all || [];
                this.total = data.total || 0;
            } catch (e) {
                console.error('Failed to load data sources:', e);
            }
        },

        async loadManagement() {
            try {
                const settings = await api.getSettings();
                this.download.start_date = settings.data_start_date || '2015-01-01';
                const response = await api.listDataProviders();
                this.providers = response.providers || [];
                this.managementProvider = response.selected || settings.data_provider || 'baostock';
                await this.loadStorageStatus();
                await this.refreshJobs();
            } catch (e) {
                this.actionSuccess = false;
                this.actionMessage = `加载数据管理状态失败: ${e.message}`;
            }
        },

        async changeProvider() {
            try {
                await api.updateSettings({ data_provider: this.managementProvider });
                this.workflowRootId = null;
                this.activeJob = null;
                await this.loadStorageStatus();
                await this.loadDataSources();
                await this.refreshJobs();
                this.actionSuccess = true;
                this.actionMessage = '数据口径已切换';
            } catch (e) {
                this.actionSuccess = false;
                this.actionMessage = `切换失败: ${e.message}`;
            }
        },

        async loadStorageStatus() {
            this.storageStatus = await api.getDataStatus(this.managementProvider);
        },

        parsedCodes() {
            return this.download.codes
                .split(/[\s,，;；]+/)
                .map(code => code.trim().toUpperCase())
                .filter(Boolean);
        },

        async startJob(jobType) {
            const codes = this.parsedCodes();
            if (['financials', 'full'].includes(jobType) && codes.length === 0) {
                const accepted = window.confirm('未指定股票代码，将处理全市场，可能需要很长时间。确定继续吗？');
                if (!accepted) return;
            }
            this.actionMessage = '';
            try {
                this.activeJob = await api.startDataJob({
                    provider: this.managementProvider,
                    job_type: jobType,
                    start_date: this.download.start_date || null,
                    end_date: this.download.end_date || null,
                    codes: codes,
                });
                this.workflowRootId = this.activeJob.id;
                this.actionSuccess = true;
                this.actionMessage = '任务已创建；如有派生因子需要更新，将自动续接并同步显示';
            } catch (e) {
                this.actionSuccess = false;
                this.actionMessage = `创建任务失败: ${e.message}`;
            }
        },

        async refreshJobs() {
            try {
                const response = await api.listDataJobs();
                this.jobs = response.jobs || [];
                let root = this.workflowRootId
                    ? this.jobs.find(job => job.id === this.workflowRootId)
                    : null;
                const running = this.jobs.find(job =>
                    job.provider === this.managementProvider && ['queued', 'running'].includes(job.status)
                );
                if (root && running) {
                    const currentFollowUp = this.jobs.find(job => job.parent_job_id === root.id);
                    const currentStatus = currentFollowUp?.status || root.status;
                    const belongsToCurrentWorkflow = running.id === root.id || running.parent_job_id === root.id;
                    if (!belongsToCurrentWorkflow && ['completed', 'failed', 'cancelled', 'interrupted'].includes(currentStatus)) {
                        this.workflowRootId = running.parent_job_id || running.id;
                        root = this.jobs.find(job => job.id === this.workflowRootId) || running;
                    }
                }
                if (!root) {
                    if (running) {
                        this.workflowRootId = running.parent_job_id || running.id;
                        root = this.jobs.find(job => job.id === this.workflowRootId) || running;
                    }
                }
                if (root) {
                    const followUp = this.jobs.find(job =>
                        job.parent_job_id === root.id && job.job_type === 'factors'
                    );
                    this.activeJob = followUp && root.status === 'completed' ? followUp : root;
                } else if (this.activeJob) {
                    const latest = this.jobs.find(job => job.id === this.activeJob.id);
                    if (latest) this.activeJob = latest;
                }
                if (this.activeJob && ['completed', 'failed', 'cancelled', 'interrupted'].includes(this.workflowStatus)) {
                    if (this.refreshedJobId !== this.activeJob.id) {
                        await this.loadStorageStatus();
                        this.refreshedJobId = this.activeJob.id;
                    }
                }
            } catch (_) {}
        },

        async cancelJob(jobId) {
            try {
                this.activeJob = await api.cancelDataJob(jobId);
            } catch (e) {
                this.actionSuccess = false;
                this.actionMessage = `取消失败: ${e.message}`;
            }
        },

        async testManagedProvider() {
            this.testingProvider = true;
            try {
                const result = await api.testDataProvider(this.managementProvider);
                this.actionSuccess = !!result.success;
                this.actionMessage = result.success ? `${result.message}（${result.elapsed}s）` : (result.error || result.message);
            } catch (e) {
                this.actionSuccess = false;
                this.actionMessage = e.message;
            } finally {
                this.testingProvider = false;
            }
        },

        formatBytes(bytes) {
            if (!bytes) return '0 B';
            const units = ['B', 'KB', 'MB', 'GB'];
            const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
            return `${(bytes / Math.pow(1024, index)).toFixed(index ? 1 : 0)} ${units[index]}`;
        },

        jobTypeLabel(type) {
            return ({ basic: '基础数据', market: '行情数据', financials: '财务数据', full: '完整初始化', incremental: '增量更新', factors: '因子同步' })[type] || type;
        },

        statusLabel(status) {
            return ({ queued: '排队中', running: '运行中', completed: '已完成', failed: '失败', cancelled: '已取消', interrupted: '已中断' })[status] || status;
        },

        onStockInput() {
            clearTimeout(this.searchTimer);
            this.highlightIndex = -1;
            this.selectedStockName = '';
            const q = this.testCode.trim();
            if (q.length < 1) { this.suggestions = []; this.showSuggestions = false; return; }
            this.searchTimer = setTimeout(async () => {
                try {
                    const resp = await fetch(`/api/analysis/stocks/search?q=${encodeURIComponent(q)}&limit=8`);
                    this.suggestions = await resp.json();
                    this.showSuggestions = this.suggestions.length > 0;
                } catch { this.suggestions = []; this.showSuggestions = false; }
            }, 200);
        },

        selectStock(s) {
            this.testCode = s.code;
            this.selectedStockName = s.name;
            this.showSuggestions = false;
            this.suggestions = [];
        },

        selectFirstOrFetch() {
            if (this.showSuggestions && this.suggestions.length > 0 && this.highlightIndex >= 0) {
                this.selectStock(this.suggestions[this.highlightIndex]);
            } else if (this.showSuggestions && this.suggestions.length > 0) {
                this.selectStock(this.suggestions[0]);
            } else {
                this.testFetch();
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

        toggleExpand(id) {
            this.expandedId = this.expandedId === id ? null : id;
        },

        async testFetch() {
            const code = this.testCode.trim();
            if (!code) return;

            this.testing = true;
            this.testResult = null;
            const start = Date.now();

            try {
                const resp = await fetch(`/api/analysis/test-data?ts_code=${encodeURIComponent(code)}`);
                const data = await resp.json();
                this.testResult = {
                    success: !data.error,
                    elapsed: ((Date.now() - start) / 1000).toFixed(1),
                    sources: data.sources || [],
                    error: data.error,
                };
            } catch (e) {
                this.testResult = {
                    success: false,
                    elapsed: ((Date.now() - start) / 1000).toFixed(1),
                    error: e.message,
                };
            } finally {
                this.testing = false;
            }
        },
    },
};
