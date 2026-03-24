/**
 * Operators management page component.
 *
 * Browse, view, edit, and create analysis operators.
 */
const OperatorsPage = {
    template: `
<div class="page-operators">
    <!-- Top: Category Tabs -->
    <div class="card">
        <h2>算子管理</h2>
        <div class="category-tabs">
            <button
                class="category-tab"
                :class="{ active: selectedCategory === '' }"
                @click="selectedCategory = ''"
            >全部 ({{ totalCount }})</button>
            <button
                v-for="cat in categories"
                :key="cat"
                class="category-tab"
                :class="{ active: selectedCategory === cat }"
                @click="selectedCategory = cat"
            >{{ cat }} ({{ (operatorsByCategory[cat] || []).length }})</button>
        </div>
    </div>

    <!-- Split Layout -->
    <div class="operators-split">
        <!-- Left: Operator List -->
        <div class="card operators-list-panel">
            <div class="operators-search">
                <input
                    type="text"
                    v-model="searchText"
                    placeholder="搜索算子..."
                />
            </div>
            <div class="operators-list">
                <div
                    v-for="op in filteredOperators"
                    :key="op.id"
                    class="operator-list-item"
                    :class="{ active: selectedOperator && selectedOperator.id === op.id }"
                    @click="selectOperator(op)"
                >
                    <div class="op-item-name">{{ op.name }}</div>
                    <div class="op-item-meta">
                        <span class="op-item-id">{{ op.id }}</span>
                        <span class="op-item-cat">{{ op.category }}</span>
                    </div>
                </div>
                <div class="empty-state" v-if="filteredOperators.length === 0">
                    暂无匹配算子
                </div>
            </div>
            <div class="operators-list-footer">
                <button class="btn btn-primary" @click="showCreateForm">+ 新建算子</button>
            </div>
        </div>

        <!-- Right: Detail Panel -->
        <div class="card operators-detail-panel" v-if="detailOperator">
            <div v-if="!editMode">
                <!-- View Mode -->
                <div class="op-detail-header">
                    <h2>{{ detailOperator.name }}</h2>
                    <button class="btn btn-secondary" @click="enterEditMode">编辑</button>
                </div>

                <div class="op-detail-fields">
                    <div class="op-field-row">
                        <span class="op-field-label">ID</span>
                        <span class="op-field-value mono">{{ detailOperator.id }}</span>
                    </div>
                    <div class="op-field-row">
                        <span class="op-field-label">分类</span>
                        <span class="op-field-value">{{ detailOperator.category }}</span>
                    </div>
                    <div class="op-field-row">
                        <span class="op-field-label">标签</span>
                        <span class="op-field-value">
                            <span class="op-tag" v-for="t in detailOperator.tags" :key="t">{{ t }}</span>
                            <span v-if="!detailOperator.tags || detailOperator.tags.length === 0" class="text-muted">无</span>
                        </span>
                    </div>
                    <div class="op-field-row" v-if="detailOperator.gate && Object.keys(detailOperator.gate).length > 0">
                        <span class="op-field-label">门控</span>
                        <div class="op-field-value">
                            <span v-if="detailOperator.gate.exclude_industry" class="gate-tag gate-exclude"
                                v-for="ind in detailOperator.gate.exclude_industry" :key="'ex-'+ind">
                                排除: {{ ind }}
                            </span>
                            <span v-if="detailOperator.gate.only_industry" class="gate-tag gate-only"
                                v-for="ind in detailOperator.gate.only_industry" :key="'only-'+ind">
                                专用: {{ ind }}
                            </span>
                        </div>
                    </div>
                    <div class="op-field-row" v-if="detailOperator.data_needed && detailOperator.data_needed.length > 0">
                        <span class="op-field-label">数据依赖</span>
                        <div class="op-field-value">
                            <span class="op-tag data-tag" v-for="d in detailOperator.data_needed" :key="d" :title="d">
                                {{ getDataSourceName(d) }}
                            </span>
                        </div>
                    </div>
                    <div style="display:none" v-if="false">
                        <span class="op-field-label">数据依赖(旧)</span>
                        <span class="op-field-value">
                            <span class="op-tag" v-for="d in detailOperator.data_needed" :key="d">{{ d }}</span>
                        </span>
                    </div>
                </div>

                <div class="op-detail-outputs" v-if="detailOperator.outputs && detailOperator.outputs.length > 0">
                    <h3>输出字段</h3>
                    <table class="op-outputs-table">
                        <thead>
                            <tr>
                                <th>字段名</th>
                                <th>类型</th>
                                <th>说明</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="o in detailOperator.outputs" :key="o.field">
                                <td class="mono">{{ o.field }}</td>
                                <td>{{ o.type }}</td>
                                <td>{{ o.desc }}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>

                <div class="op-detail-content">
                    <h3>分析指令</h3>
                    <pre class="op-content-text">{{ detailOperator.content }}</pre>
                </div>
            </div>

            <div v-else>
                <!-- Edit Mode -->
                <div class="op-detail-header">
                    <h2>{{ isCreating ? '新建算子' : '编辑: ' + editForm.name }}</h2>
                    <div class="op-edit-actions">
                        <button class="btn btn-primary" @click="saveOperator" :disabled="saving">
                            {{ saving ? '保存中...' : '保存' }}
                        </button>
                        <button class="btn btn-secondary" @click="cancelEdit">取消</button>
                    </div>
                </div>

                <div class="op-edit-form">
                    <div class="setting-item" v-if="isCreating">
                        <label>ID</label>
                        <input type="text" v-model="editForm.id" placeholder="如 debt_structure" />
                    </div>
                    <div class="setting-item">
                        <label>名称</label>
                        <input type="text" v-model="editForm.name" placeholder="算子名称" />
                    </div>
                    <div class="setting-item" v-if="isCreating">
                        <label>分类</label>
                        <select v-model="editForm.category">
                            <option value="">选择分类...</option>
                            <option v-for="cat in categories" :key="cat" :value="cat">{{ cat }}</option>
                            <option value="__new__">+ 新分类</option>
                        </select>
                        <input
                            v-if="editForm.category === '__new__'"
                            type="text"
                            v-model="editForm.newCategory"
                            placeholder="输入新分类名称"
                            style="margin-top: 6px;"
                        />
                    </div>
                    <div class="setting-item">
                        <label>标签 (逗号分隔)</label>
                        <input type="text" v-model="editForm.tagsText" placeholder="fundamental, debt" />
                    </div>
                    <div class="setting-item">
                        <label>数据依赖（勾选算子所需的数据源）</label>
                        <div class="data-need-grid" v-if="availableDataSources.length > 0">
                            <label
                                class="data-need-item"
                                v-for="ds in availableDataSources"
                                :key="ds.id"
                                :title="ds.description"
                            >
                                <input
                                    type="checkbox"
                                    :value="ds.id"
                                    :checked="editForm.dataNeedSet.has(ds.id)"
                                    @change="toggleDataNeed(ds.id, $event)"
                                />
                                <span class="data-need-name">{{ ds.name }}</span>
                                <span class="data-need-cat">{{ ds.category }}</span>
                            </label>
                        </div>
                        <div v-else class="setting-hint">加载数据源列表中...</div>
                    </div>

                    <div class="setting-item">
                        <label>输出字段 (每行一个: 字段名|类型|说明)</label>
                        <textarea
                            class="op-edit-textarea op-edit-outputs"
                            v-model="editForm.outputsText"
                            placeholder="interest_bearing_debt|float|有息负债总额&#10;zero_interest_debt|bool|是否无有息负债"
                            rows="4"
                        ></textarea>
                    </div>

                    <div class="setting-item">
                        <label>行业门控</label>
                        <div class="gate-section">
                            <div class="gate-row">
                                <span class="gate-label">排除行业（不适用于这些行业）</span>
                                <div class="gate-industry-grid">
                                    <label class="gate-ind-item" v-for="ind in industryList" :key="'ex-'+ind">
                                        <input type="checkbox" :value="ind"
                                            :checked="editForm.gateExclude.includes(ind)"
                                            @change="toggleGateExclude(ind, $event)" />
                                        <span>{{ ind }}</span>
                                    </label>
                                </div>
                            </div>
                            <div class="gate-row" style="margin-top:8px;">
                                <span class="gate-label">专用行业（仅对这些行业启用，空=通用）</span>
                                <div class="gate-industry-grid">
                                    <label class="gate-ind-item" v-for="ind in industryList" :key="'only-'+ind">
                                        <input type="checkbox" :value="ind"
                                            :checked="editForm.gateOnly.includes(ind)"
                                            @change="toggleGateOnly(ind, $event)" />
                                        <span>{{ ind }}</span>
                                    </label>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div class="setting-item">
                        <label>分析指令 (Markdown)</label>
                        <textarea
                            class="op-edit-textarea op-edit-content"
                            v-model="editForm.content"
                            placeholder="算子的 Markdown 正文..."
                            rows="16"
                        ></textarea>
                    </div>
                </div>

                <div class="save-status" v-if="saveMessage" :class="saveSuccess ? 'success' : 'error'">
                    {{ saveMessage }}
                </div>
            </div>
        </div>

        <!-- Empty Detail -->
        <div class="card operators-detail-panel" v-else>
            <div class="empty-state">
                选择一个算子查看详情，或点击 "新建算子" 创建
            </div>
        </div>
    </div>
</div>
    `,

    data() {
        return {
            categories: [],
            operatorsByCategory: {},
            totalCount: 0,
            selectedCategory: '',
            searchText: '',
            selectedOperator: null,
            detailOperator: null,
            editMode: false,
            isCreating: false,
            editForm: {
                id: '',
                name: '',
                category: '',
                newCategory: '',
                tagsText: '',
                dataNeedText: '',
                dataNeedSet: new Set(),
                gateExclude: [],
                gateOnly: [],
                outputsText: '',
                content: '',
            },
            saving: false,
            saveMessage: '',
            saveSuccess: false,
            availableDataSources: [],
            dataSourceMap: {},
            industryList: ['银行', '保险', '证券', '多元金融', '房地产', '煤炭', '钢铁', '石油', '化工', '公用事业', '食品饮料', '家电', '医药', '汽车', '科技'],
        };
    },

    computed: {
        allOperators() {
            if (this.selectedCategory) {
                return this.operatorsByCategory[this.selectedCategory] || [];
            }
            let all = [];
            for (const cat of this.categories) {
                all = all.concat(this.operatorsByCategory[cat] || []);
            }
            return all;
        },

        filteredOperators() {
            if (!this.searchText) return this.allOperators;
            const q = this.searchText.toLowerCase();
            return this.allOperators.filter(op =>
                op.id.toLowerCase().includes(q) ||
                op.name.toLowerCase().includes(q) ||
                (op.tags || []).some(t => t.toLowerCase().includes(q))
            );
        },
    },

    created() {
        this.loadOperators();
        this.loadDataSources();
    },

    methods: {
        async loadDataSources() {
            try {
                const resp = await fetch('/api/datasources');
                const data = await resp.json();
                this.availableDataSources = data.all || [];
                this.dataSourceMap = {};
                for (const ds of this.availableDataSources) {
                    this.dataSourceMap[ds.id] = ds.name;
                }
            } catch (e) {
                console.error('Failed to load data sources:', e);
            }
        },

        getDataSourceName(id) {
            return this.dataSourceMap[id] || id;
        },

        buildGate() {
            const gate = {};
            if (this.editForm.gateExclude.length > 0) gate.exclude_industry = this.editForm.gateExclude;
            if (this.editForm.gateOnly.length > 0) gate.only_industry = this.editForm.gateOnly;
            return Object.keys(gate).length > 0 ? gate : {};
        },

        toggleGateExclude(ind, event) {
            if (event.target.checked) {
                if (!this.editForm.gateExclude.includes(ind)) this.editForm.gateExclude.push(ind);
            } else {
                this.editForm.gateExclude = this.editForm.gateExclude.filter(i => i !== ind);
            }
        },

        toggleGateOnly(ind, event) {
            if (event.target.checked) {
                if (!this.editForm.gateOnly.includes(ind)) this.editForm.gateOnly.push(ind);
            } else {
                this.editForm.gateOnly = this.editForm.gateOnly.filter(i => i !== ind);
            }
        },

        toggleDataNeed(dsId, event) {
            if (event.target.checked) {
                this.editForm.dataNeedSet.add(dsId);
            } else {
                this.editForm.dataNeedSet.delete(dsId);
            }
            // Sync to text field for backward compat
            this.editForm.dataNeedText = Array.from(this.editForm.dataNeedSet).join(', ');
        },

        async loadOperators() {
            try {
                const data = await apiFetch('/api/operators');
                this.categories = data.categories || [];
                this.operatorsByCategory = data.operators || {};
                this.totalCount = data.total || 0;
            } catch (e) {
                console.error('Failed to load operators:', e);
            }
        },

        async selectOperator(op) {
            this.selectedOperator = op;
            this.editMode = false;
            this.isCreating = false;
            try {
                this.detailOperator = await apiFetch(`/api/operators/${op.id}`);
            } catch (e) {
                console.error('Failed to load operator detail:', e);
            }
        },

        enterEditMode() {
            if (!this.detailOperator) return;
            this.editMode = true;
            this.isCreating = false;
            const op = this.detailOperator;
            this.editForm = {
                id: op.id,
                name: op.name,
                category: op.category,
                newCategory: '',
                tagsText: (op.tags || []).join(', '),
                dataNeedText: (op.data_needed || []).join(', '),
                dataNeedSet: new Set(op.data_needed || []),
                gateExclude: (op.gate?.exclude_industry || []).slice(),
                gateOnly: (op.gate?.only_industry || []).slice(),
                outputsText: (op.outputs || []).map(o =>
                    `${o.field}|${o.type}|${o.desc || ''}`
                ).join('\n'),
                content: op.content || '',
            };
        },

        showCreateForm() {
            this.editMode = true;
            this.isCreating = true;
            this.selectedOperator = null;
            this.detailOperator = { id: '', name: '新建算子' };
            this.editForm = {
                id: '',
                name: '',
                category: '',
                newCategory: '',
                tagsText: '',
                dataNeedText: '',
                dataNeedSet: new Set(),
                gateExclude: [],
                gateOnly: [],
                outputsText: '',
                content: '',
            };
        },

        cancelEdit() {
            this.editMode = false;
            if (this.isCreating) {
                this.isCreating = false;
                this.detailOperator = null;
                this.selectedOperator = null;
            }
        },

        parseOutputs(text) {
            if (!text.trim()) return [];
            return text.trim().split('\n').map(line => {
                const parts = line.split('|');
                return {
                    field: (parts[0] || '').trim(),
                    type: (parts[1] || 'str').trim(),
                    desc: (parts[2] || '').trim(),
                };
            }).filter(o => o.field);
        },

        parseTags(text) {
            if (!text.trim()) return [];
            return text.split(',').map(s => s.trim()).filter(Boolean);
        },

        async saveOperator() {
            this.saving = true;
            this.saveMessage = '';

            try {
                const outputs = this.parseOutputs(this.editForm.outputsText);
                const tags = this.parseTags(this.editForm.tagsText);
                const dataNeed = this.editForm.dataNeedSet.size > 0
                    ? Array.from(this.editForm.dataNeedSet)
                    : this.parseTags(this.editForm.dataNeedText);

                if (this.isCreating) {
                    const category = this.editForm.category === '__new__'
                        ? this.editForm.newCategory
                        : this.editForm.category;

                    if (!this.editForm.id || !this.editForm.name || !category) {
                        throw new Error('ID、名称和分类为必填项');
                    }

                    const result = await apiFetch('/api/operators', {
                        method: 'POST',
                        body: JSON.stringify({
                            id: this.editForm.id,
                            name: this.editForm.name,
                            category: category,
                            tags: tags,
                            data_needed: dataNeed,
                            gate: this.buildGate(),
                            outputs: outputs,
                            content: this.editForm.content,
                        }),
                    });
                    this.saveSuccess = true;
                    this.saveMessage = '算子创建成功';
                    this.isCreating = false;
                    this.editMode = false;
                    this.detailOperator = result;
                    this.selectedOperator = result;
                } else {
                    const result = await apiFetch(`/api/operators/${this.editForm.id}`, {
                        method: 'PUT',
                        body: JSON.stringify({
                            name: this.editForm.name,
                            tags: tags,
                            data_needed: dataNeed,
                            gate: this.buildGate(),
                            outputs: outputs,
                            content: this.editForm.content,
                        }),
                    });
                    this.saveSuccess = true;
                    this.saveMessage = '保存成功';
                    this.detailOperator = result;
                    this.editMode = false;
                }

                // Reload list
                await this.loadOperators();
            } catch (e) {
                this.saveSuccess = false;
                this.saveMessage = `保存失败: ${e.message}`;
            } finally {
                this.saving = false;
                setTimeout(() => { this.saveMessage = ''; }, 3000);
            }
        },
    },
};
