/** Structured-research batch judgement and framework validation pages. */

function qualitativePreferred(items, key, preferredId = '') {
    const saved = localStorage.getItem(key);
    return items.find(item => item.id === saved)
        || items.find(item => item.id === preferredId)
        || items[0]
        || null;
}

function qualitativePercent(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
    const number = Number(value) * 100;
    return `${number > 0 ? '+' : ''}${number.toFixed(1)}%`;
}

function qualitativeJobContext(path, form, preflight, job) {
    if (!window.setAppContext) return;
    window.setAppContext({
        workspace: 'qualitative',
        research_path: path,
        run_parameters: { ...form },
        preflight,
        current_run: job,
    });
}

const QualitativeRunPreview = {
    props: {
        preflight: { type: Object, default: null },
        candidatePreview: { type: Object, default: null },
        previewing: { type: Boolean, default: false },
        previewError: { type: String, default: '' },
        mode: { type: String, default: 'latest' },
        topN: { type: Number, default: 10 },
    },
    emits: ['refresh'],
    template: `
<section class="qualitative-work-preview" v-if="preflight">
    <div class="qualitative-preview-head">
        <div><div class="workspace-eyebrow">零 LLM 调用 · 不产生分析费用</div><h3>运行前预览</h3><p>先确认 Agent 会分析谁、经过哪些章节，以及本次运行最终交付什么。</p></div>
        <button class="btn btn-secondary btn-small" @click="$emit('refresh')" :disabled="previewing">{{ previewing ? '计算候选中…' : '刷新候选预览' }}</button>
    </div>

    <div class="qualitative-scope-grid">
        <article>
            <span class="qualitative-scope-index">01</span><div><small>分析对象</small><strong>{{ preflight.screening_strategy.name }}</strong><p>{{ objectScope }}</p></div>
        </article>
        <article>
            <span class="qualitative-scope-index">02</span><div><small>Agent 工作范围</small><strong>{{ preflight.framework.chapter_count }} 章 · {{ preflight.framework.operator_count }} 个算子 · {{ preflight.framework.operators_dir }}</strong><p>严格按章节依赖执行，不允许自由扩展分析路径。</p></div>
        </article>
        <article>
            <span class="qualitative-scope-index">03</span><div><small>交付结果</small><strong>{{ mode === 'validation' ? '框架增量检验' : '逐股结构化研判' }}</strong><p>{{ deliveryScope }}</p></div>
        </article>
    </div>

    <div class="qualitative-rule-summary">
        <div><strong>候选规则</strong><span v-if="definition.exclude_st">排除 ST/退市</span><span v-if="definition.industry_cap">单行业最多 {{ definition.industry_cap }} 只</span><span v-for="rule in enabledFilters" :key="'f-' + rule.field">{{ filterText(rule) }}</span><span v-if="!enabledFilters.length">无数值过滤条件</span></div>
        <div><strong>排序规则</strong><span v-for="rule in definition.ranking" :key="'r-' + rule.field">{{ fieldName(rule.field) }} {{ rule.direction === 'asc' ? '升序' : '降序' }} · 权重 {{ rule.weight }}</span><span v-if="!definition.ranking.length">无排名因子</span></div>
    </div>

    <div class="qualitative-dag-preview">
        <div class="qualitative-preview-subhead"><strong>章节 DAG</strong><span>每个候选对象都完整执行以下固定管线</span></div>
        <div class="qualitative-dag-flow">
            <article v-for="(chapter, index) in preflight.framework.chapters" :key="chapter.id">
                <div><span>{{ String(index + 1).padStart(2, '0') }}</span><strong>{{ chapter.title }}</strong></div>
                <p v-if="chapter.dependencies?.length">依赖：{{ chapter.dependencies.map(chapterName).join('、') }}</p><p v-else>起始章节</p>
                <div class="qualitative-operator-list"><span v-for="operator in chapter.operators" :key="operator" :class="{ gate: operatorMeta(operator).gate, missing: operatorMeta(operator).missing }">{{ operatorMeta(operator).name }}<em v-if="operatorMeta(operator).gate">门控</em></span></div>
            </article>
        </div>
        <div class="qualitative-adaptation-note" v-if="mode === 'validation' && historyAdaptations.length"><strong>时间边界</strong><p>验证时，{{ historyAdaptations.map(item => item.source_name).join('、') }}只使用各截面当时可见的数据；研究问题和章节结构保持不变。</p></div>
        <div class="qualitative-rule-summary qualitative-output-contract"><div><strong>综合输出</strong><span>综合评分</span><span>最终建议</span><span>核心逻辑</span><span>关键风险</span><span>信心水平</span><span v-for="item in preflight.framework.synthesis_fields || []" :key="item.field">{{ item.field }} · {{ item.type }}</span></div></div>
    </div>

    <div class="qualitative-candidate-preview">
        <div class="qualitative-preview-subhead"><strong>{{ mode === 'validation' ? '代表截面候选' : '本次候选对象' }}</strong><span v-if="candidatePreview">请求 {{ candidatePreview.requested_date }} · 实际截面 {{ candidatePreview.effective_date }} · 全市场 {{ candidatePreview.funnel.universe }} → 过滤后 {{ candidatePreview.funnel.after_filters }} → Agent {{ candidatePreview.funnel.selected }}</span><span v-else-if="previewing">正在执行纯数值筛选…</span><span v-else>等待本地候选预览</span></div>
        <div class="qualitative-preview-error" v-if="previewError">候选预览失败：{{ previewError }}</div>
        <div class="qualitative-candidate-list" v-if="previewStocks.length"><span v-for="stock in previewStocks" :key="stock.ts_code"><strong>{{ stock.stock_name || stock.ts_code }}</strong><small>{{ stock.ts_code }} · {{ stock.industry || '行业未知' }}</small></span></div>
        <p class="qualitative-preview-note" v-if="mode === 'validation'">这里只抽取一个代表截面检查候选质量；正式验证会在 {{ preflight.estimated.slices }} 个截面分别重新筛选并执行完整 DAG。</p>
    </div>
</section>`,
    computed: {
        definition() { return this.preflight?.screening_strategy?.definition || { exclude_st: false, industry_cap: 0, filters: [], ranking: [] }; },
        enabledFilters() { return (this.definition.filters || []).filter(rule => rule.enabled !== false); },
        previewStocks() { return (this.candidatePreview?.stocks || []).slice(0, 12); },
        objectScope() { return this.mode === 'validation' ? `${this.preflight.estimated.slices} 个历史截面 × 每期 Top ${this.topN}，预计 ${this.preflight.estimated.analyses} 次分析。` : `本地最新截面筛选 Top ${this.topN}，每只股票独立运行同一框架。`; },
        deliveryScope() { return this.mode === 'validation' ? '比较市场、筛选池与框架判断的多周期前瞻收益。' : '输出评分、建议、信心、核心逻辑、关键风险、Markdown 正文和算子证据链。'; },
        chapterTitles() { return Object.fromEntries((this.preflight?.framework?.chapters || []).map(item => [item.id, item.title])); },
        historyAdaptations() { return this.preflight?.framework?.history_adaptations || []; },
    },
    methods: {
        fieldName(id) { return ({ pe_ttm: '市盈率 PE', pb: '市净率 PB', total_mv: '总市值', circ_mv: '流通市值', dv: '股息率', roe_avg_3y: '近三年平均 ROE', ep: '盈利收益率', bp: '账面市值比' })[id] || id; },
        valueText(field, value) { if (value === undefined || value === null || value === '') return ''; if (['total_mv','circ_mv'].includes(field)) return `${Number(value) / 10000}亿元`; if (field === 'dv') return `${value}%`; return String(value); },
        filterText(rule) { if (rule.mode === 'percentile') return `${this.fieldName(rule.field)} 分位 ${rule.percentile_min ?? 0}%–${rule.percentile_max ?? 100}%`; const bounds = []; if (rule.min !== undefined) bounds.push(`≥ ${this.valueText(rule.field, rule.min)}`); if (rule.max !== undefined) bounds.push(`≤ ${this.valueText(rule.field, rule.max)}`); return `${this.fieldName(rule.field)} ${bounds.join(' 且 ') || '已启用'}`; },
        operatorMeta(id) { return this.preflight?.framework?.operator_catalog?.[id] || { id, name: id, gate: false, missing: false }; },
        chapterName(id) { return this.chapterTitles[id] || id; },
    },
};

