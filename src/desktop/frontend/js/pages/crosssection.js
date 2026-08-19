/**
 * Cross-sectional screening workspace.
 *
 * One object-centred workbench coordinates strategy editing, one-snapshot
 * screening and multi-snapshot validation without coupling their engines.
 */
const SCREENING_STRATEGY_KEY = 'screening-strategy-id';
const SCREENING_DRAFT_KEY = 'screening-workbench-draft-v1';

function cloneScreening(value) {
    return JSON.parse(JSON.stringify(value));
}

function stableScreeningJson(value) {
    if (Array.isArray(value)) return `[${value.map(stableScreeningJson).join(',')}]`;
    if (value && typeof value === 'object') {
        return `{${Object.keys(value).sort().filter(key => value[key] !== undefined).map(key => `${JSON.stringify(key)}:${stableScreeningJson(value[key])}`).join(',')}}`;
    }
    return JSON.stringify(value);
}

function screeningDefinitionIdentity(strategy) {
    return strategy?.definition ? stableScreeningJson(strategy.definition) : '';
}

function preferredScreeningStrategy(strategies) {
    const saved = localStorage.getItem(SCREENING_STRATEGY_KEY);
    return strategies.find(item => item.id === saved)
        || strategies[0]
        || null;
}

function rememberScreeningStrategy(id) {
    if (!id) return;
    const changed = localStorage.getItem(SCREENING_STRATEGY_KEY) !== id;
    localStorage.setItem(SCREENING_STRATEGY_KEY, id);
    if (changed) {
        window.dispatchEvent(new CustomEvent('screening-strategy-selected', {
            detail: { id },
        }));
    }
}

function screeningContext(page, strategy, extra = {}) {
    if (!window.setAppContext) return;
    window.setAppContext({
        workspace: 'cross_section',
        research_path: page,
        screening_strategy: strategy ? {
            id: strategy.id,
            name: strategy.name,
            description: strategy.description || '',
            definition: strategy.definition,
        } : null,
        ...extra,
    });
}

const ScreeningStrategiesPage = {
    props: { embedded: { type: Boolean, default: false } },
    template: `
<div class="page screening-page">
    <workspace-page-header v-if="!embedded" eyebrow="截面筛选 · 规则管理" title="筛选策略" description="把过滤、排序和分散约束保存为可复用的纯数值规则。">
        <template #meta><span class="page-header-chip"><span>策略边界</span>只定义数值规则</span></template>
    </workspace-page-header>

    <div class="screening-workbench">
        <aside class="card strategy-library-card screening-strategy-list">
            <div class="section-title-row"><div><h2>策略库</h2><p>所有策略均由你创建并独立维护。</p></div><button class="btn btn-primary btn-small" @click="newStrategy">新建</button></div>
            <button class="strategy-list-item screening-strategy-item" v-for="strategy in strategies" :key="strategy.id" :class="{ active: editor.id === strategy.id }" @click="selectStrategy(strategy.id)">
                <span><strong>{{ strategy.name }}</strong><small>{{ strategy.description || '暂无说明' }}</small></span>
                <em>我的</em>
            </button>
            <div class="screening-empty" v-if="!strategies.length">还没有筛选策略</div>
        </aside>

        <section class="card strategy-editor-card">
            <div class="section-title-row">
                <div><h2>{{ editor.id ? editor.name : '新建筛选策略' }}</h2><p>先过滤不合格样本，再对剩余股票进行加权排名。</p></div>
            </div>
            <div class="strategy-meta-grid screening-meta-grid">
                <div class="setting-item"><label>策略名称</label><input v-model.trim="editor.name" placeholder="例如：低估值高质量" /></div>
                <div class="setting-item strategy-description"><label>说明</label><input v-model.trim="editor.description" placeholder="说明策略目标和适用范围" /></div>
                <label class="checkbox-row screening-checkbox"><input type="checkbox" v-model="editor.exclude_st" /> 排除 ST 与退市标的</label>
                <div class="setting-item"><label>单行业最多入选</label><input type="number" v-model.number="editor.industry_cap" min="0" /><div class="setting-hint">0 表示不限制</div></div>
            </div>

            <div class="rule-section screening-section">
                <div class="section-title-row screening-section-head"><div><h3>过滤条件</h3><p>支持固定数值区间和当期截面分位区间。</p></div><button class="btn btn-small" @click="addFilter" :disabled="!fields.length">添加条件</button></div>
                <div class="rule-row filter-rule-row screening-rule" v-for="(rule, index) in editor.filters" :key="index">
                    <input type="checkbox" v-model="rule.enabled" title="启用" />
                    <div class="rule-field-control"><select v-model="rule.field"><optgroup v-for="group in fieldGroups" :key="group.name" :label="group.name"><option v-for="field in group.items" :key="field.id" :value="field.id">{{ field.name }}</option></optgroup></select><small>{{ filterFieldHint(rule) }}</small></div>
                    <select v-model="rule.mode"><option value="value">数值区间</option><option value="percentile">截面分位</option></select>
                    <template v-if="rule.mode === 'value'"><input type="number" v-model.number="rule.min" placeholder="最小值" /><span>至</span><input type="number" v-model.number="rule.max" placeholder="最大值" /></template>
                    <template v-else><input type="number" v-model.number="rule.percentile_min" min="0" max="100" placeholder="最低分位" /><span>% 至</span><input type="number" v-model.number="rule.percentile_max" min="0" max="100" placeholder="最高分位" /></template>
                    <button class="rule-remove" @click="removeFilter(index)" title="删除条件">×</button>
                </div>
                <div class="screening-empty" v-if="!editor.filters.length">没有过滤条件，将直接进入排名。</div>
            </div>

            <div class="rule-section screening-section">
                <div class="section-title-row screening-section-head"><div><h3>加权排名</h3><p>各因子先转为截面分位，权重按合计值自动归一。</p></div><div class="screening-ranking-tools"><span class="weight-total" :class="{ warning: Math.abs(rankingWeightTotal - 1) > 0.0001 }">权重合计 {{ rankingWeightTotal.toFixed(2) }}</span><button class="btn btn-small" @click="addRanking" :disabled="!fields.length">添加因子</button></div></div>
                <div class="rule-row ranking-rule-row ranking-rule" v-for="(node, index) in editor.ranking" :key="index">
                    <span class="ranking-index">R{{ index + 1 }}</span>
                    <select v-model="node.field"><optgroup v-for="group in fieldGroups" :key="group.name" :label="group.name"><option v-for="field in group.items" :key="field.id" :value="field.id">{{ field.name }}</option></optgroup></select>
                    <select v-model="node.direction"><option value="desc">越高越好</option><option value="asc">越低越好</option></select>
                    <label>权重 <input type="number" v-model.number="node.weight" min="0.01" step="0.1" /></label>
                    <select v-model="node.na_handling"><option value="neutral">缺失记中性</option><option value="worst">缺失记最差</option></select>
                    <button class="rule-remove" @click="removeRanking(index)" title="删除因子">×</button>
                </div>
                <div class="screening-empty" v-if="!editor.ranking.length">没有排名因子，结果将保留原始顺序。</div>
            </div>

            <div class="research-actions screening-actions">
                <button class="btn btn-primary" @click="saveStrategy" :disabled="!editor.name || saving">{{ saving ? '保存中…' : (editor.id ? '保存修改' : '保存策略') }}</button>
                <button class="btn" @click="copyStrategy" v-if="editor.id">复制为新策略</button>
                <button class="btn btn-danger" @click="deleteStrategy" v-if="editor.id">删除</button>
            </div>
            <div class="error-msg" v-if="error">{{ error }}</div>
        </section>
    </div>
</div>`,

    data() {
        return {
            fields: [], strategies: [], saving: false, error: '',
            editor: { id: null, name: '', description: '', exclude_st: true, industry_cap: 0, filters: [], ranking: [] },
        };
    },
    computed: {
        fieldGroups() {
            const groups = {};
            for (const field of this.fields) (groups[field.group] ||= []).push(field);
            return Object.entries(groups).map(([name, items]) => ({ name, items }));
        },
        rankingWeightTotal() { return this.editor.ranking.reduce((total, node) => total + Number(node.weight || 0), 0); },
    },
    watch: {
        editor: {
            deep: true,
            handler() { this.syncContext(); },
        },
    },
    methods: {
        emptyEditor() { return { id: null, name: '', description: '', exclude_st: true, industry_cap: 0, filters: [], ranking: [] }; },
        definition() { return { exclude_st: this.editor.exclude_st, industry_cap: Number(this.editor.industry_cap || 0), filters: this.editor.filters.map(rule => ({ ...rule })), ranking: this.editor.ranking.map(node => ({ ...node })) }; },
        async load() {
            try {
                [this.fields, this.strategies] = await Promise.all([apiFetch('/api/research/screening-fields'), apiFetch('/api/research/screening-strategies')]);
                const selected = preferredScreeningStrategy(this.strategies);
                if (selected) this.selectStrategy(selected.id); else this.newStrategy();
            } catch (error) { this.error = error.message; }
        },
        selectStrategy(id) {
            const strategy = this.strategies.find(item => item.id === id);
            if (!strategy) return;
            this.editor = { id: strategy.id, name: strategy.name, description: strategy.description || '', ...cloneScreening(strategy.definition) };
            rememberScreeningStrategy(id); this.error = ''; this.syncContext();
        },
        newStrategy() { this.editor = this.emptyEditor(); this.error = ''; this.syncContext(); },
        copyStrategy() { this.editor = { ...cloneScreening(this.editor), id: null, name: `${this.editor.name} 副本` }; },
        addFilter() { const used = new Set(this.editor.filters.map(rule => rule.field)); const field = this.fields.find(item => !used.has(item.id)) || this.fields[0]; if (field) this.editor.filters.push({ field: field.id, enabled: true, mode: 'value', min: '', max: '' }); },
        removeFilter(index) { this.editor.filters.splice(index, 1); },
        addRanking() { const used = new Set(this.editor.ranking.map(node => node.field)); const field = this.fields.find(item => !used.has(item.id)) || this.fields[0]; if (field) this.editor.ranking.push({ field: field.id, weight: 1, direction: field.preferred_direction || 'desc', na_handling: 'neutral' }); },
        removeRanking(index) { this.editor.ranking.splice(index, 1); },
        fieldUnit(id) {
            return ({ total_mv: '万元', circ_mv: '万元', market_cap_yi: '亿元', circ_mv_yi: '亿元', dv: '%', turnover_rate: '%', pe_ttm: '倍', pb: '倍', ps_ttm: '倍', pcf_ncf_ttm: '倍' })[id] || '';
        },
        filterFieldHint(rule) {
            const unit = this.fieldUnit(rule.field);
            if (['total_mv', 'circ_mv'].includes(rule.field) && rule.mode === 'value') {
                const values = [rule.min, rule.max].filter(value => value !== '' && value !== null && value !== undefined && Number.isFinite(Number(value)));
                if (values.length) return `单位：万元 · ${values.map(value => `${Number(value) / 10000}亿元`).join(' 至 ')}`;
            }
            return unit ? `单位：${unit}` : (this.fields.find(field => field.id === rule.field)?.description || '');
        },
        async saveStrategy() {
            this.saving = true; this.error = '';
            try {
                const payload = { name: this.editor.name, description: this.editor.description, definition: this.definition() };
                const saved = await apiFetch(this.editor.id ? `/api/research/screening-strategies/${this.editor.id}` : '/api/research/screening-strategies', { method: this.editor.id ? 'PUT' : 'POST', body: JSON.stringify(payload) });
                const index = this.strategies.findIndex(item => item.id === saved.id);
                if (index >= 0) this.strategies.splice(index, 1, saved); else this.strategies.push(saved);
                this.selectStrategy(saved.id);
            } catch (error) { this.error = error.message; } finally { this.saving = false; }
        },
        async deleteStrategy() {
            if (!confirm(`删除筛选策略“${this.editor.name}”？历史回测快照不会受影响。`)) return;
            try {
                await apiFetch(`/api/research/screening-strategies/${this.editor.id}`, { method: 'DELETE' });
                this.strategies = this.strategies.filter(item => item.id !== this.editor.id);
                const selected = preferredScreeningStrategy(this.strategies);
                if (selected) this.selectStrategy(selected.id); else this.newStrategy();
            } catch (error) { this.error = error.message; }
        },
        syncContext() {
            const strategy = this.editor.name ? {
                id: this.editor.id,
                name: this.editor.name,
                description: this.editor.description,
                definition: this.definition(),
            } : null;
            screeningContext('筛选策略', strategy, {
                available_fields: this.fields.map(field => ({
                    id: field.id,
                    name: field.name,
                    description: field.description,
                    preferred_direction: field.preferred_direction,
                })),
            });
        },
        async handleResourceUpdated(event) {
            const detail = event.detail || {};
            if (!String(detail.action?.path || '').startsWith('/api/research/screening-strategies')) return;
            try {
                this.strategies = await apiFetch('/api/research/screening-strategies');
                const selectedId = detail.result?.id || this.editor.id;
                if (selectedId && this.strategies.some(item => item.id === selectedId)) this.selectStrategy(selectedId);
            } catch (error) { this.error = error.message; }
        },
    },
    mounted() {
        this._resourceUpdatedHandler = event => this.handleResourceUpdated(event);
        window.addEventListener('app-resource-updated', this._resourceUpdatedHandler);
        this.load();
    },
    beforeUnmount() {
        if (this._resourceUpdatedHandler) window.removeEventListener('app-resource-updated', this._resourceUpdatedHandler);
    },
};

