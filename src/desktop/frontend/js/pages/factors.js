/** Provider-aware native-field and derived-factor catalog. */
const FactorsPage = {
    template: `
<div class="page-research-workspace factor-library-page">
    <workspace-page-header eyebrow="基础设施 · 因子资产" title="因子库" description="统一管理数据源原生字段与可复用派生因子。">
        <template #meta><span class="page-header-chip" v-if="catalog"><span>当前数据源</span>{{ catalog.provider }}</span></template>
        <template #actions><button class="btn btn-primary btn-small" @click="startCreate">+ 新建 DSL 因子</button></template>
    </workspace-page-header>

    <section class="page-context-alert" v-if="catalog && catalog.provider === 'baostock'">
        <strong>BaoStock 数据边界</strong>
        <span>当前仅覆盖行情、技术和基础估值字段；完整基本面因子需要 Tushare 或其他完整财务数据源。</span>
    </section>

    <section class="factor-job-notice" v-if="jobNotice" :class="jobNotice.status">
        <div>
            <strong>{{ jobNotice.title }}</strong>
            <span>{{ jobNotice.message }}</span>
        </div>
        <div class="factor-job-progress" v-if="jobNotice.status === 'queued' || jobNotice.status === 'running'">
            <i :style="{ width: (jobNotice.percent || 0) + '%' }"></i>
        </div>
    </section>

    <div class="card factor-summary-grid" v-if="catalog">
        <div><span>目录资产</span><strong>{{ catalog.summary.total }}</strong><small>{{ catalog.summary.native }} 原生 · {{ catalog.summary.derived }} 派生</small></div>
        <div><span>Polars DSL</span><strong>{{ catalog.summary.dsl }}</strong><small>受控表达式定义</small></div>
        <div><span>研究可用</span><strong>{{ catalog.summary.eligible }}</strong><small>精确口径且时点安全</small></div>
        <div><span>已物化</span><strong>{{ catalog.summary.materialized }}</strong><small>当前 Provider 本地覆盖</small></div>
        <div><span>不可用</span><strong>{{ catalog.summary.unavailable }}</strong><small>缺少精确字段映射</small></div>
    </div>

    <div class="card factor-toolbar">
        <input v-model.trim="searchText" placeholder="搜索名称、ID、语义字段或依赖" />
        <select v-model="kindFilter">
            <option value="">全部资产</option>
            <option value="native">原生字段</option>
            <option value="derived">派生因子</option>
        </select>
        <select v-model="statusFilter">
            <option value="">全部状态</option>
            <option value="eligible">研究可用</option>
            <option value="live_only">仅最新值</option>
            <option value="unavailable">当前源不可用</option>
            <option value="materialized">已物化</option>
            <option value="needs_compute">待计算 / 已失效</option>
        </select>
        <select v-model="categoryFilter">
            <option value="">全部分类</option>
            <option v-for="category in categories" :key="category" :value="category">{{ category }}</option>
        </select>
    </div>

    <div class="factor-library-split">
        <section class="card factor-asset-list">
            <div class="factor-list-count">{{ filteredItems.length }} 项</div>
            <button
                v-for="item in filteredItems"
                :key="item.asset_kind + ':' + item.id"
                class="factor-asset-item"
                :class="{ active: selected && selected.id === item.id }"
                @click="selectItem(item)"
            >
                <div class="factor-item-main">
                    <strong>{{ item.name }}</strong>
                    <span class="factor-kind-tag" :class="item.asset_kind">{{ item.asset_kind === 'native' ? '原生' : item.engine === 'polars' ? 'DSL' : 'Python' }}</span>
                </div>
                <code>{{ item.id }}</code>
                <div class="factor-item-status">
                    <span :class="'factor-status ' + item.provider.compatibility">{{ compatibilityLabel(item.provider.compatibility) }}</span>
                    <span :class="'factor-status research-' + item.research_status">{{ researchLabel(item.research_status) }}</span>
                    <span v-if="item.asset_kind === 'derived'" :class="'factor-status materialization-' + item.materialization.status">{{ materializationLabel(item.materialization.status) }}</span>
                </div>
            </button>
            <div class="empty-state" v-if="!loading && !filteredItems.length">暂无匹配资产</div>
            <div class="empty-state" v-if="loading">正在读取因子目录…</div>
        </section>

        <section class="card factor-detail" v-if="selected && !editMode">
            <header class="factor-detail-header">
                <div>
                    <div class="workspace-eyebrow">{{ selected.asset_kind === 'native' ? '原生语义字段' : '派生因子' }}</div>
                    <h2>{{ selected.name }}</h2>
                    <code>{{ selected.semantic_id }}</code>
                </div>
                <div class="factor-detail-actions" v-if="selected.editable">
                    <button v-if="selected.materialization_blockers?.length" class="btn btn-primary" @click="prepareSelected" :disabled="saving">补齐依赖并计算</button>
                    <button v-else class="btn btn-secondary" @click="materializeSelected" :disabled="saving || ['pending', 'computing'].includes(selected.materialization.status)">重新计算</button>
                    <button class="btn btn-secondary" @click="startEdit">编辑因子</button>
                </div>
            </header>

            <p class="factor-description">{{ selected.description || '暂无说明' }}</p>
            <div class="factor-state-grid">
                <div><span>Provider 兼容</span><strong>{{ compatibilityLabel(selected.provider.compatibility) }}</strong><small>{{ selected.provider.note || selected.provider.dataset || '—' }}</small></div>
                <div><span>物化状态</span><strong>{{ materializationLabel(selected.materialization.status) }}</strong><small>{{ selected.materialization.start_date || '起点未知' }} → {{ selected.materialization.latest_date || '—' }}</small></div>
                <div><span>时点安全</span><strong>{{ selected.point_in_time_safe ? '严格' : '未保证' }}</strong><small>{{ researchLabel(selected.research_status) }}</small></div>
                <div><span>执行方式</span><strong>{{ selected.engine }}</strong><small>{{ selected.execution_mode || 'native' }} · {{ selected.grain }}</small></div>
            </div>
            <div class="factor-materialization-error" v-if="selected.materialization.error">{{ selected.materialization.error }}</div>
            <div class="factor-materialization-blockers" v-if="selected.materialization_blockers?.length">
                <strong>{{ selected.provider.compatibility === 'exact' ? '计算前还需补齐' : '当前数据源不支持' }}</strong>
                <span v-for="blocker in selected.materialization_blockers" :key="blocker">{{ blocker }}</span>
                <small v-if="selected.provider.compatibility === 'exact'">数据任务完成后，系统会自动续接该因子的物化计算。</small>
                <small v-else>该状态不是下载缺失；需要切换到支持此口径的数据源，或另行定义有可靠输入的派生因子。</small>
            </div>

            <div class="factor-detail-section">
                <h3>定义元数据</h3>
                <dl class="factor-meta-list">
                    <div><dt>ID</dt><dd><code>{{ selected.id }}</code></dd></div>
                    <div><dt>分类</dt><dd>{{ selected.category }}</dd></div>
                    <div><dt>单位</dt><dd>{{ selected.unit || '—' }}</dd></div>
                    <div><dt>方向</dt><dd>{{ directionLabel(selected.direction) }}</dd></div>
                    <div><dt>定义哈希</dt><dd><code>{{ selected.definition_hash || '原生字段' }}</code></dd></div>
                    <div><dt>来源</dt><dd class="factor-path">{{ selected.source_path }}</dd></div>
                </dl>
            </div>

            <div class="factor-detail-section" v-if="Object.keys(selected.inputs || {}).length">
                <h3>输入依赖</h3>
                <div class="factor-input-list">
                    <span v-for="(semanticId, alias) in selected.inputs" :key="alias"><code>{{ alias }}</code><em v-if="selected.optional_inputs.includes(alias)">可选</em> → {{ semanticId }}</span>
                </div>
            </div>

            <div class="factor-detail-section" v-if="selected.expression">
                <h3>Polars DSL</h3>
                <pre class="factor-expression">{{ selected.expression }}</pre>
            </div>

            <div class="factor-detail-section" v-if="selected.asset_kind === 'native'">
                <h3>当前 Provider 绑定</h3>
                <div class="factor-binding-line"><code>{{ selected.provider.dataset || '未映射' }}.{{ selected.provider.field || '' }}</code></div>
            </div>
        </section>

        <section class="card factor-detail" v-else-if="editMode">
            <header class="factor-detail-header">
                <div><div class="workspace-eyebrow">POLARS DSL</div><h2>{{ isCreating ? '新建派生因子' : '编辑 ' + form.name }}</h2></div>
                <button class="btn btn-secondary" @click="cancelEdit">取消</button>
            </header>

            <div class="factor-edit-grid">
                <div class="setting-item"><label>ID</label><input v-model.trim="form.id" :disabled="!isCreating" placeholder="如 earnings_yield" /></div>
                <div class="setting-item"><label>名称</label><input v-model.trim="form.name" placeholder="因子名称" /></div>
                <div class="setting-item"><label>分类 ID</label><select v-model="form.category"><option value="valuation">valuation</option><option value="size">size</option><option value="dividend">dividend</option><option value="quality">quality</option><option value="growth">growth</option><option value="solvency">solvency</option><option value="technical">technical</option><option value="other">other</option></select></div>
                <div class="setting-item"><label>方向</label><select v-model="form.direction"><option value="higher_better">越大越好</option><option value="lower_better">越小越好</option><option value="neutral">中性</option></select></div>
                <div class="setting-item"><label>单位</label><input v-model.trim="form.unit" placeholder="percent / ratio / cny" /></div>
                <div class="setting-item"><label>标签（逗号分隔）</label><input v-model="form.tagsText" placeholder="估值, 价值" /></div>
            </div>
            <div class="setting-item"><label>说明</label><textarea v-model="form.description" rows="3"></textarea></div>
            <div class="setting-item factor-input-builder">
                <div class="factor-builder-heading">
                    <div><label>输入字段</label><small>从原生语义字段中选择，不需要手写字段路径。</small></div>
                    <button class="btn btn-secondary btn-small" @click="addInput">+ 添加字段</button>
                </div>
                <div class="factor-input-row" v-for="(row, index) in form.inputRows" :key="index">
                    <input v-model.trim="row.alias" placeholder="表达式别名" />
                    <select v-model="row.semanticId">
                        <option value="">选择原生字段</option>
                        <option v-for="field in nativeFields" :key="field.semantic_id" :value="field.semantic_id">
                            {{ field.name }} · {{ field.semantic_id }}{{ field.provider.available ? '' : '（当前源不可用）' }}
                        </option>
                    </select>
                    <label class="factor-inline-check"><input type="checkbox" v-model="row.optional" /> 可选</label>
                    <button class="factor-remove-input" @click="removeInput(index)" title="移除字段">×</button>
                </div>
                <div class="factor-builder-empty" v-if="!form.inputRows.length">先添加一个原生字段作为计算输入。</div>
            </div>
            <div class="setting-item">
                <label>计算公式</label>
                <div class="factor-formula-tools">
                    <div class="factor-tool-group">
                        <span>插入字段</span>
                        <button v-for="row in form.inputRows.filter(item => item.alias)" :key="row.alias" @click="insertField(row.alias)">{{ row.alias }}</button>
                    </div>
                    <div class="factor-tool-group">
                        <span>公式模板</span>
                        <button @click="applyTemplate('inverse')">100 ÷ 字段</button>
                        <button @click="applyTemplate('ratio')">两字段相除</button>
                        <button @click="applyTemplate('coalesce')">缺失回退</button>
                        <button @click="applyTemplate('log')">对数</button>
                        <button @click="applyTemplate('rolling_mean')">3期均值</button>
                        <button @click="applyTemplate('cagr')">5期 CAGR</button>
                    </div>
                </div>
                <textarea ref="expressionEditor" class="factor-code-input" v-model="form.expression" rows="6" placeholder='例如：round(safe_div(100.0, col("pe")), 2)'></textarea>
                <small>支持算术、比较、safe_div、round、abs、sqrt、log、log1p、exp、clip、fill_null、coalesce、when；财报字段还支持 lag、rolling_mean、rolling_sum、rolling_std、cagr 和 positive_streak。</small>
            </div>
            <label class="factor-policy-check"><input type="checkbox" v-model="form.pointInTimeSafe" /> 声明为严格时点安全</label>
            <div class="factor-edit-actions">
                <button class="btn btn-secondary" @click="validateForm" :disabled="saving">验证</button>
                <button class="btn btn-primary" @click="saveFactor" :disabled="saving">{{ saving ? '保存中…' : '保存因子' }}</button>
            </div>
            <div class="save-status" v-if="message" :class="messageSuccess ? 'success' : 'error'">{{ message }}</div>
        </section>
    </div>

    <div class="error-msg" v-if="error">{{ error }}</div>
</div>
    `,

    data() {
        return {
            catalog: null,
            selected: null,
            loading: false,
            error: '',
            searchText: '',
            kindFilter: '',
            statusFilter: '',
            categoryFilter: '',
            editMode: false,
            isCreating: false,
            saving: false,
            message: '',
            messageSuccess: false,
            jobNotice: null,
            jobPollTimer: null,
            form: {},
        };
    },

    computed: {
        categories() {
            return [...new Set((this.catalog?.items || []).map(item => item.category))].sort();
        },
        nativeFields() {
            return (this.catalog?.items || [])
                .filter(item => item.asset_kind === 'native')
                .slice()
                .sort((left, right) => left.name.localeCompare(right.name, 'zh-CN'));
        },
        filteredItems() {
            const query = this.searchText.toLowerCase();
            return (this.catalog?.items || []).filter(item => {
                if (this.kindFilter && item.asset_kind !== this.kindFilter) return false;
                if (this.categoryFilter && item.category !== this.categoryFilter) return false;
                if (this.statusFilter === 'materialized' && !item.materialization.usable) return false;
                if (this.statusFilter === 'needs_compute' && (item.asset_kind !== 'derived' || item.materialization.usable)) return false;
                if (this.statusFilter && !['materialized', 'needs_compute'].includes(this.statusFilter) && item.research_status !== this.statusFilter) return false;
                if (!query) return true;
                return [item.id, item.semantic_id, item.name, item.description, ...Object.values(item.inputs || {})]
                    .join(' ').toLowerCase().includes(query);
            });
        },
    },

    methods: {
        async loadCatalog(preferredId = '') {
            this.loading = true;
            this.error = '';
            try {
                this.catalog = await apiFetch('/api/factors');
                const next = this.catalog.items.find(item => item.id === preferredId)
                    || this.catalog.items.find(item => this.selected && item.id === this.selected.id)
                    || this.catalog.items[0];
                this.selectItem(next || null);
            } catch (error) {
                this.error = `加载因子库失败：${error.message}`;
            } finally {
                this.loading = false;
            }
        },
        selectItem(item) {
            this.selected = item;
            this.editMode = false;
            this.isCreating = false;
            this.message = '';
            window.setAppContext?.({ page: 'factors', provider: this.catalog?.provider, factor: item });
        },
        compatibilityLabel(value) {
            return ({ exact: '精确', approximate: '近似', unavailable: '不可用' })[value] || value;
        },
        researchLabel(value) {
            return ({ eligible: '研究可用', live_only: '仅最新值', unavailable: '不可用' })[value] || value;
        },
        materializationLabel(value) {
            return ({
                ready: '已物化 · 版本一致',
                ready_unverified: '已物化 · 待校验版本',
                pending: '等待计算',
                computing: '计算中',
                stale: '定义已更新 · 待重算',
                failed: '计算失败',
                not_materialized: '未物化',
            })[value] || value;
        },
        directionLabel(value) {
            return ({ higher_better: '越大越好', lower_better: '越小越好', neutral: '中性' })[value] || value;
        },
        emptyForm() {
            return {
                id: '', name: '', category: 'other', description: '', tagsText: '',
                direction: 'neutral', unit: '', inputRows: [], expression: '', pointInTimeSafe: true,
            };
        },
        startCreate() {
            this.form = this.emptyForm();
            this.isCreating = true;
            this.editMode = true;
            this.message = '';
        },
        startEdit() {
            const item = this.selected;
            this.form = {
                id: item.id,
                name: item.name,
                category: item.category_id || 'other',
                description: item.description || '',
                tagsText: (item.tags || []).join(', '),
                direction: item.direction || 'neutral',
                unit: item.unit || '',
                inputRows: Object.entries(item.inputs || {}).map(([alias, semantic]) => ({
                    alias,
                    semanticId: semantic,
                    optional: (item.optional_inputs || []).includes(alias),
                })),
                expression: item.expression || '',
                pointInTimeSafe: !!item.point_in_time_safe,
            };
            this.isCreating = false;
            this.editMode = true;
            this.message = '';
        },
        cancelEdit() {
            this.editMode = false;
            this.isCreating = false;
            this.message = '';
        },
        addInput() {
            const used = new Set(this.form.inputRows.map(row => row.semanticId));
            const field = this.nativeFields.find(item => item.provider.available && !used.has(item.semantic_id))
                || this.nativeFields.find(item => !used.has(item.semantic_id));
            let alias = field?.id || `input_${this.form.inputRows.length + 1}`;
            const aliases = new Set(this.form.inputRows.map(row => row.alias));
            let suffix = 2;
            const baseAlias = alias;
            while (aliases.has(alias)) alias = `${baseAlias}_${suffix++}`;
            this.form.inputRows.push({ alias, semanticId: field?.semantic_id || '', optional: false });
        },
        removeInput(index) {
            this.form.inputRows.splice(index, 1);
        },
        insertField(alias) {
            const token = `col("${alias}")`;
            this.$nextTick(() => {
                const editor = this.$refs.expressionEditor;
                if (!editor || typeof editor.selectionStart !== 'number') {
                    this.form.expression = `${this.form.expression}${this.form.expression ? ' ' : ''}${token}`;
                    return;
                }
                const start = editor.selectionStart;
                const end = editor.selectionEnd;
                this.form.expression = `${this.form.expression.slice(0, start)}${token}${this.form.expression.slice(end)}`;
                this.$nextTick(() => {
                    editor.focus();
                    editor.setSelectionRange(start + token.length, start + token.length);
                });
            });
        },
        applyTemplate(kind) {
            const aliases = this.form.inputRows.map(row => row.alias).filter(Boolean);
            if (!aliases.length) {
                this.messageSuccess = false;
                this.message = '请先添加输入字段';
                return;
            }
            const first = `col("${aliases[0]}")`;
            if (['ratio', 'coalesce'].includes(kind) && aliases.length < 2) {
                this.messageSuccess = false;
                this.message = '这个模板需要两个输入字段';
                return;
            }
            const second = aliases[1] ? `col("${aliases[1]}")` : first;
            const templates = {
                inverse: `round(safe_div(100.0, ${first}), 2)`,
                ratio: `safe_div(${first}, ${second})`,
                coalesce: `coalesce(${first}, ${second})`,
                log: `log1p(${first})`,
                rolling_mean: `round(rolling_mean(${first}, 3, 2), 2)`,
                cagr: `round(cagr(${first}, 5) * 100.0, 2)`,
            };
            this.form.expression = templates[kind];
            this.message = '';
        },
        buildPayload() {
            const inputs = {};
            const optionalInputs = [];
            this.form.inputRows.forEach(row => {
                const alias = row.alias.trim();
                if (!alias || !row.semanticId) throw new Error('每个输入都需要别名和原生字段');
                if (Object.prototype.hasOwnProperty.call(inputs, alias)) throw new Error(`输入别名重复：${alias}`);
                inputs[alias] = row.semanticId;
                if (row.optional) optionalInputs.push(alias);
            });
            return {
                schema_version: 1,
                id: this.form.id,
                name: this.form.name,
                description: this.form.description,
                category: this.form.category,
                tags: this.form.tagsText.split(',').map(value => value.trim()).filter(Boolean),
                type: 'cross_section',
                grain: 'security_date',
                engine: 'polars',
                execution: {
                    mode: Object.values(inputs).some(value => value.startsWith('financial.')) ? 'point_in_time' : 'row',
                    frequency: 'annual',
                },
                inputs,
                optional_inputs: optionalInputs,
                expression: this.form.expression,
                output: { dtype: 'float64', unit: this.form.unit, direction: this.form.direction },
                policies: { null: 'propagate', point_in_time: this.form.pointInTimeSafe ? 'strict' : 'latest_only', enabled: true },
            };
        },
        async validateForm() {
            this.saving = true;
            try {
                const result = await apiFetch('/api/factors/validate', { method: 'POST', body: JSON.stringify(this.buildPayload()) });
                this.messageSuccess = true;
                this.message = `验证通过 · 定义哈希 ${result.definition_hash}`;
            } catch (error) {
                this.messageSuccess = false;
                this.message = `验证失败：${error.message}`;
            } finally {
                this.saving = false;
            }
        },
        async saveFactor() {
            this.saving = true;
            try {
                const payload = this.buildPayload();
                const path = this.isCreating ? '/api/factors' : `/api/factors/${encodeURIComponent(this.selected.id)}`;
                const method = this.isCreating ? 'POST' : 'PUT';
                const result = await apiFetch(path, { method, body: JSON.stringify(payload) });
                this.messageSuccess = true;
                this.message = '因子定义已保存';
                this.editMode = false;
                this.isCreating = false;
                await this.loadCatalog(result.id || payload.id);
                if (result.materialization_job) {
                    this.monitorJob(result.materialization_job, payload.id);
                } else {
                    this.jobNotice = {
                        status: 'completed',
                        title: '定义已保存',
                        message: '当前数据源缺少精确输入或历史指标，未启动自动计算。',
                        percent: 100,
                    };
                }
            } catch (error) {
                this.messageSuccess = false;
                this.message = `保存失败：${error.message}`;
            } finally {
                this.saving = false;
            }
        },
        async materializeSelected() {
            if (!this.selected?.editable) return;
            this.saving = true;
            try {
                const job = await apiFetch(`/api/factors/${encodeURIComponent(this.selected.id)}/materialize`, { method: 'POST' });
                this.monitorJob(job, this.selected.id);
                await this.loadCatalog(this.selected.id);
            } catch (error) {
                this.jobNotice = { status: 'failed', title: '无法开始计算', message: error.message, percent: 0 };
            } finally {
                this.saving = false;
            }
        },
        async prepareSelected() {
            if (!this.selected?.editable) return;
            this.saving = true;
            try {
                const job = await apiFetch(`/api/factors/${encodeURIComponent(this.selected.id)}/prepare`, { method: 'POST' });
                this.monitorJob(job, this.selected.id, 'dependency');
                await this.loadCatalog(this.selected.id);
            } catch (error) {
                this.jobNotice = { status: 'failed', title: '无法补齐依赖', message: error.message, percent: 0 };
            } finally {
                this.saving = false;
            }
        },
        monitorJob(job, factorId, mode = 'factor') {
            if (this.jobPollTimer) clearTimeout(this.jobPollTimer);
            const updateNotice = current => {
                this.jobNotice = {
                    status: current.status,
                    title: mode === 'dependency'
                        ? (current.status === 'completed' ? '依赖数据已补齐' : current.status === 'failed' ? '依赖数据补齐失败' : '正在补齐因子依赖')
                        : (current.status === 'completed' ? '因子计算完成' : current.status === 'failed' ? '因子计算失败' : '因子已进入计算队列'),
                    message: current.error || current.message || '等待执行',
                    percent: current.percent || 0,
                };
            };
            const poll = async current => {
                updateNotice(current);
                if (['completed', 'failed', 'cancelled', 'interrupted'].includes(current.status)) {
                    await this.loadCatalog(factorId);
                    if (mode === 'dependency' && current.status === 'completed') {
                        this.jobNotice = {
                            status: 'queued',
                            title: '依赖已就绪，等待自动计算',
                            message: '系统正在续接因子物化任务。',
                            percent: 100,
                        };
                        this.pollFactorMaterialization(factorId);
                    }
                    return;
                }
                this.jobPollTimer = setTimeout(async () => {
                    try {
                        const next = await apiFetch(`/api/datasources/jobs/${current.id}`);
                        await poll(next);
                    } catch (error) {
                        this.jobNotice = { status: 'failed', title: '任务状态读取失败', message: error.message, percent: 0 };
                    }
                }, 1000);
            };
            poll(job);
        },
        pollFactorMaterialization(factorId) {
            if (this.jobPollTimer) clearTimeout(this.jobPollTimer);
            let attempts = 0;
            const poll = async () => {
                try {
                    attempts += 1;
                    await this.loadCatalog(factorId);
                    const state = this.selected?.materialization || {};
                    if (state.usable) {
                        this.jobNotice = { status: 'completed', title: '因子计算完成', message: '已可用于截面筛选和历史验证。', percent: 100 };
                        return;
                    }
                    if (state.status === 'failed') {
                        this.jobNotice = { status: 'failed', title: '因子计算失败', message: state.error || '请查看数据任务详情。', percent: 0 };
                        return;
                    }
                    if (attempts > 1 && this.selected?.materialization_blockers?.length && !['pending', 'computing'].includes(state.status)) {
                        this.jobNotice = { status: 'failed', title: '依赖仍未就绪', message: this.selected.materialization_blockers.join('；'), percent: 0 };
                        return;
                    }
                    this.jobPollTimer = setTimeout(poll, 1000);
                } catch (error) {
                    this.jobNotice = { status: 'failed', title: '因子状态读取失败', message: error.message, percent: 0 };
                }
            };
            this.jobPollTimer = setTimeout(poll, 500);
        },
    },

    mounted() {
        this.loadCatalog();
    },
    beforeUnmount() {
        if (this.jobPollTimer) clearTimeout(this.jobPollTimer);
    },
};
