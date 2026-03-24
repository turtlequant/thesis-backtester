/**
 * Framework orchestration page component.
 *
 * View and edit strategy frameworks (chapters + operators + synthesis).
 */
const FrameworksPage = {
    template: `
<div class="page-frameworks">
    <!-- Top Bar -->
    <div class="card">
        <div class="fw-top-bar">
            <div class="fw-selector">
                <select v-model="selectedFramework" @change="loadFramework">
                    <option value="" disabled>选择框架...</option>
                    <option v-for="fw in frameworks" :key="fw.name" :value="fw.name">
                        {{ fw.display_name }} ({{ fw.chapter_count }}章, {{ fw.operator_count }}算子)
                    </option>
                </select>
            </div>
            <div class="fw-actions">
                <button class="btn btn-secondary" @click="showNewFramework">+ 新建框架</button>
                <button class="btn btn-primary" @click="saveFramework" :disabled="!frameworkData || saving">
                    {{ saving ? '保存中...' : '保存框架' }}
                </button>
            </div>
        </div>
        <div class="save-status" v-if="saveMessage" :class="saveSuccess ? 'success' : 'error'" style="margin-top: 8px;">
            {{ saveMessage }}
        </div>
    </div>

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
        </div>
        <div style="margin-top: 12px; display: flex; gap: 8px;">
            <button class="btn btn-primary" @click="createFramework" :disabled="!newForm.name || !newForm.display_name">创建</button>
            <button class="btn btn-secondary" @click="creatingNew = false">取消</button>
        </div>
    </div>

    <!-- Main Editor (only shown when framework loaded) -->
    <div v-if="frameworkData" class="fw-editor-layout">
        <!-- Left: Available Operators -->
        <div class="card fw-operators-panel">
            <h3>可用算子</h3>
            <input
                type="text"
                v-model="opSearch"
                placeholder="搜索算子..."
                style="margin-bottom: 8px;"
            />
            <div class="fw-op-groups">
                <div v-for="cat in opCategories" :key="cat" class="fw-op-group">
                    <div class="fw-op-group-title" @click="toggleOpCategory(cat)">
                        {{ cat }} ({{ (availableOps[cat] || []).length }})
                        <span class="fw-op-toggle">{{ expandedOpCats[cat] ? '▾' : '▸' }}</span>
                    </div>
                    <div v-if="expandedOpCats[cat]" class="fw-op-group-list">
                        <div
                            v-for="op in filteredOpsInCategory(cat)"
                            :key="op.id"
                            class="fw-op-item"
                            draggable="true"
                            @dragstart="onDragStart($event, op)"
                            :title="op.id"
                        >
                            <span class="fw-op-name">{{ op.name }}</span>
                            <span class="fw-op-id">{{ op.id }}</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Right: Chapter Editor -->
        <div class="fw-chapters-panel">
            <!-- Chapters -->
            <div
                v-for="(ch, idx) in frameworkData.chapters"
                :key="ch.id"
                class="card fw-chapter-card"
                @dragover.prevent
                @drop="onDropToChapter($event, idx)"
            >
                <div class="fw-chapter-header">
                    <div class="fw-chapter-badge">{{ ch.chapter }}</div>
                    <div class="fw-chapter-info">
                        <input
                            type="text"
                            v-model="ch.title"
                            class="fw-chapter-title-input"
                            placeholder="章节标题"
                        />
                        <div class="fw-chapter-id">{{ ch.id }}</div>
                    </div>
                    <button class="btn btn-small btn-danger" @click="removeChapter(idx)">删除</button>
                </div>

                <!-- Dependencies -->
                <div class="fw-chapter-deps">
                    <label>依赖章节（本章分析将基于所选章节的结论）:</label>
                    <div class="fw-deps-checkboxes" v-if="getPriorChapters(idx).length > 0">
                        <label
                            class="fw-dep-checkbox"
                            v-for="other in getPriorChapters(idx)"
                            :key="other.id"
                        >
                            <input
                                type="checkbox"
                                :value="other.id"
                                :checked="ch.dependencies.includes(other.id)"
                                @change="toggleDep(ch, other.id, $event)"
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
                        <div v-for="(opId, opIdx) in ch.operators" :key="opId + '-' + opIdx" class="fw-chapter-op">
                            <span class="flow-op">{{ getOpName(opId) }}</span>
                            <button class="fw-op-remove" @click="removeOpFromChapter(idx, opIdx)" title="移除">&times;</button>
                        </div>
                        <div class="fw-chapter-op-drop" v-if="ch.operators.length === 0">
                            拖拽算子到此处
                        </div>
                    </div>
                    <!-- Manual add -->
                    <div class="fw-chapter-add-op">
                        <select v-model="addOpSelections[idx]">
                            <option value="">+ 添加算子...</option>
                            <option v-for="op in allAvailableOps" :key="op.id" :value="op.id">
                                {{ op.name }} ({{ op.id }})
                            </option>
                        </select>
                        <button
                            class="btn btn-small"
                            v-if="addOpSelections[idx]"
                            @click="addOpToChapter(idx)"
                        >添加</button>
                    </div>
                </div>
            </div>

            <!-- Add Chapter Button -->
            <div class="fw-add-chapter">
                <button class="btn btn-secondary" @click="addChapter">+ 添加章节</button>
            </div>

            <!-- Synthesis Config -->
            <div class="card fw-synthesis-card">
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
                    <div class="syn-rubric">
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
                </div>
            </div>

            <!-- Preview Flow -->
            <div class="card">
                <div class="fw-preview-header">
                    <h3>流程预览</h3>
                    <button class="btn btn-small btn-secondary" @click="showPreview = !showPreview">
                        {{ showPreview ? '收起' : '展开' }}
                    </button>
                </div>
                <div v-if="showPreview" class="flow-timeline" style="margin-top: 12px;">
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
            newForm: { name: '', display_name: '', version: '1.0' },
            saving: false,
            saveMessage: '',
            saveSuccess: false,
            showPreview: true,

            // Available operators
            availableOps: {},
            opCategories: [],
            allAvailableOps: [],
            expandedOpCats: {},
            opSearch: '',
            opNameMap: {},

            // Per-chapter add-op dropdown state
            addOpSelections: [],

            // Synthesis config
            synthesisThresholds: { buy: 70, avoid: 29 },
            thinkingSteps: [],
            scoringRubric: [],
        };
    },

    created() {
        this.loadFrameworks();
        this.loadAvailableOps();
    },

    methods: {
        async loadFrameworks() {
            try {
                this.frameworks = await apiFetch('/api/frameworks');
            } catch (e) {
                console.error('Failed to load frameworks:', e);
            }
        },

        async loadAvailableOps() {
            try {
                const data = await apiFetch('/api/operators');
                this.opCategories = data.categories || [];
                this.availableOps = data.operators || {};

                // Build flat list and name map
                const all = [];
                const nameMap = {};
                for (const cat of this.opCategories) {
                    const ops = this.availableOps[cat] || [];
                    for (const op of ops) {
                        all.push(op);
                        nameMap[op.id] = op.name;
                    }
                    this.expandedOpCats[cat] = true;
                }
                this.allAvailableOps = all;
                this.opNameMap = nameMap;
            } catch (e) {
                console.error('Failed to load operators:', e);
            }
        },

        async loadFramework() {
            if (!this.selectedFramework) {
                this.frameworkData = null;
                return;
            }
            try {
                const data = await apiFetch(`/api/frameworks/${this.selectedFramework}`);
                // Convert operators from [{id, name}] to [id] for editing
                for (const ch of data.chapters) {
                    // Store operator name map
                    for (const op of ch.operators) {
                        if (typeof op === 'object' && op.id) {
                            this.opNameMap[op.id] = op.name;
                        }
                    }
                    ch.operators = ch.operators.map(op =>
                        typeof op === 'object' ? op.id : op
                    );
                }
                this.frameworkData = data;
                this.addOpSelections = data.chapters.map(() => '');

                // Load synthesis config
                const syn = data.synthesis || {};
                const thresholds = syn.decision_thresholds || {};
                this.synthesisThresholds = {
                    buy: thresholds.buy || 70,
                    avoid: thresholds.avoid || 29,
                };

                // Load thinking steps and scoring rubric
                this.thinkingSteps = (syn.thinking_steps || []).map(s => ({
                    step: s.step || '',
                    instruction: s.instruction || '',
                }));
                this.scoringRubric = (syn.scoring_rubric || []).map(r => ({
                    range: r.range || '',
                    description: r.description || '',
                }));
            } catch (e) {
                console.error('Failed to load framework:', e);
            }
        },

        showNewFramework() {
            this.creatingNew = true;
            this.newForm = { name: '', display_name: '', version: '1.0' };
        },

        async createFramework() {
            try {
                const result = await apiFetch('/api/frameworks', {
                    method: 'POST',
                    body: JSON.stringify({
                        name: this.newForm.name,
                        display_name: this.newForm.display_name,
                        version: this.newForm.version,
                        chapters: [],
                    }),
                });
                this.creatingNew = false;
                await this.loadFrameworks();
                this.selectedFramework = this.newForm.name;
                await this.loadFramework();
            } catch (e) {
                alert('创建失败: ' + e.message);
            }
        },

        async saveFramework() {
            if (!this.frameworkData) return;
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
                    scoring_rubric: this.scoringRubric.filter(r => r.range),
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
                        chapters: chapters,
                        synthesis: synthesis,
                    }),
                });

                this.saveSuccess = true;
                this.saveMessage = '框架已保存';
                await this.loadFrameworks();
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

        getChapterLabel(chId) {
            if (!this.frameworkData) return chId;
            const ch = this.frameworkData.chapters.find(c => c.id === chId);
            return ch ? `第${ch.chapter}章` : chId;
        },

        toggleOpCategory(cat) {
            this.expandedOpCats = {
                ...this.expandedOpCats,
                [cat]: !this.expandedOpCats[cat],
            };
        },

        filteredOpsInCategory(cat) {
            const ops = this.availableOps[cat] || [];
            if (!this.opSearch) return ops;
            const q = this.opSearch.toLowerCase();
            return ops.filter(op =>
                op.id.toLowerCase().includes(q) ||
                op.name.toLowerCase().includes(q)
            );
        },

        // Drag and drop
        onDragStart(event, op) {
            event.dataTransfer.setData('text/plain', op.id);
        },

        onDropToChapter(event, chapterIdx) {
            const opId = event.dataTransfer.getData('text/plain');
            if (opId && this.frameworkData) {
                this.frameworkData.chapters[chapterIdx].operators.push(opId);
            }
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
            this.scoringRubric.push({ range: '', description: '' });
        },

        addChapter() {
            if (!this.frameworkData) return;
            const nextNum = this.frameworkData.chapters.length + 1;
            this.frameworkData.chapters.push({
                id: `ch${String(nextNum).padStart(2, '0')}_new`,
                chapter: nextNum,
                title: '',
                operators: [],
                dependencies: [],
            });
            this.addOpSelections.push('');
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
        },

        removeOpFromChapter(chIdx, opIdx) {
            this.frameworkData.chapters[chIdx].operators.splice(opIdx, 1);
        },

        addOpToChapter(chIdx) {
            const opId = this.addOpSelections[chIdx];
            if (opId) {
                this.frameworkData.chapters[chIdx].operators.push(opId);
                this.addOpSelections[chIdx] = '';
            }
        },
    },
};