const ScreeningCurrentPage = {
    props: {
        embedded: { type: Boolean, default: false },
        selectedStrategyId: { type: String, default: '' },
    },
    template: `
<div class="page screening-page">
    <workspace-page-header v-if="!embedded" eyebrow="截面筛选 · 单次执行" title="截面选股" description="选择已保存策略和指定日期，生成一份口径明确、可以导出的股票名单。">
        <template #meta><span class="page-header-chip"><span>执行边界</span>不修改策略</span></template>
    </workspace-page-header>

    <section class="card screening-run-card screening-direct-controls">
        <div class="screening-execution-grid" :class="{ compact: embedded }">
            <div class="setting-item screening-strategy-select" v-if="!embedded"><label>筛选策略</label><select v-model="strategyId"><option v-for="strategy in strategies" :key="strategy.id" :value="strategy.id">{{ strategy.name }}</option></select></div>
            <div class="setting-item"><label>截面日期</label><input type="date" v-model="asOfDate" /><div class="setting-hint" v-if="status.latest_date">本地最新可用：{{ status.latest_date }}</div></div>
            <div class="setting-item"><label>入选数量</label><input type="number" v-model.number="topN" min="1" max="200" /></div>
            <button class="btn btn-primary screening-run-button" @click="run()" :disabled="running || !selectedStrategy">{{ running ? '计算中…' : '运行筛选' }}</button>
        </div>
        <div class="strategy-summary" v-if="selectedStrategy && !embedded">
            <div><span>策略</span><strong>{{ selectedStrategy.name }}</strong></div>
            <div><span>过滤条件</span><strong>{{ selectedStrategy.definition.filters.length }}</strong></div>
            <div><span>排名因子</span><strong>{{ selectedStrategy.definition.ranking.length }}</strong></div>
            <div><span>行业上限</span><strong>{{ selectedStrategy.definition.industry_cap || '不限' }}</strong></div>
            <p>{{ selectedStrategy.description || '暂无策略说明' }}</p>
        </div>
        <div class="error-msg" v-if="error">{{ error }}</div>
    </section>

    <section class="card screening-preview-card" v-if="result">
        <div class="section-title-row"><div><h2>选股结果</h2><p>结果绑定本次策略版本、数据源和实际交易截面。</p></div><div class="screening-result-actions"><span class="method-badge">{{ selectedStrategy?.name }}</span><button class="btn btn-small" @click="exportCsv" :disabled="!result.stocks.length">导出 CSV</button></div></div>
        <div class="screening-run-facts screening-current-facts"><div><span>策略版本</span><strong>{{ strategyVersion }}</strong></div><div><span>请求日期</span><strong>{{ result.requested_date }}</strong></div><div><span>实际截面</span><strong>{{ result.effective_date || result.requested_date }}</strong></div><div><span>数据源</span><strong>{{ status.provider || '—' }}</strong></div><div><span>数据截止</span><strong>{{ status.latest_date || '—' }}</strong></div></div>
        <div class="screening-funnel"><div><span>原始股票池</span><strong>{{ result.funnel.universe }}</strong></div><i>→</i><div><span>条件命中</span><strong>{{ result.funnel.after_filters }}</strong></div><i>→</i><div><span>最终展示</span><strong>{{ result.funnel.selected }}</strong></div></div>
        <div class="table-wrap" v-if="result.stocks.length"><table class="research-result-table preview-result-table"><thead><tr><th>代码</th><th>名称</th><th>行业</th><th v-for="column in resultColumns" :key="column">{{ columnName(column) }}</th></tr></thead><tbody><tr v-for="stock in result.stocks" :key="stock.ts_code"><td>{{ stock.ts_code }}</td><td>{{ stock.stock_name || '—' }}</td><td>{{ stock.industry || '—' }}</td><td v-for="column in resultColumns" :key="column">{{ formatNumber(stock[column]) }}</td></tr></tbody></table></div>
        <div class="screening-empty" v-else>当前策略没有命中股票。</div>
    </section>
</div>`,
    data() { return { fields: [], strategies: [], status: {}, strategyId: '', asOfDate: '', topN: 30, running: false, result: null, error: '', autoRunReady: false, autoRunTimer: null, runSequence: 0 }; },
    computed: {
        selectedStrategy() { return this.strategies.find(item => item.id === this.strategyId) || null; },
        fieldById() { return Object.fromEntries(this.fields.map(field => [field.id, field])); },
        resultColumns() {
            if (!this.result?.stocks?.length || !this.selectedStrategy) return [];
            const definition = this.selectedStrategy.definition;
            const preferred = ['tier_score', ...definition.filters.map(rule => rule.field), ...definition.ranking.map(node => node.field)];
            return [...new Set(preferred)].filter(column => column && Object.prototype.hasOwnProperty.call(this.result.stocks[0], column));
        },
        strategyVersion() { const value = this.selectedStrategy?.updated_at || ''; return value.includes('T') ? value.replace('T', ' ').slice(0, 16) : (value || '—'); },
    },
    watch: {
        strategyId() { rememberScreeningStrategy(this.strategyId); this.scheduleRun(); this.syncContext(); },
        asOfDate() { this.scheduleRun(); },
        topN() { this.scheduleRun(); },
        selectedStrategyId(value) {
            if (this.embedded && value && value !== this.strategyId) this.strategyId = value;
        },
    },
    methods: {
        async load() {
            try {
                [this.fields, this.strategies, this.status] = await Promise.all([apiFetch('/api/research/screening-fields'), apiFetch('/api/research/screening-strategies'), apiFetch('/api/research/screening-status')]);
                this.strategyId = (this.embedded && this.selectedStrategyId) || preferredScreeningStrategy(this.strategies)?.id || '';
                if (!this.asOfDate) this.asOfDate = this.status.latest_date || new Date().toISOString().slice(0, 10);
                await Vue.nextTick();
                this.autoRunReady = true;
                if (this.selectedStrategy && this.asOfDate) await this.run();
                else this.syncContext();
            } catch (error) { this.error = error.message; }
        },
        scheduleRun() {
            if (!this.autoRunReady) return;
            clearTimeout(this.autoRunTimer);
            this.result = null;
            const sequence = ++this.runSequence;
            this.syncContext();
            if (!this.selectedStrategy || !this.asOfDate) { this.running = false; return; }
            this.autoRunTimer = setTimeout(() => this.run(sequence), 450);
        },
        async run(scheduledSequence = null) {
            clearTimeout(this.autoRunTimer);
            const sequence = scheduledSequence === null ? ++this.runSequence : scheduledSequence;
            if (sequence !== this.runSequence || !this.selectedStrategy || !this.asOfDate) return;
            const definition = cloneScreening(this.selectedStrategy.definition);
            const asOfDate = this.asOfDate;
            const topN = Number(this.topN || 30);
            this.running = true; this.error = '';
            try {
                const result = await apiFetch('/api/research/screening-preview', { method: 'POST', body: JSON.stringify({ definition, as_of_date: asOfDate, top_n: topN }) });
                if (sequence === this.runSequence) this.result = result;
            } catch (error) { if (sequence === this.runSequence) this.error = error.message; }
            finally { if (sequence === this.runSequence) { this.running = false; this.syncContext(); } }
        },
        syncContext() { screeningContext('截面选股', this.selectedStrategy, { screening_result: this.result, available_fields: this.fields.map(field => ({ id: field.id, name: field.name, description: field.description, preferred_direction: field.preferred_direction })) }); },
        exportCsv() {
            if (!this.result?.stocks?.length) return;
            const columns = ['ts_code', 'stock_name', 'industry', ...this.resultColumns];
            const quote = value => `"${String(value ?? '').replaceAll('"', '""')}"`;
            const lines = [columns.map(column => quote(this.columnName(column))).join(','), ...this.result.stocks.map(stock => columns.map(column => quote(stock[column])).join(','))];
            const blob = new Blob([`\ufeff${lines.join('\r\n')}`], { type: 'text/csv;charset=utf-8' });
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            link.download = `${this.selectedStrategy?.name || '截面选股'}_${this.result.effective_date || this.result.requested_date}.csv`;
            link.click(); URL.revokeObjectURL(link.href);
        },
        columnName(id) { return ({ ts_code: '代码', stock_name: '名称', industry: '行业', tier_score: '综合分' })[id] || this.fieldById[id]?.name || id; },
        formatNumber(value) { if (value === null || value === undefined || value === '') return '—'; return typeof value === 'number' ? Number(value.toFixed(4)) : value; },
        async handleResourceUpdated(event) {
            if (!String(event.detail?.action?.path || '').startsWith('/api/research/screening-strategies')) return;
            try {
                this.strategies = await apiFetch('/api/research/screening-strategies');
                if (!this.selectedStrategy) this.strategyId = preferredScreeningStrategy(this.strategies)?.id || '';
                this.scheduleRun();
                this.syncContext();
            } catch (error) { this.error = error.message; }
        },
    },
    mounted() {
        this._resourceUpdatedHandler = event => this.handleResourceUpdated(event);
        window.addEventListener('app-resource-updated', this._resourceUpdatedHandler);
        this.load();
    },
    beforeUnmount() {
        if (this._resourceUpdatedHandler) window.removeEventListener('app-resource-updated', this._resourceUpdatedHandler);
        clearTimeout(this.autoRunTimer);
        this.runSequence += 1;
    },
};

