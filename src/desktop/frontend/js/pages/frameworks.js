/**
 * Framework orchestration page component.
 *
 * View and edit strategy frameworks (chapters + operators + synthesis).
 */
const FrameworksPage = {
    template: `
<div class="page-frameworks">
    <workspace-page-header eyebrow="基础设施 · 研究编排" title="研究框架" description="按章节和依赖关系编排算子，形成可重复执行的研究路径。">
        <template #meta>
            <div class="page-header-control page-header-control-inline fw-selector">
                <label>当前框架</label>
                <select v-model="selectedFramework" @change="loadFramework">
                    <option value="" disabled>选择框架...</option>
                    <option v-for="fw in frameworks" :key="fw.name" :value="fw.name">
                        {{ fw.display_name }} ({{ fw.chapter_count }}章, {{ fw.operator_count }}算子)
                    </option>
                </select>
            </div>
        </template>
        <template #actions>
            <button class="btn btn-secondary btn-small" @click="showNewFramework">+ 新建框架</button>
            <button class="btn btn-primary btn-small" @click="saveFramework" :disabled="!frameworkData || saving || !!thresholdError || missingOperatorIds.length > 0">{{ saving ? '保存中...' : '保存框架' }}</button>
        </template>
    </workspace-page-header>
    <div class="save-status" v-if="saveMessage" :class="saveSuccess ? 'success' : 'error'">{{ saveMessage }}</div>

    <!-- New Framework Form -->
    <div class="card" v-if="creatingNew">
        <h2>新建框架</h2>
        <div class="op-edit-form">
            <div class="setting-item">
                <label>目录名 (英文, 如 my_strategy)</label>
                <input type="text" v-model="newForm.name" placeholder="strategy_name" />
            </div>
            <div class="setting-item">
                <label>显示名称</label>
                <input type="text" v-model="newForm.display_name" placeholder="我的投资策略" />
            </div>
            <div class="setting-item">
                <label>版本</label>
                <input type="text" v-model="newForm.version" placeholder="1.0" />
            </div>
            <div class="setting-item">
                <label>分析师角色</label>
                <input type="text" v-model="newForm.analyst_role" placeholder="投资分析师" />
            </div>
            <div class="setting-item">
                <label>算子库版本</label>
                <select v-model="newForm.operators_dir"><option v-for="version in operatorVersions" :key="version.id" :value="version.operators_dir">{{ version.label }}</option></select>
            </div>
        </div>
        <div style="margin-top: 12px; display: flex; gap: 8px;">
            <button class="btn btn-primary" @click="createFramework" :disabled="!newForm.name || !newForm.display_name">创建</button>
            <button class="btn btn-secondary" @click="creatingNew = false">取消</button>
        </div>
    </div>

    <!-- Main Editor (only shown when framework loaded) -->
    <div v-if="frameworkData">
        <nav class="fw-stage-switcher" aria-label="研究框架配置步骤">
            <button
                type="button"
                class="fw-stage-button"
                :class="{ active: activeStage === 'dag' }"
                :aria-current="activeStage === 'dag' ? 'step' : null"
                @click="activeStage = 'dag'"
            >
                <span class="fw-stage-index">01</span>
                <span class="fw-stage-copy"><strong>章节 DAG</strong><small>章节、依赖与算子编排</small></span>
            </button>
            <button
                type="button"
                class="fw-stage-button"
                :class="{ active: activeStage === 'synthesis' }"
                :aria-current="activeStage === 'synthesis' ? 'step' : null"
                @click="activeStage = 'synthesis'"
            >
                <span class="fw-stage-index">02</span>
                <span class="fw-stage-copy"><strong>综合研判</strong><small>决策、评分与输出契约</small></span>
            </button>
            <button
                type="button"
                class="fw-stage-button"
                :class="{ active: activeStage === 'preview' }"
                :aria-current="activeStage === 'preview' ? 'step' : null"
                @click="activeStage = 'preview'"
            >
                <span class="fw-stage-index">03</span>
                <span class="fw-stage-copy"><strong>流程预览</strong><small>核对最终执行路径</small></span>
            </button>
        </nav>

        <div class="card fw-basic-settings" v-show="activeStage === 'dag'">
            <div class="fw-basic-settings-head"><div><h3>框架基础设置</h3><p>这些字段会直接进入 Agent 提示词和算子解析过程。</p></div><span class="method-badge">{{ frameworkData.operators_dir }}</span></div>
            <div class="fw-basic-settings-grid">
                <div class="setting-item"><label>显示名称</label><input type="text" v-model="frameworkData.display_name" /></div>
                <div class="setting-item"><label>版本</label><input type="text" v-model="frameworkData.version" /></div>
                <div class="setting-item"><label>Agent 框架名称</label><input type="text" v-model="frameworkData.version_string" placeholder="用于 Agent 提示词" /></div>
                <div class="setting-item"><label>分析师角色</label><input type="text" v-model="frameworkData.analyst_role" placeholder="投资分析师" /></div>
                <div class="setting-item"><label>算子库版本</label><select v-model="frameworkData.operators_dir" @change="changeOperatorLibrary"><option v-for="version in operatorVersions" :key="version.id" :value="version.operators_dir">{{ version.label }} · {{ version.operator_count }} 个</option></select><small class="setting-hint">框架内所有算子统一从该版本解析，避免同名 ID 歧义</small></div>
            </div>
            <div class="error-msg" v-if="missingOperatorIds.length">当前版本缺少算子：{{ missingOperatorIds.join('、') }}。请切回原版本或替换后再保存。</div>
        </div>

        <section class="card fw-dag-overview" v-show="activeStage === 'dag'">
            <div class="fw-dag-overview-head">
                <div><h3>章节路径</h3><p>按依赖层级浏览章节；选择节点后在下方编辑当前章节。</p></div>
                <span>{{ frameworkData.chapters.length }} 个章节</span>
            </div>
            <div class="fw-dag-scroll">
                <div class="fw-dag-layers">
                    <template v-for="(layer, layerIndex) in dagLayers" :key="layer.level">
                        <div class="fw-dag-layer">
                            <span class="fw-dag-layer-label">阶段 {{ layerIndex + 1 }}</span>
                            <button
                                v-for="item in layer.items"
                                :key="item.chapter.id"
                                type="button"
                                class="fw-dag-node"
                                :class="{ active: selectedChapterId === item.chapter.id, warning: chapterMissingOperators(item.chapter).length > 0 }"
                                :aria-pressed="selectedChapterId === item.chapter.id"
                                @click="selectedChapterId = item.chapter.id"
                            >
                                <span class="fw-dag-node-top"><b>{{ String(item.chapter.chapter).padStart(2, '0') }}</b><em>{{ item.chapter.operators.length }} 个算子</em></span>
                                <strong>{{ item.chapter.title || '未命名章节' }}</strong>
                                <small v-if="item.chapter.dependencies.length">依赖 {{ item.chapter.dependencies.map(getChapterNumber).join('、') }}</small>
                                <small v-else>起始章节</small>
                                <i v-if="chapterMissingOperators(item.chapter).length">缺少 {{ chapterMissingOperators(item.chapter).length }} 个算子</i>
                            </button>
                        </div>
                        <span class="fw-dag-layer-arrow" v-if="layerIndex < dagLayers.length - 1" aria-hidden="true">→</span>
                    </template>
                    <button type="button" class="fw-dag-add-node" @click="addChapter"><b>＋</b><span>新增章节</span></button>
                </div>
            </div>
        </section>

        <div class="fw-editor-layout" :class="'stage-' + activeStage">
        <!-- Chapter Editor -->
        <div class="fw-chapters-panel">
            <!-- Selected chapter -->
            <div
                v-if="activeStage === 'dag' && selectedChapter"
                :key="selectedChapter.id"
                class="card fw-chapter-card fw-chapter-card-active"
            >
                <div class="fw-chapter-header">
                    <div class="fw-chapter-badge">{{ selectedChapter.chapter }}</div>
                    <div class="fw-chapter-info">
                        <input
                            type="text"
                            v-model="selectedChapter.title"
                            class="fw-chapter-title-input"
                            placeholder="章节标题"
                        />
                        <div class="fw-chapter-id">{{ selectedChapter.id }}</div>
                    </div>
                    <button class="btn btn-small btn-danger" @click="removeChapter(selectedChapterIndex)">删除</button>
                </div>

                <!-- Dependencies -->
                <div class="fw-chapter-deps">
                    <label>依赖章节（本章分析将基于所选章节的结论）:</label>
                    <div class="fw-deps-checkboxes" v-if="getPriorChapters(selectedChapterIndex).length > 0">
                        <label
                            class="fw-dep-checkbox"
                            v-for="other in getPriorChapters(selectedChapterIndex)"
                            :key="other.id"
                        >
                            <input
                                type="checkbox"
                                :value="other.id"
                                :checked="selectedChapter.dependencies.includes(other.id)"
                                @change="toggleDep(selectedChapter, other.id, $event)"
                            />
                            <span class="fw-dep-label">第{{ other.chapter }}章 {{ other.title }}</span>
                        </label>
                    </div>
                    <div class="fw-deps-none" v-else>
                        首个章节，无可依赖项
                    </div>
                </div>

                <!-- Operators in chapter -->
                <div class="fw-chapter-ops">
                    <label>算子列表:</label>
                    <div class="fw-chapter-op-list">
                        <div v-for="(opId, opIdx) in selectedChapter.operators" :key="opId + '-' + opIdx" class="fw-chapter-op">
                            <span class="flow-op" :class="{ 'flow-op-skipped': !getOpMeta(opId) }">{{ getOpName(opId) }}</span>
                            <button class="fw-op-remove" @click="removeOpFromChapter(selectedChapterIndex, opIdx)" title="移除">&times;</button>
                        </div>
                        <div class="fw-chapter-op-drop" v-if="selectedChapter.operators.length === 0">
                            拖拽算子到此处
                        </div>
                    </div>
                    <!-- Manual add -->
                    <div class="fw-chapter-add-op">
                        <select v-model="addOpSelections[selectedChapterIndex]">
                            <option value="">+ 添加算子...</option>
                            <optgroup v-for="category in opCategories" :key="category" :label="category">
                                <option v-for="op in availableOps[category] || []" :key="op.id" :value="op.id">{{ op.name }} ({{ op.id }})</option>
                            </optgroup>
                        </select>
                        <button
                            class="btn btn-small"
                            v-if="addOpSelections[selectedChapterIndex]"
                            @click="addOpToChapter(selectedChapterIndex)"
                        >添加</button>
                    </div>
                </div>

                <details class="fw-chapter-contract" v-if="chapterOutputs(selectedChapter).length || chapterDataNeeds(selectedChapter).length">
                    <summary>实际字段契约 · {{ chapterOutputs(selectedChapter).length }} 个输出字段 · {{ chapterDataNeeds(selectedChapter).length }} 项数据依赖</summary>
                    <div class="fw-contract-grid">
                        <div><strong>输出字段</strong><span v-for="item in chapterOutputs(selectedChapter)" :key="item.field"><code>{{ item.field }}</code><small>{{ item.type }} · {{ item.source_operator }}</small></span></div>
                        <div><strong>数据依赖</strong><span v-for="item in chapterDataNeeds(selectedChapter)" :key="item">{{ item }}</span></div>
                    </div>
                </details>
            </div>

            <div class="card fw-chapter-empty" v-else-if="activeStage === 'dag'">
                <strong>还没有章节</strong><span>从上方新增第一个章节开始编排。</span>
            </div>

            <!-- Synthesis Config -->
            <div class="card fw-synthesis-card" v-show="activeStage === 'synthesis'">
                <h3>综合研判配置</h3>

                <!-- Decision Thresholds -->
                <div class="syn-section">
                    <h4>决策边界</h4>
                    <div class="syn-thresholds">
                        <div class="syn-threshold-item">
                            <span class="syn-th-label buy">买入</span>
                            <span>≥</span>
                            <input type="number" v-model.number="synthesisThresholds.buy" min="0" max="100" class="syn-th-input" />
                            <span>分</span>
                        </div>
                        <div class="syn-threshold-item">
                            <span class="syn-th-label watch">观望</span>
                            <span>{{ synthesisThresholds.avoid + 1 }} - {{ synthesisThresholds.buy - 1 }}</span>
                            <span>分</span>
                        </div>
                        <div class="syn-threshold-item">
                            <span class="syn-th-label avoid">回避</span>
                            <span>≤</span>
                            <input type="number" v-model.number="synthesisThresholds.avoid" min="0" max="100" class="syn-th-input" />
                            <span>分</span>
                        </div>
                    </div>
                    <div class="error-msg" v-if="thresholdError">{{ thresholdError }}</div>
                </div>

                <!-- Synthesis output contract -->
                <div class="syn-section">
                    <h4>综合输出契约 <span class="syn-count">Agent 最终 JSON</span></h4>
                    <div class="syn-public-fields"><span v-for="item in publicSynthesisFields" :key="item.field"><strong>{{ item.field }}</strong><small>公共必填</small></span></div>
                    <div class="syn-field-list">
                        <div class="syn-field-row" v-for="(item, idx) in synthesisFields" :key="idx">
                            <input type="text" v-model="item.field" placeholder="字段名" />
                            <select v-model="item.type"><option value="str">文本</option><option value="int">整数</option><option value="float">数值</option><option value="bool">布尔</option><option value="list">列表</option></select>
                            <input type="text" v-model="item.desc" placeholder="字段口径和允许值" />
                            <button class="btn-icon" @click="synthesisFields.splice(idx, 1)" title="删除">✕</button>
                        </div>
                        <button class="btn btn-small btn-secondary" @click="addSynthesisField">+ 添加自定义输出字段</button>
                    </div>
                </div>

                <!-- Thinking Steps -->
                <div class="syn-section">
                    <h4>
                        思考步骤
                        <span class="syn-count">{{ thinkingSteps.length }} 步</span>
                    </h4>
                    <div class="syn-steps">
                        <div class="syn-step" v-for="(step, idx) in thinkingSteps" :key="idx">
                            <div class="syn-step-header">
                                <span class="syn-step-num">{{ idx + 1 }}</span>
                                <input
                                    type="text"
                                    v-model="step.step"
                                    class="syn-step-name"
                                    placeholder="步骤名称"
                                />
                                <button class="btn-icon" @click="removeThinkingStep(idx)" title="删除">✕</button>
                            </div>
                            <textarea
                                v-model="step.instruction"
                                class="syn-step-instruction"
                                placeholder="步骤指令（告诉 AI 这一步具体怎么思考）"
                                rows="3"
                            ></textarea>
                        </div>
                        <button class="btn btn-small btn-secondary" @click="addThinkingStep">+ 添加步骤</button>
                    </div>
                </div>

                <!-- Scoring Rubric -->
                <div class="syn-section">
                    <h4>
                        评分锚点
                        <span class="syn-count">校准参考，不是公式</span>
                    </h4>
                    <div class="syn-rubric-mode"><button :class="{ active: rubricMode === 'range' }" @click="changeRubricMode('range')">分数区间</button><button :class="{ active: rubricMode === 'dimension' }" @click="changeRubricMode('dimension')">维度权重</button></div>
                    <div class="syn-rubric" v-if="rubricMode === 'range'">
                        <div class="syn-rubric-item" v-for="(item, idx) in scoringRubric" :key="idx">
                            <input
                                type="text"
                                v-model="item.range"
                                class="syn-rubric-range"
                                placeholder="85-100"
                            />
                            <span>分：</span>
                            <input
                                type="text"
                                v-model="item.description"
                                class="syn-rubric-desc"
                                placeholder="描述该分段的典型特征"
                            />
                            <button class="btn-icon" @click="scoringRubric.splice(idx, 1)" title="删除">✕</button>
                        </div>
                        <button class="btn btn-small btn-secondary" @click="addScoringRubric">+ 添加锚点</button>
                    </div>
                    <div class="syn-rubric" v-else>
                        <div class="syn-rubric-item syn-rubric-dimension" v-for="(item, idx) in scoringRubric" :key="idx">
                            <input type="text" v-model="item.dimension" placeholder="评分维度" />
                            <select v-model="item.source_chapter"><option value="">不限定章节</option><option v-for="chapter in frameworkData.chapters" :key="chapter.id" :value="chapter.id">第{{ chapter.chapter }}章</option></select>
                            <input type="number" v-model.number="item.weight" min="0.01" max="1" step="0.05" placeholder="权重" />
                            <input type="text" v-model="item.description" class="syn-rubric-desc" placeholder="说明该维度如何评分" />
                            <button class="btn-icon" @click="scoringRubric.splice(idx, 1)" title="删除">✕</button>
                        </div>
                        <button class="btn btn-small btn-secondary" @click="addScoringRubric">+ 添加评分维度</button>
                    </div>
                </div>
            </div>

            <!-- Preview Flow -->
            <div class="card fw-flow-preview-card" v-show="activeStage === 'preview'">
                <div class="fw-preview-header">
                    <div><h3>流程预览</h3><p>保存前核对章节依赖、算子数量与最终决策边界。</p></div>
                </div>
                <div class="flow-timeline" style="margin-top: 12px;">
                    <div
                        class="flow-step"
                        v-for="(ch, idx) in frameworkData.chapters"
                        :key="ch.id"
                    >
                        <div class="flow-step-left">
                            <div class="flow-step-badge">{{ ch.chapter }}</div>
                            <div class="flow-step-line" v-if="idx < frameworkData.chapters.length"></div>
                        </div>
                        <div class="flow-step-content">
                            <div class="flow-step-header">
                                <span class="flow-step-title">第{{ ch.chapter }}步 · {{ ch.title }}</span>
                                <span class="flow-step-count">{{ ch.operators.length }} 个算子</span>
                            </div>
                            <div class="flow-step-deps" v-if="ch.dependencies && ch.dependencies.length > 0">
                                ← 依赖：{{ ch.dependencies.map(d => getChapterLabel(d)).join(', ') }}
                            </div>
                            <div class="flow-step-ops" style="margin-top: 6px;">
                                <span class="flow-op" v-for="opId in ch.operators" :key="opId">
                                    {{ getOpName(opId) }}
                                </span>
                            </div>
                        </div>
                    </div>
                    <!-- Synthesis node -->
                    <div class="flow-step flow-step-final">
                        <div class="flow-step-left">
                            <div class="flow-step-badge flow-badge-final">★</div>
                        </div>
                        <div class="flow-step-content">
                            <div class="flow-step-header">
                                <span class="flow-step-title">综合研判 · 买入 >= {{ synthesisThresholds.buy }}, 回避 <= {{ synthesisThresholds.avoid }}</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Empty state -->
    <div class="card empty-state" v-if="!frameworkData && !creatingNew">
        选择一个框架开始编辑，或创建新框架
    </div>
</div>
    `,

    data() {
        return {
            frameworks: [],
            selectedFramework: '',
            frameworkData: null,
            creatingNew: false,
            newForm: { name: '', display_name: '', version: '1.0', analyst_role: '投资分析师', operators_dir: 'operators/v2' },
            saving: false,
            saveMessage: '',
            saveSuccess: false,
            activeStage: 'dag',
            selectedChapterId: '',

            // Available operators
            availableOps: {},
            opCategories: [],
            opNameMap: {},
            opMetaMap: {},
            operatorVersions: [],

            // Per-chapter add-op dropdown state
            addOpSelections: [],

            // Synthesis config
            synthesisThresholds: { buy: 70, avoid: 29 },
            thinkingSteps: [],
            scoringRubric: [],
            rubricMode: 'range',
            synthesisFields: [],
            publicSynthesisFields: [
                { field: '综合评分', type: 'int' },
                { field: '最终建议', type: 'str' },
                { field: '核心逻辑', type: 'str' },
                { field: '关键风险', type: 'list' },
                { field: '信心水平', type: 'str' },
            ],
        };
    },

    computed: {
        selectedChapterIndex() {
            const chapters = this.frameworkData?.chapters || [];
            if (!chapters.length) return -1;
            const index = chapters.findIndex(ch => ch.id === this.selectedChapterId);
            return index >= 0 ? index : 0;
        },
        selectedChapter() {
            return this.selectedChapterIndex >= 0
                ? this.frameworkData.chapters[this.selectedChapterIndex]
                : null;
        },
        dagLayers() {
            const chapters = this.frameworkData?.chapters || [];
            const levels = new Map();
            const layers = [];
            chapters.forEach((chapter, index) => {
                const dependencies = chapter.dependencies || [];
                const level = dependencies.length
                    ? Math.max(...dependencies.map(id => levels.get(id) ?? 0)) + 1
                    : 0;
                levels.set(chapter.id, level);
                if (!layers[level]) layers[level] = { level, items: [] };
                layers[level].items.push({ chapter, index });
            });
            return layers.filter(Boolean);
        },
        missingOperatorIds() {
            if (!this.frameworkData) return [];
            const ids = this.frameworkData.chapters.flatMap(ch => ch.operators || []);
            return [...new Set(ids.filter(id => !this.opMetaMap[id]))];
        },
        thresholdError() {
            const buy = Number(this.synthesisThresholds.buy);
            const avoid = Number(this.synthesisThresholds.avoid);
            if (!Number.isFinite(buy) || !Number.isFinite(avoid)) return '请填写有效的决策阈值';
            if (avoid < 0 || buy > 100 || avoid >= buy) return '决策边界必须满足 0 ≤ 回避阈值 < 买入阈值 ≤ 100';
            return '';
        },
    },

    created() {
        this.loadFrameworks();
        this.loadOperatorVersions();
        this.loadAvailableOps('operators/v2');
    },

    mounted() {
        this._resourceUpdatedHandler = event => this.handleResourceUpdated(event);
        window.addEventListener('app-resource-updated', this._resourceUpdatedHandler);
        this.syncAgentContext();
    },

    beforeUnmount() {
        if (this._resourceUpdatedHandler) {
            window.removeEventListener('app-resource-updated', this._resourceUpdatedHandler);
        }
    },

    watch: {
        frameworkData: {
            deep: true,
            handler() { this.syncAgentContext(); },
        },
        synthesisThresholds: {
            deep: true,
            handler() { this.syncAgentContext(); },
        },
        thinkingSteps: {
            deep: true,
            handler() { this.syncAgentContext(); },
        },
        scoringRubric: {
            deep: true,
            handler() { this.syncAgentContext(); },
        },
        synthesisFields: {
            deep: true,
            handler() { this.syncAgentContext(); },
        },
    },

    methods: {
        syncAgentContext() {
            const data = this.frameworkData;
            const context = {
                framework_id: this.selectedFramework || this.newForm.name || '',
                framework_name: data?.display_name || this.newForm.display_name || '尚未选择框架',
                mode: this.creatingNew ? 'create' : (data ? 'edit' : 'browse'),
                framework: data ? {
                    name: data.name,
                    display_name: data.display_name,
                    version: data.version,
                    version_string: data.version_string,
                    operators_dir: data.operators_dir,
                    analyst_role: data.analyst_role,
                    chapters: data.chapters.map(ch => ({
                        id: ch.id,
                        chapter: ch.chapter,
                        title: ch.title,
                        operators: [...ch.operators],
                        dependencies: [...(ch.dependencies || [])],
                        effective_outputs: this.chapterOutputs(ch),
                        data_needed: this.chapterDataNeeds(ch),
                    })),
                    synthesis: {
                        thinking_steps: this.thinkingSteps.map(step => ({ ...step })),
                        scoring_rubric: this.scoringRubric.map(item => ({ ...item })),
                        decision_thresholds: {
                            buy: this.synthesisThresholds.buy,
                            avoid: this.synthesisThresholds.avoid,
                        },
                        fields: this.synthesisFields.map(item => ({ ...item })),
                    },
                } : null,
            };
            if (window.setAppContext) window.setAppContext(context);
            else window._appContext = context;
        },

        async handleResourceUpdated(event) {
            const detail = event.detail || {};
            if (!String(detail.action?.path || '').startsWith('/api/frameworks')) return;
            await this.loadFrameworks();
            if (detail.result?.name) this.selectedFramework = detail.result.name;
            if (this.selectedFramework) await this.loadFramework();
            this.syncAgentContext();
        },

        async loadFrameworks() {
            try {
                this.frameworks = await apiFetch('/api/frameworks');
                if (!this.creatingNew) {
                    const exists = this.frameworks.some(item => item.name === this.selectedFramework);
                    if (!exists) this.selectedFramework = this.frameworks[0]?.name || '';
                    if (this.selectedFramework && this.frameworkData?.name !== this.selectedFramework) await this.loadFramework();
                }
            } catch (e) {
                console.error('Failed to load frameworks:', e);
            }
        },

        async loadOperatorVersions() {
            try {
                const data = await apiFetch('/api/operators/versions');
                this.operatorVersions = data.versions || [];
                if (!this.newForm.operators_dir && data.default) this.newForm.operators_dir = `operators/${data.default}`;
            } catch (e) {
                console.error('Failed to load operator versions:', e);
            }
        },

        async loadAvailableOps(operatorsDir = 'operators/v2') {
            try {
                const data = await apiFetch(`/api/operators?version=${encodeURIComponent(operatorsDir)}`);
                if (data.available_versions?.length) this.operatorVersions = data.available_versions;
                this.opCategories = data.categories || [];
                this.availableOps = data.operators || {};

                // Build operator lookup maps used by chapter editing and previews.
                const nameMap = {};
                const metaMap = {};
                for (const cat of this.opCategories) {
                    const ops = this.availableOps[cat] || [];
                    for (const op of ops) {
                        nameMap[op.id] = op.name;
                        metaMap[op.id] = op;
                    }
                }
                this.opNameMap = nameMap;
                this.opMetaMap = metaMap;
            } catch (e) {
                console.error('Failed to load operators:', e);
            }
        },

        async loadFramework() {
            if (!this.selectedFramework) {
                this.frameworkData = null;
                this.selectedChapterId = '';
                return;
            }
            try {
                const data = await apiFetch(`/api/frameworks/${this.selectedFramework}`);
                await this.loadAvailableOps(data.operators_dir || 'operators/v2');
                // Convert operators from [{id, name}] to [id] for editing
                for (const ch of data.chapters) {
                    // Store operator name map
                    for (const op of ch.operators) {
                        if (typeof op === 'object' && op.id) {
                            this.opNameMap[op.id] = op.name;
                            this.opMetaMap[op.id] = { ...(this.opMetaMap[op.id] || {}), ...op };
                        }
                    }
                    ch.operators = ch.operators.map(op =>
                        typeof op === 'object' ? op.id : op
                    );
                }
                this.frameworkData = data;
                if (!data.chapters.some(ch => ch.id === this.selectedChapterId)) {
                    this.selectedChapterId = data.chapters[0]?.id || '';
                }
                this.addOpSelections = data.chapters.map(() => '');

                // Load synthesis config
                const syn = data.synthesis || {};
                const thresholds = syn.decision_thresholds || {};
                this.synthesisThresholds = {
                    buy: thresholds.buy ?? 70,
                    avoid: thresholds.avoid ?? 29,
                };

                // Load thinking steps and scoring rubric
                this.thinkingSteps = (syn.thinking_steps || []).map(s => ({
                    step: s.step || '',
                    instruction: s.instruction || '',
                }));
                this.scoringRubric = (syn.scoring_rubric || []).map(r => ({
                    range: r.range || '',
                    description: r.description || '',
                    dimension: r.dimension || '',
                    source_chapter: r.source_chapter || '',
                    weight: r.weight ?? null,
                }));
                this.rubricMode = this.scoringRubric.some(item => item.dimension) ? 'dimension' : 'range';
                this.synthesisFields = (data.synthesis_fields || []).map(item => ({
                    field: item.field || '',
                    type: item.type || 'str',
                    desc: item.desc || '',
                }));
                this.syncAgentContext();
            } catch (e) {
                console.error('Failed to load framework:', e);
            }
        },

        showNewFramework() {
            this.creatingNew = true;
            this.activeStage = 'dag';
            this.newForm = { name: '', display_name: '', version: '1.0', analyst_role: '投资分析师', operators_dir: 'operators/v2' };
            this.syncAgentContext();
        },

        async createFramework() {
            try {
                const result = await apiFetch('/api/frameworks', {
                    method: 'POST',
                    body: JSON.stringify({
                        name: this.newForm.name,
                        display_name: this.newForm.display_name,
                        version: this.newForm.version,
                        analyst_role: this.newForm.analyst_role,
                        operators_dir: this.newForm.operators_dir,
                        chapters: [],
                    }),
                });
                this.creatingNew = false;
                await this.loadFrameworks();
                this.selectedFramework = this.newForm.name;
                await this.loadFramework();
                this.syncAgentContext();
            } catch (e) {
                alert('创建失败: ' + e.message);
            }
        },

        async saveFramework() {
            if (!this.frameworkData) return;
            if (this.thresholdError) {
                this.saveSuccess = false;
                this.saveMessage = this.thresholdError;
                return;
            }
            if (this.missingOperatorIds.length) {
                this.saveSuccess = false;
                this.saveMessage = `当前算子版本缺少：${this.missingOperatorIds.join('、')}`;
                return;
            }
            this.saving = true;
            this.saveMessage = '';

            try {
                const chapters = this.frameworkData.chapters.map(ch => ({
                    id: ch.id,
                    chapter: ch.chapter,
                    title: ch.title,
                    operators: ch.operators,
                    dependencies: ch.dependencies || [],
                }));

                // Build synthesis with full config
                const synthesis = {
                    thinking_steps: this.thinkingSteps.filter(s => s.step),
                    scoring_rubric: this.scoringRubric.filter(r =>
                        this.rubricMode === 'dimension'
                            ? r.dimension && r.description
                            : r.range && r.description
                    ).map(r => this.rubricMode === 'dimension' ? {
                        dimension: r.dimension,
                        source_chapter: r.source_chapter || null,
                        weight: r.weight,
                        description: r.description,
                    } : {
                        range: r.range,
                        description: r.description,
                    }),
                    decision_thresholds: {
                        buy: this.synthesisThresholds.buy,
                        avoid: this.synthesisThresholds.avoid,
                        watch: [this.synthesisThresholds.avoid + 1, this.synthesisThresholds.buy - 1],
                    },
                };

                await apiFetch(`/api/frameworks/${this.selectedFramework}`, {
                    method: 'PUT',
                    body: JSON.stringify({
                        display_name: this.frameworkData.display_name,
                        version: this.frameworkData.version,
                        version_string: this.frameworkData.version_string,
                        analyst_role: this.frameworkData.analyst_role,
                        operators_dir: this.frameworkData.operators_dir,
                        chapters: chapters,
                        synthesis: synthesis,
                        synthesis_fields: this.synthesisFields.filter(item => item.field).map(item => ({ ...item })),
                    }),
                });

                this.saveSuccess = true;
                this.saveMessage = '框架已保存';
                await this.loadFrameworks();
                this.syncAgentContext();
            } catch (e) {
                this.saveSuccess = false;
                this.saveMessage = '保存失败: ' + e.message;
            } finally {
                this.saving = false;
                setTimeout(() => { this.saveMessage = ''; }, 3000);
            }
        },

        getOpName(opId) {
            return this.opNameMap[opId] || opId;
        },

        getOpMeta(opId) {
            return this.opMetaMap[opId] || null;
        },

        chapterOutputs(chapter) {
            const seen = new Set();
            const result = [];
            for (const opId of chapter.operators || []) {
                const operator = this.getOpMeta(opId);
                for (const item of operator?.outputs || []) {
                    if (seen.has(item.field)) continue;
                    seen.add(item.field);
                    result.push({ ...item, source_operator: opId });
                }
            }
            return result;
        },

        chapterDataNeeds(chapter) {
            return [...new Set((chapter.operators || []).flatMap(opId => this.getOpMeta(opId)?.data_needed || []))];
        },

        async changeOperatorLibrary() {
            if (!this.frameworkData) return;
            await this.loadAvailableOps(this.frameworkData.operators_dir);
            this.addOpSelections = this.frameworkData.chapters.map(() => '');
            this.syncAgentContext();
        },

        getChapterLabel(chId) {
            if (!this.frameworkData) return chId;
            const ch = this.frameworkData.chapters.find(c => c.id === chId);
            return ch ? `第${ch.chapter}章` : chId;
        },

        getChapterNumber(chId) {
            if (!this.frameworkData) return chId;
            const chapter = this.frameworkData.chapters.find(item => item.id === chId);
            return chapter ? String(chapter.chapter).padStart(2, '0') : chId;
        },

        chapterMissingOperators(chapter) {
            return (chapter?.operators || []).filter(id => !this.opMetaMap[id]);
        },

        // Chapter management
        getPriorChapters(currentIdx) {
            return this.frameworkData.chapters.filter((_, i) => i < currentIdx);
        },

        toggleDep(chapter, depId, event) {
            const deps = [...(chapter.dependencies || [])];
            if (event.target.checked) {
                if (!deps.includes(depId)) deps.push(depId);
            } else {
                const idx = deps.indexOf(depId);
                if (idx >= 0) deps.splice(idx, 1);
            }
            chapter.dependencies = deps;
        },

        addThinkingStep() {
            this.thinkingSteps.push({ step: '', instruction: '' });
        },

        removeThinkingStep(idx) {
            this.thinkingSteps.splice(idx, 1);
        },

        addScoringRubric() {
            if (this.rubricMode === 'dimension') {
                this.scoringRubric.push({ dimension: '', source_chapter: '', weight: null, description: '' });
            } else {
                this.scoringRubric.push({ range: '', description: '' });
            }
        },

        changeRubricMode(mode) {
            if (mode === this.rubricMode) return;
            if (this.scoringRubric.length && !confirm('切换评分规则类型会清空当前评分规则，是否继续？')) return;
            this.rubricMode = mode;
            this.scoringRubric = [];
        },

        addSynthesisField() {
            this.synthesisFields.push({ field: '', type: 'str', desc: '' });
        },

        addChapter() {
            if (!this.frameworkData) return;
            const nextNum = this.frameworkData.chapters.length + 1;
            let suffix = nextNum;
            let chapterId = `ch${String(suffix).padStart(2, '0')}_new`;
            const existingIds = new Set(this.frameworkData.chapters.map(ch => ch.id));
            while (existingIds.has(chapterId)) {
                suffix += 1;
                chapterId = `ch${String(suffix).padStart(2, '0')}_new`;
            }
            this.frameworkData.chapters.push({
                id: chapterId,
                chapter: nextNum,
                title: '',
                operators: [],
                dependencies: [],
            });
            this.addOpSelections.push('');
            this.selectedChapterId = chapterId;
        },

        removeChapter(idx) {
            if (!confirm('确定删除此章节?')) return;
            const removedId = this.frameworkData.chapters[idx].id;
            this.frameworkData.chapters.splice(idx, 1);
            this.addOpSelections.splice(idx, 1);

            // Renumber chapters
            this.frameworkData.chapters.forEach((ch, i) => {
                ch.chapter = i + 1;
            });

            // Clean up dependencies
            for (const ch of this.frameworkData.chapters) {
                ch.dependencies = (ch.dependencies || []).filter(d => d !== removedId);
            }
            const nextChapter = this.frameworkData.chapters[Math.min(idx, this.frameworkData.chapters.length - 1)];
            this.selectedChapterId = nextChapter?.id || '';
        },

        removeOpFromChapter(chIdx, opIdx) {
            this.frameworkData.chapters[chIdx].operators.splice(opIdx, 1);
        },

        addOpToChapter(chIdx) {
            const opId = this.addOpSelections[chIdx];
            if (opId && !this.frameworkData.chapters[chIdx].operators.includes(opId)) {
                this.frameworkData.chapters[chIdx].operators.push(opId);
            }
            this.addOpSelections[chIdx] = '';
        },
    },
};