const LatestJudgementPage = {
    components: { QualitativeRunPreview },
    template: `
<div class="page qualitative-batch-page">
    <workspace-page-header eyebrow="结构化投研 · 当前截面" title="最新研判" description="从当前截面候选池出发，按同一研究框架批量形成可比较的结构化结论。">
        <template #meta><span class="page-header-chip"><span>执行口径</span>筛选池 → 章节 DAG</span></template>
    </workspace-page-header>

    <section class="card qualitative-run-config">
        <div class="section-title-row"><div><h2>当前批量方案</h2><p>引用已有筛选策略与研究框架，不创建新的项目或规则副本。</p></div><span class="method-badge" v-if="options.status?.latest_date">本地数据 {{ options.status.latest_date }}</span></div>
        <div class="qualitative-config-grid">
            <div class="setting-item"><label>候选筛选策略</label><select v-model="form.screening_strategy_id"><option v-for="item in options.screening_strategies" :key="item.id" :value="item.id">{{ item.name }}</option></select></div>
            <div class="setting-item"><label>研究框架</label><select v-model="form.framework_id"><option v-for="item in options.frameworks" :key="item.id" :value="item.id">{{ item.name }}{{ item.valid === false ? '（结构有误）' : '' }}</option></select></div>
            <div class="setting-item"><label>分析数量</label><input type="number" v-model.number="form.top_n" min="1" max="100" /></div>
            <div class="setting-item"><label>并发数</label><input type="number" v-model.number="form.concurrency" min="1" max="10" /></div>
        </div>
        <div class="qualitative-preflight" v-if="preflight">
            <div><span>预计分析</span><strong>{{ preflight.estimated.analyses }} 只</strong></div>
            <div><span>预计耗时</span><strong>约 {{ preflight.estimated.minutes }} 分钟</strong></div>
            <div><span>成本估算</span><strong>约 ¥{{ preflight.estimated.cost_yuan }}</strong></div>
            <div><span>Agent 配置</span><strong>{{ preflight.llm.model }} · T={{ preflight.llm.temperature }} · {{ preflight.llm.max_tokens }} tokens</strong></div>
        </div>
        <qualitative-run-preview :preflight="preflight" :candidate-preview="candidatePreview" :previewing="previewing" :preview-error="previewError" :top-n="form.top_n" mode="latest" @refresh="refreshCandidatePreview(true)" />
        <div class="qualitative-warnings" v-if="preflight?.warnings?.length"><strong>运行前提醒</strong><span v-for="item in preflight.warnings" :key="item">{{ item }}</span></div>
        <div class="qualitative-blockers" v-if="preflight?.blockers?.length"><strong>执行前需要处理</strong><span v-for="item in preflight.blockers" :key="item">{{ item }}</span></div>
        <div class="research-actions">
            <button class="btn btn-primary" @click="start" :disabled="!preflight?.ready || isRunning">{{ isRunning ? '批量研判中…' : '执行最新研判' }}</button>
            <button class="btn" @click="pause" v-if="isRunning">暂停</button>
            <button class="btn btn-primary" @click="resume" v-if="['paused','failed','interrupted'].includes(currentJob?.status)">继续补齐</button>
            <span class="setting-hint">运行时冻结候选名单、框架和数据截面；失败项可继续补齐。</span>
        </div>
        <div class="error-msg" v-if="error">{{ error }}</div>
    </section>

    <section class="card qualitative-progress qualitative-failed" v-if="currentJob && ['failed','interrupted'].includes(currentJob.status)">
        <div class="section-title-row"><div><h2>任务未完整完成</h2><p>{{ currentJob.error || currentJob.message }}</p></div><span class="badge badge-failed">{{ currentJob.status === 'interrupted' ? '运行中断' : '执行失败' }}</span></div>
        <div class="qualitative-progress-facts"><span>总计 <strong>{{ currentJob.progress?.total || 0 }}</strong></span><span>已完成 <strong>{{ currentJob.progress?.completed || 0 }}</strong></span><span>失败 <strong>{{ currentJob.progress?.failed || 0 }}</strong></span><span>可从未完成项继续，不重复已有报告</span></div>
    </section>

    <section class="card qualitative-progress" v-if="currentJob && ['queued','running','pause_requested','paused'].includes(currentJob.status)">
        <div class="section-title-row"><div><h2>{{ currentJob.status === 'paused' ? '任务已暂停' : '批量执行进度' }}</h2><p>{{ currentJob.message }}</p></div><span class="badge badge-running">{{ stageLabel(currentJob.stage) }}</span></div>
        <div class="qualitative-progress-track"><span :style="{ width: progressPercent + '%' }"></span></div>
        <div class="qualitative-progress-facts"><span>总计 <strong>{{ currentJob.progress?.total || 0 }}</strong></span><span>成功 <strong>{{ currentJob.progress?.completed || 0 }}</strong></span><span>失败 <strong>{{ currentJob.progress?.failed || 0 }}</strong></span><span>进度 <strong>{{ progressPercent }}%</strong></span></div>
    </section>

    <section class="card qualitative-result" v-if="currentJob?.status === 'completed' && currentJob.result">
        <div class="section-title-row"><div><div class="workspace-eyebrow">最新截面研判结果</div><h2>{{ currentJob.params.framework_name }}</h2><p>{{ currentJob.result.effective_date }} · {{ currentJob.params.screening_strategy_name }} · 共完成 {{ currentJob.result.completed }} 只</p></div><button class="btn btn-small" @click="load">刷新</button></div>
        <div class="qualitative-result-summary">
            <div><span>原始股票池</span><strong>{{ currentJob.result.universe }}</strong></div>
            <div><span>筛选命中</span><strong>{{ currentJob.result.after_filters }}</strong></div>
            <div><span>完成研判</span><strong>{{ currentJob.result.completed }}</strong></div>
            <div><span>失败</span><strong>{{ currentJob.result.failed }}</strong></div>
        </div>
        <div class="qualitative-rec-distribution"><span v-for="(count, label) in currentJob.result.recommendation_counts" :key="label"><em>{{ label }}</em><strong>{{ count }}</strong></span></div>
        <div class="table-wrap"><table class="research-result-table qualitative-result-table"><thead><tr><th>股票</th><th>评分</th><th>建议</th><th>信心</th><th>核心逻辑</th><th>关键风险</th><th>扩展结论</th><th>状态</th></tr></thead><tbody><tr v-for="row in currentJob.rows" :key="row.ts_code"><td><strong>{{ row.stock_name || row.ts_code }}</strong><small>{{ row.ts_code }} · {{ row.industry || '行业未知' }}</small></td><td><strong :class="scoreClass(row.score)">{{ row.score ?? '—' }}</strong></td><td><span class="method-badge">{{ row.recommendation || '—' }}</span></td><td>{{ row.confidence || '—' }}</td><td class="qualitative-long-cell">{{ row.core_logic || '—' }}</td><td class="qualitative-long-cell">{{ row.risks || '—' }}</td><td class="qualitative-long-cell"><details v-if="customSynthesisEntries(row).length"><summary>{{ customSynthesisEntries(row).length }} 项</summary><div class="qualitative-custom-fields"><span v-for="item in customSynthesisEntries(row)" :key="item.key"><strong>{{ item.key }}</strong>{{ formatSynthesisValue(item.value) }}</span></div></details><span v-else>—</span></td><td><span :class="row.status === 'completed' ? 'status-ready' : 'status-missing'">{{ row.status === 'completed' ? '完成' : '失败' }}</span><small v-if="row.error">{{ row.error }}</small><small class="contract-warning" v-for="warning in row.contract_warnings || []" :key="warning">{{ warning }}</small></td></tr></tbody></table></div>
    </section>
</div>`,
    data() {
        return {
            options: { screening_strategies: [], frameworks: [], status: {}, llm: {} },
            form: { screening_strategy_id: '', framework_id: '', top_n: 10, concurrency: 2 },
            preflight: null, preflightSequence: 0, candidatePreview: null, candidatePreviewKey: '', previewing: false, previewError: '', previewSequence: 0,
            jobs: [], currentJob: null, error: '', pollTimer: null, preflightTimer: null, formReady: false,
        };
    },
    computed: {
        isRunning() { return ['queued', 'running', 'pause_requested'].includes(this.currentJob?.status); },
        progressPercent() { const total = Number(this.currentJob?.progress?.total || 0); const done = Number(this.currentJob?.progress?.completed || 0) + Number(this.currentJob?.progress?.failed || 0); return total ? Math.min(100, Math.round(done / total * 100)) : 0; },
    },
    watch: { form: { deep: true, handler() { if (this.formReady) this.schedulePreflight(); } } },
    methods: {
        async load() {
            this.stopPolling(); this.error = '';
            try {
                this.options = await apiFetch('/api/qualitative/options');
                const strategy = qualitativePreferred(this.options.screening_strategies, 'screening-strategy-id');
                const framework = qualitativePreferred(this.options.frameworks, 'qualitative-framework-id', 'v6_enhanced');
                if (!this.form.screening_strategy_id) this.form.screening_strategy_id = strategy?.id || '';
                if (!this.form.framework_id) this.form.framework_id = framework?.id || '';
                this.formReady = true;
                await this.refreshPreflight();
                await this.loadJobs();
            } catch (error) { this.error = error.message; }
            this.syncContext();
        },
        schedulePreflight() { clearTimeout(this.preflightTimer); this.preflight = null; this.currentJob = null; this.previewError = ''; this.preflightSequence += 1; this.previewSequence += 1; this.preflightTimer = setTimeout(async () => { await this.refreshPreflight(); await this.loadJobs(); }, 350); },
        async refreshPreflight() {
            if (!this.form.screening_strategy_id || !this.form.framework_id) return;
            const sequence = ++this.preflightSequence;
            try { const result = await apiFetch('/api/qualitative/latest/preflight', { method: 'POST', body: JSON.stringify(this.form) }); if (sequence !== this.preflightSequence) return; this.preflight = result; localStorage.setItem('qualitative-framework-id', this.form.framework_id); this.refreshCandidatePreview(); }
            catch (error) { if (sequence === this.preflightSequence) this.error = error.message; }
            this.syncContext();
        },
        async refreshCandidatePreview(force = false) {
            const definition = this.preflight?.screening_strategy?.definition;
            const asOfDate = this.preflight?.latest_date;
            if (!definition || !asOfDate) return;
            const previewKey = `${this.preflight.screening_strategy.identity}|${asOfDate}|${Number(this.form.top_n)}|latest`;
            if (!force && this.candidatePreview && this.candidatePreviewKey === previewKey) return;
            const sequence = ++this.previewSequence; this.previewing = true; this.previewError = '';
            try { const result = await apiFetch('/api/research/screening-preview', { method: 'POST', body: JSON.stringify({ definition, as_of_date: asOfDate, top_n: Number(this.form.top_n), historical: false, force }) }); if (sequence === this.previewSequence) { this.candidatePreview = result; this.candidatePreviewKey = previewKey; } }
            catch (error) { if (sequence === this.previewSequence) this.previewError = error.message; }
            finally { if (sequence === this.previewSequence) this.previewing = false; }
        },
        async loadJobs() {
            this.jobs = await apiFetch('/api/qualitative/jobs?kind=latest_judgement&limit=20&current_only=true');
            const active = this.jobs.find(job => ['queued','running','pause_requested','paused'].includes(job.status));
            const relevant = this.jobs.find(job => ['completed','failed','interrupted'].includes(job.status) && this.jobMatchesForm(job));
            this.currentJob = active || relevant || null;
            if (['queued','running','pause_requested'].includes(this.currentJob?.status)) this.startPolling();
        },
        jobMatchesForm(job) { return job?.params?.screening_strategy_id === this.form.screening_strategy_id && job?.params?.framework_id === this.form.framework_id && Number(job?.params?.top_n) === Number(this.form.top_n) && (!this.preflight?.requested_date || job?.params?.cutoff_date === this.preflight.requested_date); },
        async start() { this.error = ''; try { this.currentJob = await apiFetch('/api/qualitative/latest/start', { method: 'POST', body: JSON.stringify(this.form) }); this.startPolling(); } catch (error) { this.error = error.message; } this.syncContext(); },
        async pause() { if (!this.currentJob) return; try { this.currentJob = await apiFetch(`/api/qualitative/jobs/${this.currentJob.id}/pause`, { method: 'POST' }); } catch (error) { this.error = error.message; } },
        async resume() { if (!this.currentJob) return; try { this.currentJob = await apiFetch(`/api/qualitative/jobs/${this.currentJob.id}/resume`, { method: 'POST' }); this.startPolling(); } catch (error) { this.error = error.message; } },
        startPolling() { this.stopPolling(); this.pollTimer = setInterval(this.poll, 1600); this.poll(); },
        stopPolling() { if (this.pollTimer) clearInterval(this.pollTimer); this.pollTimer = null; },
        async poll() { if (!this.currentJob) return; try { this.currentJob = await apiFetch(`/api/qualitative/jobs/${this.currentJob.id}`); if (!['queued','running','pause_requested'].includes(this.currentJob.status)) this.stopPolling(); } catch (error) { this.error = error.message; this.stopPolling(); } this.syncContext(); },
        syncContext() { qualitativeJobContext('最新研判', this.form, this.preflight, this.currentJob); },
        stageLabel(value) { return ({ queued: '等待', screening: '截面筛选', analysis: 'DAG 分析', pause_requested: '等待暂停', paused: '已暂停' })[value] || value || '执行中'; },
        scoreClass(value) { const thresholds = this.currentJob?.params?.framework_snapshot?.synthesis?.decision_thresholds || this.preflight?.framework?.synthesis?.decision_thresholds || {}; const buy = Number(thresholds.buy ?? 70); const avoid = Number(thresholds.avoid ?? 29); return Number(value) >= buy ? 'return-positive' : (Number(value) <= avoid ? 'return-negative' : ''); },
        customSynthesisEntries(row) { const publicKeys = new Set(['综合评分','总体评分','score','overall_score','最终建议','投资建议','recommendation','核心逻辑','一句话买入逻辑（强制）','一句话买入逻辑','buy_logic','关键风险','风险提示','主要风险','risks','信心水平','置信度','confidence']); return Object.entries(row?.synthesis_fields || {}).filter(([key]) => !publicKeys.has(key)).map(([key,value]) => ({ key, value })); },
        formatSynthesisValue(value) { return Array.isArray(value) ? value.join('；') : (typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value ?? '—')); },
    },
    mounted() { this.load(); },
    beforeUnmount() { this.stopPolling(); clearTimeout(this.preflightTimer); this.preflightSequence += 1; this.previewSequence += 1; },
};