const ScreeningBacktestPage = {
    props: {
        embedded: { type: Boolean, default: false },
        selectedStrategyId: { type: String, default: '' },
    },
    template: `
<div class="page screening-page screening-backtest-page">
    <workspace-page-header v-if="!embedded" eyebrow="截面筛选 · 多截面验证" title="历史验证" description="冻结筛选策略快照，在多个历史截面检验稳定性和前瞻收益。">
        <template #meta><span class="page-header-chip"><span>结果口径</span>冻结策略快照</span></template>
    </workspace-page-header>

    <section class="card research-config-card screening-backtest-config">
        <div class="section-title-row">
            <div><h2>回测方案</h2><p>选择已保存的数值策略，再定义历史截面与每期组合规模。</p></div>
            <div class="setting-item screening-result-picker" v-if="resultJobs.length"><label>查看已有结果</label><select :value="currentResultMatchesForm ? currentJob.id : ''" @change="selectJobById($event.target.value)" :disabled="isRunning"><option value="" disabled>选择一个已完成方案</option><option v-for="job in resultJobs" :key="job.id" :value="job.id">{{ resultOptionLabel(job) }}</option></select></div>
        </div>

        <div class="screening-backtest-strategy-row">
            <div class="setting-item"><label>筛选策略</label><select v-model="runForm.screening_strategy_id" :disabled="isRunning"><option value="" disabled>请选择已保存策略</option><option v-for="strategy in strategies" :key="strategy.id" :value="strategy.id">{{ strategy.name }}</option></select></div>
            <div class="screening-backtest-strategy-structure" v-if="selectedStrategy">
                <label>策略结构</label>
                <div class="screening-backtest-strategy-summary">
                    <div><span>过滤条件</span><strong>{{ selectedStrategy.definition.filters.length }}</strong></div>
                    <div><span>排名指标</span><strong>{{ selectedStrategy.definition.ranking.length }}</strong></div>
                    <div><span>行业上限</span><strong>{{ selectedStrategy.definition.industry_cap || '不限' }}</strong></div>
                    <p>{{ selectedStrategy.description || '纯数值筛选策略；运行时会冻结当前版本。' }}</p>
                </div>
            </div>
        </div>

        <div class="research-form-grid screening-backtest-params">
                <div class="setting-item"><label>开始截面</label><input type="date" v-model="runForm.start_date" :disabled="isRunning" /></div>
                <div class="setting-item"><label>结束截面</label><input type="date" v-model="runForm.end_date" :disabled="isRunning" /><div class="setting-hint" v-if="status.latest_date">本地最新可用：{{ status.latest_date }}</div></div>
                <div class="setting-item"><label>截面频率</label><select v-model="runForm.interval" :disabled="isRunning"><option value="1m">每月</option><option value="3m">每季度</option><option value="6m">每半年</option><option value="1y">每年</option></select></div>
                <div class="setting-item"><label>每期入选数量</label><input type="number" v-model.number="runForm.top_n" min="1" max="1000" :disabled="isRunning" /></div>
        </div>
        <div class="research-actions"><button class="btn btn-primary" @click="startRun" :disabled="!canStart">{{ runButtonLabel }}</button><span class="setting-hint">固定策略版本 → 多截面选股 → 前瞻收益 → 基准比较</span><span class="screening-scheme-state matched" v-if="currentResultMatchesForm">已有完全匹配结果</span><span class="screening-scheme-state pending" v-else-if="formComplete && !isRunning">当前方案尚未运行，旧参数结果已隐藏</span></div>
        <div class="error-msg" v-if="error">{{ error }}</div>
    </section>

    <section class="card research-progress-card screening-execution-progress" v-if="currentJob && isRunning">
        <div class="section-title-row">
            <div><div class="workspace-eyebrow">历史验证进度</div><h2>{{ progressTitle }}</h2><p>{{ currentJob.message }}</p></div>
            <span class="badge badge-running">{{ stageLabel(currentJob.stage) }}</span>
        </div>
        <div class="screening-progress-steps">
            <div class="screening-progress-step" :class="progressStepClass('screening')"><i>1</i><span><strong>历史截面筛选</strong><small>生成各期候选组合</small></span></div>
            <div class="screening-progress-connector"></div>
            <div class="screening-progress-step" :class="progressStepClass('evaluation')"><i>2</i><span><strong>前向收益评估</strong><small>收益采集与基准比较</small></span></div>
        </div>
        <div class="screening-progress-head"><span>整体进度</span><strong>{{ overallProgress }}%</strong></div>
        <div class="screening-progress-track"><span :style="{ width: overallProgress + '%' }"></span></div>
        <div class="screening-progress-facts">
            <span v-if="progressTotal">{{ progressCounter }}</span>
            <span v-if="jobProgress.current_date">当前截面 <strong>{{ jobProgress.current_date }}</strong></span>
            <span v-if="jobProgress.candidate_count !== undefined">本期入选 <strong>{{ jobProgress.candidate_count }}</strong> 只</span>
            <span v-if="jobProgress.cached">缓存命中 <strong>{{ jobProgress.cached }}</strong></span>
            <span v-if="jobProgress.speed">速度 <strong>{{ jobProgress.speed }}</strong> 只/秒</span>
            <span v-if="jobProgress.eta_seconds">预计剩余 <strong>{{ formatDuration(jobProgress.eta_seconds) }}</strong></span>
        </div>
    </section>

    <section class="card research-result-card screening-backtest-result" v-if="currentResultMatchesForm">
        <div class="section-title-row"><div><div class="workspace-eyebrow">历史验证结果</div><h2>{{ currentJob.result.screening_strategy_name || currentJob.result.strategy }}</h2><p>结果绑定运行时策略快照与下列参数，后续修改策略不会改变本次结果。</p></div><span class="badge" :class="currentResultUsesLegacyOutcome ? 'badge-warning' : 'badge-completed'">{{ currentResultUsesLegacyOutcome ? '旧收益口径' : '已完成' }}</span></div>
        <div class="result-methodology-warning" v-if="currentResultUsesLegacyOutcome">该结果生成于当前后复权收益口径前，可能使用不复权价格；更早版本还可能把尚未走完的持有期记为部分收益。统计与图表仅作历史参考，新任务统一使用后复权前向收益。</div>

        <div class="screening-run-facts">
            <div><span>执行时间</span><strong>{{ resultVersion }}</strong></div>
            <div><span>回测区间</span><strong>{{ currentJob.params?.start_date }} — {{ currentJob.params?.end_date }}</strong></div>
            <div><span>截面频率</span><strong>{{ intervalLabel(currentJob.params?.interval || currentJob.result.interval) }}</strong></div>
            <div><span>每期组合</span><strong>Top {{ currentJob.params?.top_n }}</strong></div>
            <div><span>有效截面</span><strong>{{ currentJob.result.dates.length }} 期</strong></div>
        </div>

        <div class="screening-result-focus">
            <div><h3>主周期表现</h3><p>持有期自动与截面频率一致，避免跨期重叠造成含义混乱。</p></div>
            <span class="method-badge">{{ intervalLabel(currentJob.params?.interval) }}截面 · {{ focusPeriod }}持有</span>
        </div>
        <div class="screening-performance-cards">
            <article v-for="row in performanceRows" :key="row.key" :class="'series-' + row.key">
                <span>{{ row.label }}</span><strong :class="returnClass(periodStat(row)?.mean)">{{ percent(periodStat(row)?.mean) }}</strong>
                <div><small>胜率 {{ percent(periodStat(row)?.win_rate, false) }}</small><small v-if="row.key !== 'market'">超额 {{ percent(excessReturn(row)) }}</small><small>{{ periodStat(row)?.count || 0 }} 样本</small></div>
            </article>
        </div>

        <article class="screening-chart-card screening-equity-chart-card" v-if="equityCurve">
            <div><h3>逐期复合收益曲线</h3><p>每个截面使用与截面频率一致的前瞻收益逐期复合；这是策略研究曲线，不含交易成本。</p></div>
            <div class="screening-chart-legend"><span v-for="series in equityCurve.series" :key="series.key"><i :style="{ background: series.color }"></i>{{ series.label }} <strong :class="returnClass(series.finalReturn)">{{ percent(series.finalReturn) }}</strong></span></div>
            <svg class="screening-equity-chart" :viewBox="'0 0 ' + equityCurve.width + ' ' + equityCurve.height" role="img" aria-label="逐期复合收益曲线">
                <g v-for="tick in equityCurve.ticks" :key="tick.value"><line :x1="equityCurve.left" :x2="equityCurve.width - equityCurve.right" :y1="tick.y" :y2="tick.y" class="chart-grid-line"/><text :x="equityCurve.left - 8" :y="tick.y + 4" class="chart-axis-label" text-anchor="end">{{ percent(tick.value - 1, false) }}</text></g>
                <line :x1="equityCurve.left" :x2="equityCurve.width - equityCurve.right" :y1="equityCurve.baseY" :y2="equityCurve.baseY" class="chart-zero-line"/>
                <g v-for="series in equityCurve.series" :key="series.key"><polyline :points="series.points" class="equity-chart-line" :stroke="series.color"/><circle v-for="dot in series.dots" :key="series.key + dot.date" :cx="dot.x" :cy="dot.y" r="2.6" :fill="series.color"><title>{{ series.label }} {{ dot.date }}：{{ percent(dot.value - 1) }}</title></circle></g>
                <text v-for="label in equityCurve.labels" :key="label.text" :x="label.x" :y="equityCurve.height - 7" class="chart-axis-label" :text-anchor="label.anchor">{{ label.text }}</text>
            </svg>
        </article>
        <div class="screening-curve-unavailable" v-else>该结果生成于逐截面收益数据升级前。重新运行当前方案后，才能展示真实复合收益曲线。</div>

        <div class="screening-result-charts">
            <article class="screening-chart-card" v-if="returnChart">
                <div><h3>各持有期平均收益</h3><p>同一策略下，筛选池、Top 排名与沪深 300 的横向比较。</p></div>
                <div class="screening-chart-legend"><span v-for="row in performanceRows" :key="row.key"><i :style="{ background: chartColor(row.key) }"></i>{{ row.label }}</span></div>
                <svg class="screening-return-chart" :viewBox="'0 0 ' + returnChart.width + ' ' + returnChart.height" role="img" aria-label="各持有期平均收益柱状图">
                    <g v-for="tick in returnChart.ticks" :key="tick.value"><line :x1="returnChart.left" :x2="returnChart.width - returnChart.right" :y1="tick.y" :y2="tick.y" class="chart-grid-line"/><text :x="returnChart.left - 8" :y="tick.y + 4" class="chart-axis-label" text-anchor="end">{{ percent(tick.value, false) }}</text></g>
                    <line :x1="returnChart.left" :x2="returnChart.width - returnChart.right" :y1="returnChart.zeroY" :y2="returnChart.zeroY" class="chart-zero-line"/>
                    <g v-for="bar in returnChart.bars" :key="bar.key"><rect :x="bar.x" :y="bar.y" :width="bar.width" :height="bar.height" :fill="bar.color" rx="2"><title>{{ bar.label }} {{ bar.period }}：{{ percent(bar.value) }}</title></rect></g>
                    <text v-for="label in returnChart.labels" :key="label.text" :x="label.x" :y="returnChart.height - 9" class="chart-axis-label" text-anchor="middle">{{ label.text }}</text>
                </svg>
            </article>

            <article class="screening-chart-card screening-count-chart-card" v-if="countChart">
                <div><h3>截面入选数量</h3><p>观察历史截面中候选数量是否稳定。</p></div>
                <div class="screening-count-summary"><span>最低<strong>{{ countChart.min }}</strong></span><span>平均<strong>{{ countChart.average }}</strong></span><span>最高<strong>{{ countChart.max }}</strong></span></div>
                <svg class="screening-count-chart" :viewBox="'0 0 ' + countChart.width + ' ' + countChart.height" role="img" aria-label="历史截面入选数量折线图">
                    <polygon :points="countChart.area" class="count-chart-area" />
                    <polyline :points="countChart.points" class="count-chart-line" />
                    <circle v-for="point in countChart.dots" :key="point.date" :cx="point.x" :cy="point.y" r="3"><title>{{ point.date }}：{{ point.value }} 只</title></circle>
                    <text v-for="label in countChart.labels" :key="label.text" :x="label.x" :y="countChart.height - 6" class="chart-axis-label" :text-anchor="label.anchor">{{ label.text }}</text>
                </svg>
            </article>
        </div>

        <div class="screening-run-comparison" v-if="comparisonRows.length > 1">
            <div class="screening-detail-table-head"><div><h3>当前策略方案比较</h3><p>仅展示当前最终策略产生的结果；每套方案按自身截面频率对应的持有期展示。</p></div></div>
            <div class="table-wrap"><table class="research-result-table"><thead><tr><th>策略与区间</th><th>截面参数</th><th>主周期</th><th>筛选池收益</th><th>Top 收益</th><th>相对基准</th><th>胜率</th></tr></thead><tbody><tr v-for="row in comparisonRows" :key="row.id" :class="{ active: currentJob?.id === row.id }" @click="selectJobById(row.id)"><td><strong>{{ row.strategy }}</strong><small>{{ row.start }} — {{ row.end }}{{ row.legacyOutcome ? ' · 旧收益口径' : '' }}</small></td><td><strong>{{ intervalLabel(row.interval) }} · Top {{ row.topN }}</strong><small>{{ row.slices }} 个截面</small></td><td><strong>{{ row.period }}</strong></td><td><strong :class="returnClass(row.screenMean)">{{ percent(row.screenMean) }}</strong></td><td><strong :class="returnClass(row.topMean)">{{ percent(row.topMean) }}</strong></td><td><strong :class="returnClass(row.excess)">{{ percent(row.excess) }}</strong></td><td><strong>{{ percent(row.winRate, false) }}</strong></td></tr></tbody></table></div>
        </div>

        <div class="screening-detail-table-head"><div><h3>完整统计</h3><p>均值用于比较收益水平，中位数和最好/最差值用于检查极端样本影响。</p></div></div>
        <div class="table-wrap" v-if="performanceRows.length"><table class="research-result-table screening-performance-table"><thead><tr><th>比较对象</th><th v-for="period in performancePeriods" :key="period">{{ period }}</th></tr></thead><tbody><tr v-for="row in performanceRows" :key="row.key"><td><strong>{{ row.label }}</strong><small>{{ row.desc }}</small></td><td v-for="period in performancePeriods" :key="period"><template v-if="row.stats[period]?.count"><strong :class="returnClass(row.stats[period].mean)">均值 {{ percent(row.stats[period].mean) }}</strong><small>中位数 {{ percent(row.stats[period].median) }} · 胜率 {{ percent(row.stats[period].win_rate, false) }}</small><small>最好 {{ percent(row.stats[period].best) }} · 最差 {{ percent(row.stats[period].worst) }}</small><small>{{ row.stats[period].count }} 样本</small></template><span v-else>—</span></td></tr></tbody></table></div>
        <div class="result-path">结构化结果：{{ currentJob.result.summary_path }}</div>
    </section>
    <section class="card research-progress-card failed" v-if="currentJobMatchesForm && currentJob.status === 'failed'"><h2>运行失败</h2><div class="error-msg">{{ currentJob.error || currentJob.message }}</div></section>
</div>`,
    data() { return { fields: [], strategies: [], status: {}, runForm: { screening_strategy_id: '', start_date: '2020-01-01', end_date: '', interval: '6m', top_n: 50 }, jobs: [], currentJob: null, formReady: false, pollTimer: null, error: '' }; },
    computed: {
        selectedStrategy() { return this.strategies.find(item => item.id === this.runForm.screening_strategy_id) || null; },
        currentStrategyIdentity() { return screeningDefinitionIdentity(this.selectedStrategy); },
        isRunning() { return !!this.currentJob && ['queued', 'running'].includes(this.currentJob.status); },
        formComplete() { return !!this.selectedStrategy && !!this.runForm.start_date && !!this.runForm.end_date; },
        canStart() { return this.formComplete && !this.isRunning; },
        runButtonLabel() { return this.isRunning ? '运行中…' : (this.currentResultUsesLegacyOutcome ? '按新口径重算' : (this.currentResultMatchesForm ? '重新运行当前方案' : '运行历史验证')); },
        jobProgress() { return this.currentJob?.progress || {}; },
        overallProgress() { return Math.max(0, Math.min(100, Math.round(Number(this.jobProgress.overall_percent || 0)))); },
        progressTotal() { return Number(this.jobProgress.total || 0); },
        progressCounter() {
            const current = Number(this.jobProgress.current || 0), total = this.progressTotal;
            const unit = this.jobProgress.phase === 'outcomes' ? '候选样本' : '历史截面';
            return `${unit} ${current.toLocaleString()} / ${total.toLocaleString()} · 阶段 ${Math.round(Number(this.jobProgress.percent || 0))}%`;
        },
        progressTitle() {
            return ({ queued: '等待开始', screening: '正在生成历史截面', loading: '正在整理筛选结果', outcomes: '正在采集前向收益', summarizing: '正在计算组合表现', reporting: '正在生成结果报告' })[this.jobProgress.phase] || '正在执行历史验证';
        },
        resultJobs() { return this.jobs.filter(job => job.status === 'completed' && job.result && job?.params?.screening_strategy_id === this.runForm.screening_strategy_id && screeningDefinitionIdentity(this.jobStrategySnapshot(job)) === this.currentStrategyIdentity); },
        currentJobMatchesForm() { return Boolean(this.currentJob) && this.jobSignature(this.currentJob) === this.formSignature(); },
        currentResultUsesLegacyOutcome() { return this.currentJobMatchesForm && this.currentJob.status === 'completed' && Boolean(this.currentJob.result) && Number(this.currentJob.result.outcome_schema_version || 1) < 3; },
        currentResultMatchesForm() { return this.currentJobMatchesForm && this.currentJob.status === 'completed' && Boolean(this.currentJob.result); },
        performanceRows() { const performance = this.currentJob?.result?.performance || {}; return ['market', 'screen_all', 'screen_top'].filter(key => performance[key]).map(key => ({ key, ...performance[key] })); },
        performancePeriods() { const periods = []; for (const row of this.performanceRows) for (const period of Object.keys(row.stats || {})) if (!periods.includes(period) && typeof row.stats[period] === 'object') periods.push(period); return periods; },
        focusPeriod() { return this.periodForInterval(this.currentJob?.params?.interval || this.runForm.interval, this.currentJob?.result?.performance || {}); },
        comparisonRows() {
            return this.resultJobs.map(job => {
                const performance = job.result?.performance || {};
                const period = this.periodForInterval(job.params?.interval, performance);
                const market = performance.market?.stats?.[period] || {};
                const screen = performance.screen_all?.stats?.[period] || {};
                const top = performance.screen_top?.stats?.[period] || {};
                const screenMean = Number(screen.mean), marketMean = Number(market.mean);
                return { id: job.id, strategy: this.jobStrategyName(job), start: job.params?.start_date, end: job.params?.end_date, interval: job.params?.interval, topN: job.params?.top_n, slices: job.result?.dates?.length || 0, period, legacyOutcome: Number(job.result?.outcome_schema_version || 1) < 3, screenMean: Number.isFinite(screenMean) ? screenMean : null, topMean: Number.isFinite(Number(top.mean)) ? Number(top.mean) : null, excess: Number.isFinite(screenMean) && Number.isFinite(marketMean) ? screenMean - marketMean : null, winRate: Number.isFinite(Number(screen.win_rate)) ? Number(screen.win_rate) : null };
            });
        },
        resultVersion() { const version = this.currentJob?.result?.version || ''; return String(version).includes('T') ? String(version).replace('T', ' ').slice(0, 16) : (version || '已冻结'); },
        returnChart() {
            if (!this.performanceRows.length || !this.performancePeriods.length) return null;
            const width = 760, height = 280, left = 56, right = 18, top = 18, bottom = 42;
            const values = this.performancePeriods.flatMap(period => this.performanceRows.map(row => Number(row.stats?.[period]?.mean)).filter(Number.isFinite));
            if (!values.length) return null;
            let min = Math.min(0, ...values), max = Math.max(0, ...values);
            const span = Math.max(max - min, 0.02); min -= span * 0.08; max += span * 0.08;
            const plotWidth = width - left - right, plotHeight = height - top - bottom;
            const y = value => top + ((max - value) / (max - min)) * plotHeight;
            const zeroY = y(0), groupWidth = plotWidth / this.performancePeriods.length;
            const barWidth = Math.min(30, Math.max(10, (groupWidth - 22) / this.performanceRows.length));
            const bars = [], labels = [];
            this.performancePeriods.forEach((period, periodIndex) => {
                const center = left + groupWidth * (periodIndex + 0.5);
                labels.push({ text: period, x: center });
                this.performanceRows.forEach((row, rowIndex) => {
                    const value = Number(row.stats?.[period]?.mean);
                    if (!Number.isFinite(value)) return;
                    const valueY = y(value);
                    bars.push({ key: `${period}-${row.key}`, label: row.label, period, value, color: this.chartColor(row.key), width: barWidth, x: center - (barWidth * this.performanceRows.length) / 2 + rowIndex * barWidth, y: Math.min(valueY, zeroY), height: Math.max(1, Math.abs(valueY - zeroY)) });
                });
            });
            const ticks = Array.from({ length: 5 }, (_, index) => { const value = max - ((max - min) * index) / 4; return { value, y: y(value) }; });
            return { width, height, left, right, zeroY, bars, labels, ticks };
        },
        equityCurve() {
            if (!this.focusPeriod || !this.currentResultMatchesForm) return null;
            const dates = this.currentJob.result?.dates || [];
            if (!dates.length) return null;
            const rawSeries = [];
            for (const row of this.performanceRows) {
                const byDate = Object.fromEntries((row.slices || []).map(item => [item.cutoff_date, item]));
                let cumulative = 1, observed = false;
                const values = [{ date: '起点', value: 1 }];
                for (const date of dates) {
                    const raw = byDate[date]?.returns?.[this.focusPeriod];
                    if (raw !== null && raw !== undefined && Number.isFinite(Number(raw))) {
                        cumulative *= 1 + Number(raw);
                        observed = true;
                    }
                    values.push({ date, value: cumulative });
                }
                if (observed) rawSeries.push({ key: row.key, label: row.label, color: this.chartColor(row.key), values, finalReturn: cumulative - 1 });
            }
            if (!rawSeries.length) return null;
            const width = 920, height = 330, left = 58, right = 20, top = 18, bottom = 42;
            const allValues = rawSeries.flatMap(series => series.values.map(item => item.value));
            let min = Math.min(1, ...allValues), max = Math.max(1, ...allValues);
            const span = Math.max(max - min, 0.04); min -= span * 0.08; max += span * 0.08;
            const plotWidth = width - left - right, plotHeight = height - top - bottom;
            const x = index => left + (index / dates.length) * plotWidth;
            const y = value => top + ((max - value) / (max - min)) * plotHeight;
            const series = rawSeries.map(item => {
                const dots = item.values.map((point, index) => ({ ...point, x: x(index), y: y(point.value) }));
                return { ...item, dots, points: dots.map(point => `${point.x},${point.y}`).join(' ') };
            });
            const labelIndexes = [...new Set([1, Math.max(1, Math.floor((dates.length + 1) / 2)), dates.length])];
            const labels = labelIndexes.map((index, order) => ({ text: dates[index - 1].slice(0, 7), x: x(index), anchor: order === 0 ? 'start' : (order === labelIndexes.length - 1 ? 'end' : 'middle') }));
            const ticks = Array.from({ length: 5 }, (_, index) => { const value = max - ((max - min) * index) / 4; return { value, y: y(value) }; });
            return { width, height, left, right, baseY: y(1), series, labels, ticks };
        },
        countChart() {
            const slices = this.currentJob?.result?.slices || [];
            if (!slices.length) return null;
            const width = 520, height = 190, left = 18, right = 18, top = 24, bottom = 30;
            const values = slices.map(item => Number(item.screen_count || 0));
            const min = Math.min(...values), max = Math.max(...values), spread = Math.max(max - min, 1);
            const x = index => slices.length === 1 ? width / 2 : left + (index / (slices.length - 1)) * (width - left - right);
            const y = value => top + ((max - value) / spread) * (height - top - bottom);
            const dots = slices.map((item, index) => ({ date: item.cutoff_date, value: values[index], x: x(index), y: y(values[index]) }));
            const points = dots.map(point => `${point.x},${point.y}`).join(' ');
            const area = `${left},${height - bottom} ${points} ${width - right},${height - bottom}`;
            const labelIndexes = [...new Set([0, Math.floor((slices.length - 1) / 2), slices.length - 1])];
            const labels = labelIndexes.map((index, order) => ({ text: slices[index].cutoff_date.slice(0, 7), x: x(index), anchor: order === 0 ? 'start' : (order === labelIndexes.length - 1 ? 'end' : 'middle') }));
            return { width, height, min, max, average: (values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(1), points, area, dots, labels };
        },
    },
    watch: {
        runForm: { deep: true, handler() { if (!this.formReady) return; rememberScreeningStrategy(this.runForm.screening_strategy_id); this.syncMatchingResult(); this.syncContext(); } },
        selectedStrategyId(value) {
            if (this.embedded && value !== this.runForm.screening_strategy_id) this.runForm.screening_strategy_id = value || '';
        },
    },
    methods: {
        async load() {
            try {
                [this.fields, this.strategies, this.jobs, this.status] = await Promise.all([apiFetch('/api/research/screening-fields'), apiFetch('/api/research/screening-strategies'), apiFetch('/api/research/jobs?kind=cross_section&limit=20'), apiFetch('/api/research/screening-status')]);
                this.runForm.screening_strategy_id = this.embedded ? (this.selectedStrategyId || '') : (preferredScreeningStrategy(this.strategies)?.id || '');
                if (!this.runForm.end_date) this.runForm.end_date = this.status.latest_date || new Date().toISOString().slice(0, 10);
                const active = this.jobs.find(job => ['queued', 'running'].includes(job.status));
                if (active) { this.applyJobToForm(active); this.startPolling(); }
                else { this.formReady = true; this.syncMatchingResult(); }
                this.syncContext();
            } catch (error) { this.error = error.message; }
        },
        async startRun() {
            this.error = '';
            try {
                this.currentJob = await apiFetch('/api/research/cross-section/start', { method: 'POST', body: JSON.stringify(this.runForm) });
                this.jobs = [this.currentJob, ...this.jobs.filter(job => job.id !== this.currentJob.id)];
                this.startPolling(); this.syncContext();
            } catch (error) { this.error = error.message; }
        },
        startPolling() { this.stopPolling(); this.pollTimer = setInterval(this.pollJob, 1500); this.pollJob(); },
        stopPolling() { if (this.pollTimer) clearInterval(this.pollTimer); this.pollTimer = null; },
        async pollJob() {
            if (!this.currentJob) return;
            try {
                const updated = await apiFetch(`/api/research/jobs/${this.currentJob.id}`); this.currentJob = updated;
                const index = this.jobs.findIndex(job => job.id === updated.id); if (index >= 0) this.jobs.splice(index, 1, updated);
                if (!['queued', 'running'].includes(updated.status)) this.stopPolling(); this.syncContext();
            } catch (error) { this.error = error.message; this.stopPolling(); }
        },
        formSignature() { return JSON.stringify({ strategy: this.runForm.screening_strategy_id || '', definition: this.currentStrategyIdentity, start: this.runForm.start_date || '', end: this.runForm.end_date || '', interval: this.runForm.interval || '', topN: Number(this.runForm.top_n || 0) }); },
        jobStrategySnapshot(job) { return job?.params?.screening_strategy_snapshot || job?.result?.screening_strategy_snapshot || null; },
        jobSignature(job) { return JSON.stringify({ strategy: job?.params?.screening_strategy_id || '', definition: screeningDefinitionIdentity(this.jobStrategySnapshot(job)), start: job?.params?.start_date || '', end: job?.params?.end_date || '', interval: job?.params?.interval || '', topN: Number(job?.params?.top_n || 0) }); },
        syncMatchingResult() { if (this.isRunning) return; const match = this.resultJobs.find(job => this.jobSignature(job) === this.formSignature()); this.currentJob = match || null; },
        applyJobToForm(job) {
            this.formReady = false;
            this.runForm = { screening_strategy_id: job.params?.screening_strategy_id || '', start_date: job.params?.start_date || '', end_date: job.params?.end_date || '', interval: job.params?.interval || '6m', top_n: Number(job.params?.top_n || 50) };
            this.currentJob = job;
            Vue.nextTick(() => { this.formReady = true; this.syncContext(); });
        },
        selectJobById(id) { const job = this.jobs.find(item => item.id === id); if (job) this.applyJobToForm(job); },
        syncContext() { screeningContext('截面回测', this.selectedStrategy, { current_run: this.currentJob, available_fields: this.fields.map(field => ({ id: field.id, name: field.name, description: field.description, preferred_direction: field.preferred_direction })) }); },
        jobStrategyName(job) { return job.params?.screening_strategy_name || job.result?.screening_strategy_name || job.params?.strategy || '历史回测'; },
        resultOptionLabel(job) { return `${this.jobStrategyName(job)} · ${job.params?.start_date || ''}~${job.params?.end_date || ''} · ${this.intervalLabel(job.params?.interval)} · Top ${job.params?.top_n || '—'}`; },
        async handleResourceUpdated(event) {
            if (!String(event.detail?.action?.path || '').startsWith('/api/research/screening-strategies')) return;
            try {
                this.strategies = await apiFetch('/api/research/screening-strategies');
                this.syncMatchingResult();
                this.syncContext();
            } catch (error) { this.error = error.message; }
        },
        intervalLabel(value) { return ({ '1m': '每月', '3m': '每季度', '6m': '每半年', '1y': '每年' })[value] || value || '—'; },
        periodForInterval(value, performance = {}) { const expected = ({ '1m': '1个月', '3m': '3个月', '6m': '6个月', '1y': '12个月' })[value]; const stats = performance.screen_all?.stats || {}; if (expected && stats[expected]) return expected; return Object.keys(stats).find(key => typeof stats[key] === 'object') || expected || ''; },
        stageLabel(stage) { return ({ queued: '等待执行', screening: '历史筛选', evaluation: '收益评估' })[stage] || '执行中'; },
        progressStepClass(step) {
            const stage = this.currentJob?.stage || 'queued';
            if (step === 'screening') return { active: stage === 'screening', complete: stage === 'evaluation' || stage === 'completed' };
            return { active: stage === 'evaluation', complete: stage === 'completed' };
        },
        formatDuration(seconds) {
            const value = Math.max(0, Number(seconds || 0));
            if (value >= 3600) return `${Math.floor(value / 3600)}小时${Math.ceil((value % 3600) / 60)}分`;
            if (value >= 60) return `${Math.ceil(value / 60)}分钟`;
            return `${Math.ceil(value)}秒`;
        },
        shortTime(value) { return value ? value.replace('T', ' ').slice(5, 16) : ''; },
        percent(value, signed = true) { if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'; const number = Number(value) * 100; return `${signed && number > 0 ? '+' : ''}${number.toFixed(1)}%`; },
        returnClass(value) { return Number(value) > 0 ? 'return-positive' : (Number(value) < 0 ? 'return-negative' : ''); },
        chartColor(key) { return ({ market: '#94a3b8', screen_all: '#3182ce', screen_top: '#805ad5' })[key] || '#4a5568'; },
        periodStat(row) { return row?.stats?.[this.focusPeriod] || null; },
        excessReturn(row) { const value = Number(this.periodStat(row)?.mean); const market = Number(this.periodStat(this.performanceRows.find(item => item.key === 'market'))?.mean); return Number.isFinite(value) && Number.isFinite(market) ? value - market : null; },
    },
    mounted() {
        this._resourceUpdatedHandler = event => this.handleResourceUpdated(event);
        window.addEventListener('app-resource-updated', this._resourceUpdatedHandler);
        this.load();
    },
    beforeUnmount() {
        this.stopPolling();
        if (this._resourceUpdatedHandler) window.removeEventListener('app-resource-updated', this._resourceUpdatedHandler);
    },
};

const ScreeningWorkbenchPage = {
    template: `
<div class="page screening-page screening-unified-workbench">
    <workspace-page-header eyebrow="截面筛选 · 规则构建" title="策略构建" description="组合条件并即时预览，确认有效后保存为可复用的数值策略。">
        <template #meta><span class="page-header-chip" v-if="status.latest_date"><span>本地数据</span>{{ status.latest_date }}</span></template>
    </workspace-page-header>

    <div class="screening-studio">
        <aside class="card screening-factor-pool">
            <div class="screening-factor-head"><h2>指标库</h2><span>{{ fields.length }}</span></div>
            <input class="screening-factor-search" v-model.trim="fieldSearch" placeholder="搜索指标" />
            <div class="screening-factor-job" v-if="fieldJobNotice" :class="fieldJobNotice.status">
                <strong>{{ fieldJobNotice.title }}</strong>
                <span>{{ fieldJobNotice.message }}</span>
                <i v-if="['queued', 'running'].includes(fieldJobNotice.status)"><b :style="{ width: (fieldJobNotice.percent || 0) + '%' }"></b></i>
            </div>
            <div class="screening-factor-groups">
                <section v-for="group in filteredFieldGroups" :key="group.name" class="screening-factor-group">
                    <button class="screening-factor-group-title" @click="toggleGroup(group.name)"><span>{{ group.name }}</span><em>{{ group.items.length }}</em><b>{{ collapsedGroups[group.name] ? '＋' : '－' }}</b></button>
                    <div v-if="!collapsedGroups[group.name]">
                        <div class="screening-factor-item" v-for="field in group.items" :key="field.id">
                            <span><strong>{{ field.name }}</strong><small>{{ field.description }}</small><em :class="{ ready: field.capabilities?.current_screen, unsupported: field.provider_compatibility !== 'exact' }">{{ fieldStatusLabel(field) }}</em></span>
                            <div v-if="field.capabilities?.current_screen"><button @click="addFilter(field)">条件</button><button @click="addRanking(field)" :disabled="rankingFields.has(field.id)">排名</button></div>
                            <div v-else-if="canPrepareField(field)"><button class="screening-factor-prepare" @click="prepareField(field)" :disabled="!!preparingFieldId">{{ preparingFieldId === field.id ? '补齐中…' : '补齐数据' }}</button></div>
                            <div v-else><button disabled>当前源不可用</button></div>
                        </div>
                    </div>
                </section>
                <div class="screening-empty" v-if="!filteredFieldGroups.length">没有匹配的指标</div>
            </div>
        </aside>

        <main class="screening-studio-main">
            <section class="card screening-draft-card">
                <div class="screening-draft-toolbar">
                    <div class="screening-draft-identity">
                        <span>当前规则</span>
                        <strong>{{ source.name || '未命名草稿' }}</strong>
                        <em class="dirty" v-if="dirty">有未保存修改</em><em class="saved" v-else-if="source.id">已保存</em>
                    </div>
                    <div class="screening-preset-actions">
                        <select :value="source.id || ''" @change="requestLoadStrategy($event)"><option value="" disabled>{{ source.id ? '载入其他策略…' : '载入策略…' }}</option><option v-for="strategy in strategies" :key="strategy.id" :value="strategy.id">{{ strategy.name }}</option></select>
                        <button class="btn btn-small" @click="newDraft">清空</button>
                        <button class="btn btn-small btn-danger" v-if="source.id" @click="deleteStrategy" :disabled="deleting">{{ deleting ? '删除中…' : '删除策略' }}</button>
                        <button class="btn btn-small btn-primary" @click="openSaveDialog">保存规则</button>
                    </div>
                </div>

                <div class="screening-strategy-description-editor">
                    <label for="screening-strategy-description">
                        <span>策略说明</span>
                        <small>记录适用范围、研究假设或注意事项</small>
                    </label>
                    <textarea id="screening-strategy-description" v-model="source.description" rows="2" maxlength="500" placeholder="补充这套策略的适用范围、研究假设或注意事项"></textarea>
                </div>

                <div class="screening-run-strip">
                    <label><span>预览日期</span><input type="date" v-model="asOfDate" /></label>
                    <label><span>预览数量</span><input type="number" v-model.number="topN" min="1" max="200" /></label>
                    <label class="screening-inline-check"><input type="checkbox" v-model="draft.exclude_st" /><span>排除 ST 与退市</span></label>
                    <label><span>单行业最多</span><input type="number" v-model.number="draft.industry_cap" min="0" placeholder="不限" /></label>
                    <button class="btn btn-primary screening-run-button" @click="runScreen" :disabled="running || !asOfDate">{{ running ? '计算中…' : '刷新预览' }}</button>
                    <small v-if="status.latest_date">本地数据至 {{ status.latest_date }}</small>
                </div>

                <div class="screening-section">
                    <div class="screening-section-head"><div><h3>过滤条件</h3><p>所有启用条件同时满足后，股票才进入排名。</p></div><button class="btn btn-small" @click="addFilter()">添加条件</button></div>
                    <div class="screening-rule" v-for="(rule, index) in draft.filters" :key="index">
                        <input type="checkbox" v-model="rule.enabled" title="启用" />
                        <div class="rule-field-control"><select v-model="rule.field"><optgroup v-for="group in fieldGroups" :key="group.name" :label="group.name"><option v-for="field in group.items" :key="field.id" :value="field.id">{{ field.name }}</option></optgroup></select><small>{{ filterFieldHint(rule) }}</small></div>
                        <select v-model="rule.mode"><option value="value">数值区间</option><option value="percentile">截面分位</option></select>
                        <template v-if="rule.mode === 'value'"><input type="number" v-model.number="rule.min" placeholder="最小值" /><span>至</span><input type="number" v-model.number="rule.max" placeholder="最大值" /></template>
                        <template v-else><input type="number" v-model.number="rule.percentile_min" min="0" max="100" placeholder="最低分位" /><span>% 至</span><input type="number" v-model.number="rule.percentile_max" min="0" max="100" placeholder="最高分位" /></template>
                        <button class="rule-remove" @click="removeFilter(index)" title="删除条件">×</button>
                    </div>
                    <div class="screening-empty" v-if="!draft.filters.length">从左侧指标库添加条件，或直接运行无条件排名。</div>
                </div>

                <div class="screening-section">
                    <div class="screening-section-head"><div><h3>加权排名</h3><p>指标先转为截面分位，权重由引擎按合计值归一。</p></div><div class="screening-ranking-tools"><span class="weight-total" :class="{ warning: Math.abs(rankingWeightTotal - 1) > 0.0001 }">权重合计 {{ rankingWeightTotal.toFixed(2) }}</span><button class="btn btn-small" @click="addRanking()">添加指标</button></div></div>
                    <div class="ranking-rule" v-for="(node, index) in draft.ranking" :key="index">
                        <span class="ranking-index">R{{ index + 1 }}</span>
                        <select v-model="node.field"><optgroup v-for="group in fieldGroups" :key="group.name" :label="group.name"><option v-for="field in group.items" :key="field.id" :value="field.id">{{ field.name }}</option></optgroup></select>
                        <select v-model="node.direction"><option value="desc">越高越好</option><option value="asc">越低越好</option></select>
                        <label>权重 <input type="number" v-model.number="node.weight" min="0.01" step="0.1" /></label>
                        <select v-model="node.na_handling"><option value="neutral">缺失记中性</option><option value="worst">缺失记最差</option></select>
                        <button class="rule-remove" @click="removeRanking(index)" title="删除指标">×</button>
                    </div>
                    <div class="screening-empty" v-if="!draft.ranking.length">尚未设置排名指标，结果将保留原始顺序。</div>
                </div>
            </section>

            <section class="card screening-preview-card screening-live-result">
                <div class="section-title-row"><div><h2>规则预览</h2><p v-if="result">请求 {{ result.requested_date }}，实际使用 {{ result.effective_date || result.requested_date }}</p><p v-else>规则或日期变化后自动预估，也可点击“刷新预览”立即计算。</p></div><span class="screening-live-state" :class="{ active: previewing || running }">{{ previewing || running ? '正在计算' : (result ? '已同步当前规则' : '等待数据') }}</span></div>
                <div class="screening-funnel" v-if="result"><div><span>原始股票池</span><strong>{{ result.funnel.universe }}</strong></div><i>→</i><div><span>条件命中</span><strong>{{ result.funnel.after_filters }}</strong></div><i>→</i><div><span>最终入选</span><strong>{{ result.funnel.selected }}</strong></div></div>
                <div class="table-wrap screening-preview-scroll" v-if="result?.stocks?.length" tabindex="0" aria-label="规则预览结果，可左右滚动"><table class="research-result-table preview-result-table"><thead><tr><th>代码</th><th>名称</th><th>行业</th><th v-for="column in resultColumns" :key="column">{{ columnName(column) }}</th></tr></thead><tbody><tr v-for="stock in result.stocks" :key="stock.ts_code"><td>{{ stock.ts_code }}</td><td>{{ stock.stock_name || '—' }}</td><td>{{ stock.industry || '—' }}</td><td v-for="column in resultColumns" :key="column">{{ formatNumber(stock[column]) }}</td></tr></tbody></table></div>
                <div class="screening-empty" v-else-if="result && !previewing">当前规则没有命中股票。</div>
                <div class="screening-empty" v-else-if="!result && !previewing">设置条件后将在这里直接看到命中结果。</div>
                <div class="error-msg" v-if="error">{{ error }}</div>
            </section>
        </main>
    </div>

    <div class="screening-modal-layer" v-if="saveDialog.open" @click.self="closeSaveDialog">
        <section class="card screening-save-dialog">
            <div class="section-title-row"><div><h2>保存筛选规则</h2><p>保存后可重复载入，也可用于历史验证。</p></div><button class="agent-icon-button" @click="closeSaveDialog">×</button></div>
            <div class="setting-item"><label>策略名称</label><input v-model.trim="saveDialog.name" maxlength="80" autofocus /></div>
            <div class="research-actions">
                <button class="btn btn-primary" v-if="source.id" @click="updateStrategy" :disabled="saveDialog.saving || !saveDialog.name">{{ saveDialog.saving ? '保存中…' : '保存修改' }}</button>
                <button class="btn btn-primary" v-else @click="saveAsStrategy" :disabled="saveDialog.saving || !saveDialog.name">{{ saveDialog.saving ? '保存中…' : '另存为策略' }}</button>
                <button class="btn" v-if="source.id" @click="saveAsStrategy" :disabled="saveDialog.saving || !saveDialog.name">另存为新策略</button>
                <button class="btn" @click="closeSaveDialog">取消</button>
            </div>
            <div class="error-msg" v-if="saveDialog.error">{{ saveDialog.error }}</div>
        </section>
    </div>
</div>`,
    data() {
        return {
            fields: [],
            strategies: [],
            status: {},
            source: { id: null, name: '', description: '' },
            draft: { exclude_st: true, industry_cap: 0, filters: [], ranking: [] },
            dirty: false,
            baseline: '',
            baselineDescription: '',
            draftReady: false,
            fieldSearch: '',
            collapsedGroups: {},
            asOfDate: '',
            topN: 30,
            result: null,
            previewing: false,
            running: false,
            deleting: false,
            previewTimer: null,
            previewSequence: 0,
            error: '',
            saveDialog: { open: false, name: '', saving: false, error: '' },
            preparingFieldId: '',
            fieldJobNotice: null,
            fieldJobTimer: null,
        };
    },
    computed: {
        fieldGroups() {
            const groups = {};
            for (const field of this.fields) (groups[field.group] ||= []).push(field);
            return Object.entries(groups).map(([name, items]) => ({ name, items }));
        },
        filteredFieldGroups() {
            const query = this.fieldSearch.toLowerCase();
            if (!query) return this.fieldGroups;
            return this.fieldGroups.map(group => ({ ...group, items: group.items.filter(field => `${field.name} ${field.id} ${field.description || ''}`.toLowerCase().includes(query)) })).filter(group => group.items.length);
        },
        fieldById() { return Object.fromEntries(this.fields.map(field => [field.id, field])); },
        rankingFields() { return new Set(this.draft.ranking.map(node => node.field)); },
        rankingWeightTotal() { return this.draft.ranking.reduce((total, node) => total + Number(node.weight || 0), 0); },
        resultColumns() {
            if (!this.result?.stocks?.length) return [];
            const preferred = ['tier_score', ...this.draft.filters.map(rule => rule.field), ...this.draft.ranking.map(node => node.field)];
            return [...new Set(preferred)].filter(column => column && Object.prototype.hasOwnProperty.call(this.result.stocks[0], column));
        },
    },
    watch: {
        draft: { deep: true, handler() { if (!this.draftReady) return; this.refreshDirtyState(); this.persistDraft(); this.schedulePreview(); this.syncContext(); } },
        'source.description'() { if (!this.draftReady) return; this.refreshDirtyState(); this.persistDraft(); this.syncContext(); },
        asOfDate() { if (this.draftReady) { this.persistDraft(); this.schedulePreview(); } },
        topN() { if (this.draftReady) { this.persistDraft(); this.schedulePreview(); } },
    },
    methods: {
        emptyDefinition() { return { exclude_st: true, industry_cap: 0, filters: [], ranking: [] }; },
        normalizedDefinition(value = {}) { return { exclude_st: value.exclude_st !== false, industry_cap: Number(value.industry_cap || 0), filters: cloneScreening(value.filters || []), ranking: cloneScreening(value.ranking || []) }; },
        serializeDefinition() { return JSON.stringify(this.normalizedDefinition(this.draft)); },
        refreshDirtyState() { this.dirty = this.serializeDefinition() !== this.baseline || String(this.source.description || '') !== this.baselineDescription; },
        async load() {
            try {
                [this.fields, this.strategies, this.status] = await Promise.all([apiFetch('/api/research/screening-fields'), apiFetch('/api/research/screening-strategies'), apiFetch('/api/research/screening-status')]);
                const stored = this.readStoredDraft();
                this.asOfDate = stored?.asOfDate || this.status.latest_date || new Date().toISOString().slice(0, 10);
                this.topN = Number(stored?.topN || 30);
                if (stored?.dirty && stored.definition) this.applyDraft(stored.source || {}, stored.definition, true);
                else {
                    const selected = preferredScreeningStrategy(this.strategies);
                    if (selected) this.applyStrategy(selected);
                    else this.applyDraft({}, this.emptyDefinition(), true);
                }
            } catch (error) { this.error = error.message; }
        },
        readStoredDraft() { try { return JSON.parse(localStorage.getItem(SCREENING_DRAFT_KEY) || 'null'); } catch (_) { return null; } },
        persistDraft() { localStorage.setItem(SCREENING_DRAFT_KEY, JSON.stringify({ source: this.source, definition: this.normalizedDefinition(this.draft), dirty: this.dirty, asOfDate: this.asOfDate, topN: this.topN })); },
        applyDraft(source, definition, dirty = false) {
            this.draftReady = false;
            this.source = { id: source.id || null, name: source.name || '', description: source.description || '' };
            this.draft = this.normalizedDefinition(definition);
            this.baseline = dirty ? '' : this.serializeDefinition();
            this.baselineDescription = dirty ? '' : this.source.description;
            this.dirty = dirty;
            this.result = null;
            this.draftReady = true;
            this.persistDraft();
            this.schedulePreview();
            this.syncContext();
        },
        applyStrategy(strategy) { this.applyDraft(strategy, strategy.definition, false); rememberScreeningStrategy(strategy.id); },
        requestLoadStrategy(event) {
            const id = event.target.value;
            event.target.value = this.source.id || '';
            if (!id || id === this.source.id) return;
            if (this.dirty && !confirm('载入策略会替换当前未保存规则，继续吗？')) return;
            const strategy = this.strategies.find(item => item.id === id);
            if (strategy) this.applyStrategy(strategy);
        },
        newDraft() { if (this.dirty && !confirm('清空会丢弃当前未保存规则，继续吗？')) return; this.applyDraft({}, this.emptyDefinition(), true); },
        toggleGroup(name) { this.collapsedGroups = { ...this.collapsedGroups, [name]: !this.collapsedGroups[name] }; },
        addFilter(field = null) { const selected = field || this.fields.find(item => item.capabilities?.current_screen && !this.draft.filters.some(rule => rule.field === item.id)); if (selected?.capabilities?.current_screen) this.draft.filters.push({ field: selected.id, enabled: true, mode: 'value', min: '', max: '' }); },
        removeFilter(index) { this.draft.filters.splice(index, 1); },
        addRanking(field = null) { const selected = field || this.fields.find(item => item.capabilities?.current_screen && !this.rankingFields.has(item.id)); if (selected?.capabilities?.current_screen && !this.rankingFields.has(selected.id)) this.draft.ranking.push({ field: selected.id, weight: 1, direction: selected.preferred_direction || 'desc', na_handling: 'neutral' }); },
        removeRanking(index) { this.draft.ranking.splice(index, 1); },
        fieldStatusLabel(field) {
            if (field.capabilities?.current_screen) return '当前可执行';
            if (field.provider_compatibility !== 'exact') return field.provider_note || '当前数据源不支持';
            return field.materialization_blockers?.[0] || '等待历史物化';
        },
        canPrepareField(field) { return !!field.editable && field.provider_compatibility === 'exact' && !!field.materialization_blockers?.length; },
        async reloadFields() { this.fields = await apiFetch('/api/research/screening-fields'); },
        async prepareField(field) {
            if (!this.canPrepareField(field) || this.preparingFieldId) return;
            clearTimeout(this.fieldJobTimer); this.preparingFieldId = field.id; this.error = '';
            try {
                const job = await apiFetch(`/api/factors/${encodeURIComponent(field.id)}/prepare`, { method: 'POST' });
                this.pollFieldJob(job, field.id);
            } catch (error) {
                this.preparingFieldId = '';
                this.fieldJobNotice = { status: 'failed', title: '无法补齐指标', message: error.message, percent: 0 };
            }
        },
        pollFieldJob(job, fieldId) {
            this.fieldJobNotice = { status: job.status, title: '正在补齐指标数据', message: job.error || job.message || '等待执行', percent: Number(job.percent || 0) };
            if (['failed', 'cancelled', 'interrupted'].includes(job.status)) { this.preparingFieldId = ''; this.fieldJobNotice.title = '指标数据补齐失败'; return; }
            if (job.status === 'completed') { this.fieldJobNotice = { status: 'running', title: '依赖已就绪', message: '正在自动续接因子计算…', percent: 100 }; this.waitForFieldReady(fieldId); return; }
            this.fieldJobTimer = setTimeout(async () => {
                try { this.pollFieldJob(await apiFetch(`/api/datasources/jobs/${job.id}`), fieldId); }
                catch (error) { this.preparingFieldId = ''; this.fieldJobNotice = { status: 'failed', title: '任务状态读取失败', message: error.message, percent: 0 }; }
            }, 1200);
        },
        async waitForFieldReady(fieldId) {
            try {
                await this.reloadFields();
                const field = this.fields.find(item => item.id === fieldId);
                if (field?.capabilities?.current_screen) { this.preparingFieldId = ''; this.fieldJobNotice = { status: 'completed', title: '指标已可用', message: '现在可以直接加入条件或排名。', percent: 100 }; return; }
                if (field?.materialization?.status === 'failed') { this.preparingFieldId = ''; this.fieldJobNotice = { status: 'failed', title: '因子计算失败', message: field.materialization.error || field.materialization_blockers?.join('；') || '请查看数据任务。', percent: 0 }; return; }
                this.fieldJobTimer = setTimeout(() => this.waitForFieldReady(fieldId), 1200);
            } catch (error) { this.preparingFieldId = ''; this.fieldJobNotice = { status: 'failed', title: '指标状态读取失败', message: error.message, percent: 0 }; }
        },
        fieldUnit(id) { return ({ total_mv: '万元', circ_mv: '万元', market_cap_yi: '亿元', circ_mv_yi: '亿元', dv: '%', turnover_rate: '%', pe_ttm: '倍', pb: '倍', ps_ttm: '倍', pcf_ncf_ttm: '倍' })[id] || ''; },
        filterFieldHint(rule) { const unit = this.fieldUnit(rule.field); if (['total_mv', 'circ_mv'].includes(rule.field) && rule.mode === 'value') { const values = [rule.min, rule.max].filter(value => value !== '' && value !== null && value !== undefined && Number.isFinite(Number(value))); if (values.length) return `单位：万元 · ${values.map(value => `${Number(value) / 10000}亿元`).join(' 至 ')}`; } return unit ? `单位：${unit}` : (this.fieldById[rule.field]?.description || ''); },
        schedulePreview() { clearTimeout(this.previewTimer); if (!this.asOfDate) return; this.previewTimer = setTimeout(() => this.fetchPreview(false), 700); },
        async fetchPreview(manual) {
            if (!this.asOfDate) return;
            const sequence = ++this.previewSequence;
            if (manual) this.running = true; else this.previewing = true;
            this.error = '';
            try {
                const result = await apiFetch('/api/research/screening-preview', { method: 'POST', body: JSON.stringify({ definition: this.normalizedDefinition(this.draft), as_of_date: this.asOfDate, top_n: Number(this.topN || 30) }) });
                if (sequence === this.previewSequence) this.result = result;
            } catch (error) { if (sequence === this.previewSequence) this.error = error.message; }
            finally { if (sequence === this.previewSequence) { this.previewing = false; this.running = false; this.syncContext(); } }
        },
        runScreen() { clearTimeout(this.previewTimer); return this.fetchPreview(true); },
        openSaveDialog() { this.saveDialog = { open: true, name: this.source.name || '我的筛选策略', saving: false, error: '' }; },
        closeSaveDialog() { if (!this.saveDialog.saving) this.saveDialog.open = false; },
        async saveStrategy(method, id = '') {
            this.saveDialog.saving = true; this.saveDialog.error = '';
            try {
                const saved = await apiFetch(id ? `/api/research/screening-strategies/${id}` : '/api/research/screening-strategies', { method, body: JSON.stringify({ name: this.saveDialog.name, description: this.source.description || '', definition: this.normalizedDefinition(this.draft) }) });
                const index = this.strategies.findIndex(item => item.id === saved.id);
                if (index >= 0) this.strategies.splice(index, 1, saved); else this.strategies.push(saved);
                this.applyStrategy(saved); this.saveDialog.open = false;
            } catch (error) { this.saveDialog.error = error.message; }
            finally { this.saveDialog.saving = false; }
        },
        saveAsStrategy() { return this.saveStrategy('POST'); },
        updateStrategy() { return this.saveStrategy('PUT', this.source.id); },
        async deleteStrategy() {
            if (!this.source.id || this.deleting) return;
            const strategyId = this.source.id;
            const strategyName = this.source.name || '未命名策略';
            const dirtyWarning = this.dirty ? '\n当前未保存修改也会一并丢弃。' : '';
            if (!confirm(`确定删除策略“${strategyName}”？历史验证快照会保留，但策略本身无法恢复。${dirtyWarning}`)) return;
            this.deleting = true; this.error = '';
            try {
                await apiFetch(`/api/research/screening-strategies/${strategyId}`, { method: 'DELETE' });
                this.strategies = this.strategies.filter(item => item.id !== strategyId);
                if (localStorage.getItem(SCREENING_STRATEGY_KEY) === strategyId) localStorage.removeItem(SCREENING_STRATEGY_KEY);
                this.applyDraft({}, this.emptyDefinition(), true);
            } catch (error) { this.error = error.message; }
            finally { this.deleting = false; }
        },
        async handleResourceUpdated(event) {
            if (!String(event.detail?.action?.path || '').startsWith('/api/research/screening-strategies')) return;
            try {
                this.strategies = await apiFetch('/api/research/screening-strategies');
                const id = event.detail?.result?.id;
                const strategy = this.strategies.find(item => item.id === id);
                if (strategy) this.applyStrategy(strategy);
            } catch (error) { this.error = error.message; }
        },
        syncContext() { screeningContext('策略构建', { id: this.source.id, name: this.source.name || '未保存草稿', description: this.source.description, definition: this.normalizedDefinition(this.draft) }, { draft_dirty: this.dirty, screening_result: this.result, available_fields: this.fields.map(field => ({ id: field.id, name: field.name, description: field.description, preferred_direction: field.preferred_direction })) }); },
        columnName(id) { return id === 'tier_score' ? '综合分' : (this.fieldById[id]?.name || id); },
        formatNumber(value) { if (value === null || value === undefined || value === '') return '—'; return typeof value === 'number' ? Number(value.toFixed(4)) : value; },
    },
    mounted() {
        this._resourceUpdatedHandler = event => this.handleResourceUpdated(event);
        window.addEventListener('app-resource-updated', this._resourceUpdatedHandler);
        this.load();
    },
    beforeUnmount() {
        window.removeEventListener('app-resource-updated', this._resourceUpdatedHandler);
        clearTimeout(this.previewTimer);
        clearTimeout(this.fieldJobTimer);
        this.previewSequence += 1;
    },
};
