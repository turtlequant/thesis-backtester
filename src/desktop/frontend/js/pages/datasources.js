/**
 * Data sources page component.
 *
 * Browse available data sources and test data fetching.
 */
const DataSourcesPage = {
    template: `
<div class="page-datasources">
    <div class="card">
        <h2>数据源</h2>
        <p class="ds-subtitle">分析引擎可用的全部数据源（共 {{ total }} 个），算子通过声明 data_needed 引用这些数据。</p>

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
            :class="{ 'ds-card-expanded': expandedId === ds.id }"
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
        };
    },

    computed: {
        filteredSources() {
            if (!this.selectedCategory) return this.allSources;
            return this.grouped[this.selectedCategory] || [];
        },
    },

    created() {
        this.loadDataSources();
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