const FrameworkValidationPage = {
    components: { QualitativeRunPreview },
    template: `
<div class="page qualitative-batch-page">
    <workspace-page-header eyebrow="结构化投研 · 历史验证" title="框架验证" description="用历史时点可见数据运行完整章节 DAG，检验框架相对原始筛选池是否产生增量判断力。">
        <template #meta><span class="page-header-chip"><span>历史纪律</span>严格无前视</span></template>
    </workspace-page-header>

    <section class="card qualitative-run-config">
        <div class="section-title-row"><div><h2>验证方案</h2><p>框架和筛选策略仍各自独立，只在本次运行中组合。</p></div><span class="method-badge">筛选池 → 框架 → 前瞻收益</span></div>
        <div class="qualitative-config-grid validation">
            <div class="setting-item"><label>候选筛选策略</label><select v-model="form.screening_strategy_id"><option v-for="item in options.screening_strategies" :key="item.id" :value="item.id">{{ item.name }}</option></select></div>
            <div class="setting-item"><label>研究框架</label><select v-model="form.framework_id"><option v-for="item in options.frameworks" :key="item.id" :value="item.id">{{ item.name }}{{ item.valid === false ? '（结构有误）' : (item.history_blocker_count ? '（暂不可验证）' : '') }}</option></select><small class="setting-hint">验证时只使用截面当时可见的数据</small></div>
            <div class="setting-item"><label>开始截面</label><input type="date" v-model="form.start_date" /></div>
            <div class="setting-item"><label>结束截面</label><input type="date" v-model="form.end_date" /></div>
            <div class="setting-item"><label>截面频率</label><select v-model="form.interval"><option value="3m">每季度</option><option value="6m">每半年</option><option value="1y">每年</option></select></div>
            <div class="setting-item"><label>每期分析</label><input type="number" v-model.number="form.top_n" min="1" max="100" /></div>
            <div class="setting-item"><label>并发数</label><input type="number" v-model.number="form.concurrency" min="1" max="10" /></div>
        </div>
        <div class="qualitative-preflight" v-if="preflight">
            <div><span>历史截面</span><strong>{{ preflight.estimated.slices }} 期</strong></div>
            <div><span>预计分析</span><strong>{{ preflight.estimated.analyses }} 次</strong></div>
            <div><span>预计耗时</span><strong>约 {{ preflight.estimated.minutes }} 分钟</strong></div>
            <div><span>成本估算</span><strong>约 ¥{{ preflight.estimated.cost_yuan }}</strong></div>
        </div>
        <qualitative-run-preview :preflight="preflight" :candidate-preview="candidatePreview" :previewing="previewing" :preview-error="previewError" :top-n="form.top_n" mode="validation" @refresh="refreshCandidatePreview(true)" />
        <div class="qualitative-warnings" v-if="preflight?.warnings?.length"><strong>运行前提醒</strong><span v-for="item in preflight.warnings" :key="item">{{ item }}</span></div>
        <div class="qualitative-blockers" v-if="nonFrameworkBlockers.length"><strong>当前方案不能执行</strong><span v-for="item in nonFrameworkBlockers" :key="item">{{ item }}</span></div>
        <div class="qualitative-history-boundary" v-if="preflight?.framework?.history_blockers?.length">
            <div class="qualitative-history-boundary-head">
                <div><strong>部分分析环节暂时无法验证</strong><span>其中 {{ preflight.framework.history_blockers.length }} 个环节依赖最新信息，目前没有相应的历史数据口径；系统不会静默删减框架。</span></div>
                <button class="btn btn-secondary btn-small" v-if="recommendedSafeFramework" @click="switchToSafeFramework">改用 {{ recommendedSafeFramework.name }}</button>
            </div>
            <details class="qualitative-blocker-details">
                <summary>查看不兼容算子</summary>
                <div v-for="item in preflight.framework.history_blockers" :key="item.id"><strong>{{ item.name }}</strong><span>{{ blockerKindLabel(item.kind) }}</span><small>{{ item.reason }}</small></div>
            </details>
        </div>
        <div class="research-actions"><button class="btn btn-primary" @click="start" :disabled="!preflight?.ready || isRunning">{{ isRunning ? '验证执行中…' : '开始框架验证' }}</button><button class="btn" @click="pause" v-if="isRunning">暂停</button><button class="btn btn-primary" @click="resume" v-if="['paused','failed','interrupted'].includes(currentJob?.status)">继续补齐</button><span class="setting-hint">执行前先确认任务量和成本；再次继续只补未完成分析。</span></div>
        <div class="error-msg" v-if="error">{{ error }}</div>
    </section>

    <section class="card qualitative-progress qualitative-failed" v-if="currentJob && ['failed','interrupted'].includes(currentJob.status)">
        <div class="section-title-row"><div><h2>验证未完整完成</h2><p>{{ currentJob.error || currentJob.message }}</p></div><span class="badge badge-failed">{{ currentJob.status === 'interrupted' ? '运行中断' : '执行失败' }}</span></div>
        <div class="qualitative-progress-facts"><span>分析任务 <strong>{{ currentJob.progress?.total || 0 }}</strong></span><span>已完成 <strong>{{ currentJob.progress?.completed || 0 }}</strong></span><span>失败 <strong>{{ currentJob.progress?.failed || 0 }}</strong></span><span>继续时复用已有历史截面与报告</span></div>
    </section>

    <section class="card qualitative-progress" v-if="currentJob && ['queued','running','pause_requested','paused'].includes(currentJob.status)">
        <div class="section-title-row"><div><h2>{{ currentJob.status === 'paused' ? '验证已暂停' : '框架验证进度' }}</h2><p>{{ currentJob.message }}</p></div><span class="badge badge-running">{{ stageLabel(currentJob.stage) }}</span></div>
        <div class="qualitative-progress-track"><span :style="{ width: progressPercent + '%' }"></span></div>
        <div class="qualitative-progress-facts"><span>分析任务 <strong>{{ currentJob.progress?.total || 0 }}</strong></span><span>成功 <strong>{{ currentJob.progress?.completed || 0 }}</strong></span><span>失败 <strong>{{ currentJob.progress?.failed || 0 }}</strong></span><span>进度 <strong>{{ progressPercent }}%</strong></span></div>
    </section>

    <section class="card qualitative-archive" v-if="archiveJobs.length">
        <div class="section-title-row"><div><div class="workspace-eyebrow">已有研究证据</div><h2>历史验证档案</h2><p>从旧版批量回测产物转换而来，只读展示原始口径，不冒充当前参数运行。</p></div><button class="btn btn-secondary btn-small" v-if="currentJob?.status === 'completed' && selectedArchiveId" @click="showCurrentResult">查看当前方案结果</button></div>
        <div class="qualitative-archive-grid">
            <button v-for="job in archiveJobs" :key="job.id" class="qualitative-archive-card" :class="{ active: selectedArchiveId === job.id, unsafe: job.provenance?.current_history_safe === false }" @click="selectArchive(job.id)">
                <span class="qualitative-archive-label">{{ job.provenance?.current_history_safe === false ? '旧框架 · 未通过当前严格回溯检查' : '严格历史验证档案' }} · {{ job.params.framework_version || '旧版' }}{{ usesLegacyOutcome(job) ? ' · 旧收益口径' : '' }}</span>
                <strong>{{ job.params.framework_name }}</strong>
                <small>{{ job.params.start_date }} — {{ job.params.end_date }} · {{ intervalLabel(job.params.interval) }}</small>
                <div><span>{{ job.result.dates.length }} 个截面</span><span>{{ job.result.analysis_completed }}/{{ job.result.analysis_total }} 份有效分析</span><span>6个月框架增量 {{ archiveAlpha(job, '6个月') }}</span></div>
            </button>
        </div>
    </section>

    <section class="card qualitative-result" v-if="displayJob?.status === 'completed' && displayJob.result">
        <div class="section-title-row"><div><div class="workspace-eyebrow">{{ displayJob.imported ? '历史验证档案' : '框架增量效果' }}</div><h2>{{ displayJob.params.framework_name }}</h2><p>{{ displayJob.params.start_date }} — {{ displayJob.params.end_date }} · {{ intervalLabel(displayJob.params.interval) }} · {{ displayJob.result.dates.length }} 个有效截面</p></div><span class="badge" :class="displayJob.provenance?.current_history_safe === false ? 'badge-failed' : (!outcomeSemanticsCurrent ? 'badge-warning' : 'badge-completed')">{{ archiveContractLabel(displayJob) }}{{ !outcomeSemanticsCurrent ? ' · 旧收益口径' : '' }}</span></div>
        <div class="qualitative-result-summary"><div><span>研究框架</span><strong>{{ displayJob.params.framework_name }}{{ displayJob.params.framework_version ? ' ' + displayJob.params.framework_version : '' }}</strong></div><div><span>候选基线</span><strong>{{ displayJob.params.screening_strategy_name }}</strong></div><div><span>历史截面</span><strong>{{ displayJob.result.dates.length }}</strong></div><div><span>有效分析覆盖</span><strong>{{ displayJob.result.analysis_completed }}/{{ displayJob.result.analysis_total }}</strong></div></div>
        <div class="result-methodology-warning" v-if="!outcomeSemanticsCurrent">收益和 Alpha 继续按原始产物展示，但它们生成于当前后复权收益口径前，可能使用不复权价格；更早版本还可能包含未走完持有期的部分收益。结果仅作历史参考，新任务统一使用后复权口径。</div>
        <div class="table-wrap"><table class="research-result-table qualitative-performance-table"><thead><tr><th>比较对象</th><th v-for="period in periods" :key="period">{{ period }}</th></tr></thead><tbody><tr v-for="row in performanceRows" :key="row.key"><td><strong>{{ row.label }}</strong><small>{{ row.desc }}</small></td><td v-for="period in periods" :key="period"><template v-if="row.stats[period]?.count"><strong :class="returnClass(row.stats[period].mean)">{{ qualitativePercent(row.stats[period].mean) }}</strong><small>胜率 {{ qualitativePercent(row.stats[period].win_rate) }} · {{ row.stats[period].count }} 样本</small></template><span v-else>—</span></td></tr></tbody></table></div>
        <div class="qualitative-alpha" v-if="focusStats"><div><span>筛选池相对市场</span><strong :class="returnClass(focusStats.screenAlpha)">{{ qualitativePercent(focusStats.screenAlpha) }}</strong></div><div><span>框架买入相对筛选池</span><strong :class="returnClass(focusStats.agentAlpha)">{{ qualitativePercent(focusStats.agentAlpha) }}</strong></div><div><span>框架买入相对市场</span><strong :class="returnClass(focusStats.totalAlpha)">{{ qualitativePercent(focusStats.totalAlpha) }}</strong></div></div>
        <div class="qualitative-archive-note" :class="{ warning: displayJob.provenance?.current_history_safe === false }" v-if="displayJob.imported"><strong>口径说明</strong><span>{{ displayJob.provenance?.current_history_safe === false ? '该旧框架包含当前规则认定为不可严格历史回溯的算子，因此结果只作为旧实验参考，不作为无前视证据。' : '该产物通过当前框架的历史安全检查，但' }}数据源字段未保存在旧产物中；筛选条件来自当时框架内嵌配置，不等同于当前筛选策略。</span></div>
        <div class="result-path">结构化结果：{{ displayJob.result.summary_path }}</div>
    </section>
</div>`,
    data() {
        const year = new Date().getFullYear();
        return {
            options: { screening_strategies: [], frameworks: [], status: {}, llm: {} },
            form: { screening_strategy_id: '', framework_id: '', start_date: `${year - 5}-01-01`, end_date: `${year - 1}-12-31`, interval: '6m', top_n: 10, concurrency: 2 },
            preflight: null, preflightSequence: 0, candidatePreview: null, candidatePreviewKey: '', previewing: false, previewError: '', previewSequence: 0,
            jobs: [], currentJob: null, archiveJobs: [], selectedArchiveId: '', error: '', pollTimer: null, preflightTimer: null, formReady: false,
        };
    },
    computed: {
        isRunning() { return ['queued','running','pause_requested'].includes(this.currentJob?.status); },
        progressPercent() { const total = Number(this.currentJob?.progress?.total || 0); const done = Number(this.currentJob?.progress?.completed || 0) + Number(this.currentJob?.progress?.failed || 0); return total ? Math.min(100, Math.round(done / total * 100)) : 0; },
        selectedArchiveJob() { return this.archiveJobs.find(job => job.id === this.selectedArchiveId) || null; },
        displayJob() { return this.selectedArchiveJob || (this.currentJob?.status === 'completed' ? this.currentJob : null); },
        outcomeSemanticsCurrent() { return !this.usesLegacyOutcome(this.displayJob); },
        performanceRows() { const performance = this.displayJob?.result?.performance || {}; return ['market','screen_all','agent_buy','agent_top'].filter(key => performance[key]).map(key => ({ key, ...performance[key] })); },
        periods() { const values = []; for (const row of this.performanceRows) for (const key of Object.keys(row.stats || {})) if (typeof row.stats[key] === 'object' && !values.includes(key)) values.push(key); return values; },
        focusPeriod() { return ({ '3m': '3个月', '6m': '6个月', '1y': '12个月' })[this.displayJob?.params?.interval || this.form.interval] || this.periods[0]; },
        focusStats() { const performance = this.displayJob?.result?.performance || {}; const market = performance.market?.stats?.[this.focusPeriod]?.mean; const screen = performance.screen_all?.stats?.[this.focusPeriod]?.mean; const agent = performance.agent_buy?.stats?.[this.focusPeriod]?.mean; if (![market, screen, agent].every(value => Number.isFinite(Number(value)))) return null; return { screenAlpha: Number(screen) - Number(market), agentAlpha: Number(agent) - Number(screen), totalAlpha: Number(agent) - Number(market) }; },
        nonFrameworkBlockers() { return (this.preflight?.blockers || []).filter(item => item !== '框架包含不能用于严格历史验证的算子'); },
        safeFrameworks() { return this.options.frameworks.filter(item => item.valid !== false && item.history_safe); },
        recommendedSafeFramework() { return this.safeFrameworks.find(item => item.id === 'v6_value') || this.safeFrameworks[0] || null; },
    },
    watch: { form: { deep: true, handler() { if (this.formReady) this.schedulePreflight(); } } },
    methods: {
        qualitativePercent,
        blockerKindLabel(kind) { return ({ missing_operator: '引用错误', current_only_data: '需要最新数据', current_only_context: '需要实时信息', invalid_history_adapter: '历史口径不一致' })[kind] || '时间边界'; },
        switchToSafeFramework() { if (this.recommendedSafeFramework) this.form.framework_id = this.recommendedSafeFramework.id; },
        async load() {
            this.stopPolling(); this.error = '';
            try {
                this.options = await apiFetch('/api/qualitative/options');
                const strategy = qualitativePreferred(this.options.screening_strategies, 'screening-strategy-id');
                const safeFrameworks = this.options.frameworks.filter(item => item.history_safe);
                const framework = qualitativePreferred(safeFrameworks.length ? safeFrameworks : this.options.frameworks, 'qualitative-validation-framework-id', 'v6_value');
                if (!this.form.screening_strategy_id) this.form.screening_strategy_id = strategy?.id || '';
                if (!this.form.framework_id) this.form.framework_id = framework?.id || '';
                this.formReady = true;
                await this.refreshPreflight();
                await this.loadJobs();
                await this.loadArchive();
            } catch (error) { this.error = error.message; }
            this.syncContext();
        },
        schedulePreflight() { clearTimeout(this.preflightTimer); this.preflight = null; this.currentJob = null; this.previewError = ''; this.preflightSequence += 1; this.previewSequence += 1; this.preflightTimer = setTimeout(async () => { await this.refreshPreflight(); await this.loadJobs(); }, 350); },
        async refreshPreflight() { if (!this.form.screening_strategy_id || !this.form.framework_id) return; const sequence = ++this.preflightSequence; try { const result = await apiFetch('/api/qualitative/validation/preflight', { method: 'POST', body: JSON.stringify(this.form) }); if (sequence !== this.preflightSequence) return; this.preflight = result; localStorage.setItem('qualitative-validation-framework-id', this.form.framework_id); this.refreshCandidatePreview(); } catch (error) { if (sequence === this.preflightSequence) this.error = error.message; } this.syncContext(); },
        async refreshCandidatePreview(force = false) {
            const definition = this.preflight?.screening_strategy?.definition;
            const dates = this.preflight?.dates || [];
            const latestDate = this.preflight?.latest_date || '';
            const asOfDate = [...dates].reverse().find(value => !latestDate || value <= latestDate) || dates[dates.length - 1];
            if (!definition || !asOfDate || !latestDate) return;
            const previewKey = `${this.preflight.screening_strategy.identity}|${asOfDate}|${Number(this.form.top_n)}|historical`;
            if (!force && this.candidatePreview && this.candidatePreviewKey === previewKey) return;
            const sequence = ++this.previewSequence; this.previewing = true; this.previewError = '';
            try { const result = await apiFetch('/api/research/screening-preview', { method: 'POST', body: JSON.stringify({ definition, as_of_date: asOfDate, top_n: Number(this.form.top_n), historical: true, force }) }); if (sequence === this.previewSequence) { this.candidatePreview = result; this.candidatePreviewKey = previewKey; } }
            catch (error) { if (sequence === this.previewSequence) this.previewError = error.message; }
            finally { if (sequence === this.previewSequence) this.previewing = false; }
        },
        async loadJobs() { this.jobs = await apiFetch('/api/qualitative/jobs?kind=framework_validation&limit=20&current_only=true'); const active = this.jobs.find(job => ['queued','running','pause_requested','paused'].includes(job.status)); const relevant = this.jobs.find(job => ['completed','failed','interrupted'].includes(job.status) && this.jobMatchesForm(job)); this.currentJob = active || relevant || null; if (['queued','running','pause_requested'].includes(this.currentJob?.status)) this.startPolling(); },
        async loadArchive() { this.archiveJobs = await apiFetch('/api/qualitative/validation/archive'); if (!this.selectedArchiveId && this.currentJob?.status !== 'completed') this.selectedArchiveId = this.archiveJobs[0]?.id || ''; },
        jobMatchesForm(job) { return job?.params?.screening_strategy_id === this.form.screening_strategy_id && job?.params?.framework_id === this.form.framework_id && job?.params?.start_date === this.form.start_date && job?.params?.end_date === this.form.end_date && job?.params?.interval === this.form.interval && Number(job?.params?.top_n) === Number(this.form.top_n); },
        async start() { this.error = ''; this.selectedArchiveId = ''; try { this.currentJob = await apiFetch('/api/qualitative/validation/start', { method: 'POST', body: JSON.stringify(this.form) }); this.startPolling(); } catch (error) { this.error = error.message; } this.syncContext(); },
        selectArchive(id) { this.selectedArchiveId = id; },
        showCurrentResult() { this.selectedArchiveId = ''; },
        archiveAlpha(job, period) { const performance = job?.result?.performance || {}; const screen = Number(performance.screen_all?.stats?.[period]?.mean); const agent = Number(performance.agent_buy?.stats?.[period]?.mean); return Number.isFinite(screen) && Number.isFinite(agent) ? qualitativePercent(agent - screen) : '—'; },
        archiveContractLabel(job) { if (!job?.imported) return '已完成'; return job.provenance?.current_history_safe === false ? '旧实验参考' : '只读档案'; },
        usesLegacyOutcome(job) { return Number(job?.result?.outcome_schema_version || 1) < 3; },
        async pause() { if (!this.currentJob) return; try { this.currentJob = await apiFetch(`/api/qualitative/jobs/${this.currentJob.id}/pause`, { method: 'POST' }); } catch (error) { this.error = error.message; } },
        async resume() { if (!this.currentJob) return; try { this.currentJob = await apiFetch(`/api/qualitative/jobs/${this.currentJob.id}/resume`, { method: 'POST' }); this.startPolling(); } catch (error) { this.error = error.message; } },
        startPolling() { this.stopPolling(); this.pollTimer = setInterval(this.poll, 1600); this.poll(); },
        stopPolling() { if (this.pollTimer) clearInterval(this.pollTimer); this.pollTimer = null; },
        async poll() { if (!this.currentJob) return; try { this.currentJob = await apiFetch(`/api/qualitative/jobs/${this.currentJob.id}`); if (!['queued','running','pause_requested'].includes(this.currentJob.status)) { this.stopPolling(); if (this.currentJob.status === 'completed') this.selectedArchiveId = ''; } } catch (error) { this.error = error.message; this.stopPolling(); } this.syncContext(); },
        syncContext() { qualitativeJobContext('框架验证', this.form, this.preflight, this.currentJob); },
        stageLabel(value) { return ({ queued: '等待', screening: '历史截面', analysis: 'DAG 分析', evaluation: '收益评估', pause_requested: '等待暂停', paused: '已暂停' })[value] || value || '执行中'; },
        intervalLabel(value) { return ({ '3m': '每季度', '6m': '每半年', '1y': '每年' })[value] || value; },
        returnClass(value) { return Number(value) > 0 ? 'return-positive' : (Number(value) < 0 ? 'return-negative' : ''); },
    },
    mounted() { this.load(); },
    beforeUnmount() { this.stopPolling(); clearTimeout(this.preflightTimer); this.preflightSequence += 1; this.previewSequence += 1; },
};
