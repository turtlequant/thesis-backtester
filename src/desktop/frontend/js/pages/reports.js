/**
 * Reports page component.
 *
 * Lists all historical analyses with filtering and detail view.
 */
const ReportsPage = {
    template: `
<div class="page-reports">
    <div class="card">
        <div class="reports-header">
            <h2>历史报告</h2>
            <button class="btn btn-secondary" @click="loadReports">刷新</button>
        </div>

        <!-- Filters -->
        <div class="filter-row">
            <input
                type="text"
                v-model="filterText"
                placeholder="搜索: 股票代码 / 策略..."
                class="filter-input"
            />
            <select v-model="filterRecommendation" class="filter-select">
                <option value="">全部建议</option>
                <option value="买入">买入</option>
                <option value="建仓">建仓收息</option>
                <option value="观望">观望</option>
                <option value="回避">回避</option>
                <option value="值得深入">值得深入</option>
            </select>
        </div>

        <!-- Reports Table -->
        <div class="table-container" v-if="filteredReports.length > 0">
            <table>
                <thead>
                    <tr>
                        <th>股票代码</th>
                        <th>策略</th>
                        <th>评分</th>
                        <th>建议</th>
                        <th>分析日期</th>
                        <th>创建时间</th>
                        <th>操作</th>
                    </tr>
                </thead>
                <tbody>
                    <tr
                        v-for="r in filteredReports"
                        :key="r.id"
                        :class="{ 'row-selected': selectedId === r.id }"
                        @click="selectReport(r.id)"
                    >
                        <td class="code-cell">{{ r.ts_code }}</td>
                        <td>{{ r.strategy }}</td>
                        <td>
                            <span class="score-badge" :class="scoreClass(r.score)">
                                {{ r.score || '--' }}
                            </span>
                        </td>
                        <td>
                            <span class="rec-badge" :class="recClass(r.recommendation)">
                                {{ r.recommendation || '--' }}
                            </span>
                        </td>
                        <td>{{ r.cutoff_date }}</td>
                        <td>{{ r.created_at }}</td>
                        <td class="action-cell">
                            <button
                                class="btn btn-small"
                                :class="compareSelected.includes(r.id) ? 'btn-primary' : 'btn-secondary'"
                                @click.stop="toggleCompare(r.id)"
                                :disabled="!compareSelected.includes(r.id) && compareSelected.length >= 2"
                            >对比</button>
                            <button
                                class="btn btn-small btn-danger"
                                @click.stop="confirmDelete(r.id)"
                            >删除</button>
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>

        <div class="empty-state" v-else-if="!loading">
            {{ reports.length === 0 ? '暂无历史报告' : '无匹配结果' }}
        </div>

        <div class="loading-state" v-if="loading">加载中...</div>
    </div>

    <!-- Report Detail -->
    <div class="card report-detail" v-if="detail">
        <div class="detail-header">
            <h2>{{ detail.ts_code }} - {{ detail.strategy }}</h2>
            <button class="btn btn-secondary" @click="detail = null">关闭</button>
        </div>

        <!-- Metadata Bar -->
        <div class="detail-meta-bar" v-if="detail.full_data && detail.full_data.metadata">
            <span v-if="detail.full_data.metadata.model">模型: {{ detail.full_data.metadata.model }}</span>
            <span v-if="detail.full_data.metadata.elapsed_seconds">耗时: {{ detail.full_data.metadata.elapsed_seconds }}s</span>
            <span v-if="detail.cutoff_date">分析日期: {{ detail.cutoff_date }}</span>
            <span v-if="detail.created_at">创建: {{ detail.created_at }}</span>
        </div>

        <!-- Score + Recommendation Hero -->
        <div class="detail-hero" v-if="detail.full_data && detail.full_data.synthesis">
            <div class="detail-score" :class="scoreClass(detail.score)">
                <div class="detail-score-number">{{ detail.score || '--' }}</div>
                <div class="detail-score-label">综合评分</div>
            </div>
            <div class="detail-rec-badge" :class="recClass(detail.recommendation)">
                {{ detail.recommendation || '--' }}
            </div>
            <div class="detail-confidence" v-if="detail.full_data.synthesis['信心水平'] || detail.full_data.synthesis.confidence">
                信心: {{ detail.full_data.synthesis['信心水平'] || detail.full_data.synthesis.confidence }}
            </div>
        </div>

        <!-- Synthesis Summary -->
        <div class="detail-synthesis" v-if="detail.full_data && detail.full_data.synthesis">
            <h3>综合研判</h3>
            <div class="synthesis-fields">
                <div
                    v-for="(value, key) in detailSynthesisFiltered"
                    :key="key"
                    class="synthesis-field"
                >
                    <span class="field-key">{{ key }}:</span>
                    <span class="field-val">{{ formatValue(value) }}</span>
                </div>
            </div>
        </div>

        <!-- Chapter Outputs (collapsible) -->
        <div class="detail-chapters" v-if="detail.full_data && detail.full_data.chapter_outputs">
            <h3>章节结构化输出</h3>
            <div
                v-for="(output, chId) in detail.full_data.chapter_outputs"
                :key="chId"
                class="chapter-output-collapsible"
            >
                <div class="chapter-output-header" @click="toggleDetailChapter(chId)">
                    <span class="chapter-output-toggle">{{ expandedDetailChapters[chId] ? '▾' : '▸' }}</span>
                    <span>{{ chId }}</span>
                    <span class="chapter-output-summary">{{ chapterOutputSummary(output) }}</span>
                </div>
                <pre v-if="expandedDetailChapters[chId]">{{ JSON.stringify(output, null, 2) }}</pre>
            </div>
        </div>

        <!-- Full Report Text -->
        <div class="detail-report" v-if="detail.report_text">
            <h3>完整报告</h3>
            <pre class="report-text">{{ detail.report_text }}</pre>
        </div>
    </div>

    <!-- Compare Bar -->
    <div class="compare-bar" v-if="compareSelected.length > 0 && !compareMode">
        <span>已选 {{ compareSelected.length }} / 2 份报告</span>
        <button class="btn btn-primary btn-small" @click="startCompare" :disabled="compareSelected.length !== 2">开始对比</button>
        <button class="btn btn-secondary btn-small" @click="clearCompare">取消对比</button>
    </div>

    <!-- Compare Panel (side-by-side) -->
    <div class="card compare-panel" v-if="compareMode && compareReports.length === 2">
        <div class="compare-header">
            <h2>对比分析</h2>
            <button class="btn btn-secondary" @click="exitCompare">取消对比</button>
        </div>
        <div class="compare-grid">
            <div v-for="r in compareReports" :key="r.id" class="compare-col">
                <h3>{{ r.ts_code }} <span class="compare-strategy">({{ r.strategy }})</span></h3>
                <div class="compare-score-row">
                    <span class="score-badge" :class="scoreClass(r.score)">{{ r.score || '--' }}</span>
                    <span class="rec-badge" :class="recClass(r.recommendation)">{{ r.recommendation || '--' }}</span>
                </div>
                <div v-if="r.full_data && r.full_data.synthesis" class="compare-fields">
                    <div v-for="(value, key) in r.full_data.synthesis" :key="key" class="compare-field">
                        <span class="field-key">{{ key }}:</span>
                        <span class="field-val" :class="compareHighlight(key, r)">{{ formatValue(value) }}</span>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
    `,

    data() {
        return {
            reports: [],
            loading: false,
            filterText: '',
            filterRecommendation: '',
            selectedId: null,
            detail: null,
            compareMode: false,
            compareReports: [],
            compareSelected: [],
            expandedDetailChapters: {},
        };
    },

    computed: {
        detailSynthesisFiltered() {
            if (!this.detail?.full_data?.synthesis) return {};
            const skip = ['综合评分', 'score', '最终建议', 'recommendation', '信心水平', 'confidence'];
            const result = {};
            for (const [key, value] of Object.entries(this.detail.full_data.synthesis)) {
                if (!skip.includes(key) && value) {
                    result[key] = value;
                }
            }
            return result;
        },

        filteredReports() {
            let filtered = this.reports;

            if (this.filterText) {
                const q = this.filterText.toLowerCase();
                filtered = filtered.filter(r =>
                    (r.ts_code || '').toLowerCase().includes(q) ||
                    (r.strategy || '').toLowerCase().includes(q)
                );
            }

            if (this.filterRecommendation) {
                filtered = filtered.filter(r =>
                    (r.recommendation || '').includes(this.filterRecommendation)
                );
            }

            return filtered;
        },
    },

    created() {
        this.loadReports();
    },

    methods: {
        async loadReports() {
            this.loading = true;
            try {
                this.reports = await api.listReports();
            } catch (e) {
                console.error('Failed to load reports:', e);
            } finally {
                this.loading = false;
            }
        },

        async selectReport(id) {
            this.selectedId = id;
            this.expandedDetailChapters = {};
            // Update global context for chat assistant
            window._appContext = { report_id: id };
            try {
                this.detail = await api.getReport(id);
            } catch (e) {
                console.error('Failed to load report:', e);
            }
        },

        async confirmDelete(id) {
            if (!confirm('确定删除此报告?')) return;
            try {
                await api.deleteReport(id);
                this.reports = this.reports.filter(r => r.id !== id);
                if (this.selectedId === id) {
                    this.selectedId = null;
                    this.detail = null;
                }
            } catch (e) {
                alert(`删除失败: ${e.message}`);
            }
        },

        scoreClass(score) {
            const s = parseInt(score);
            if (s >= 75) return 'score-buy';
            if (s >= 50) return 'score-watch';
            if (s > 0) return 'score-avoid';
            return '';
        },

        recClass(rec) {
            if (!rec) return '';
            if (rec.includes('买入') || rec.includes('建仓') || rec.includes('值得深入')) return 'rec-buy';
            if (rec.includes('观望')) return 'rec-watch';
            return 'rec-avoid';
        },

        formatValue(value) {
            if (typeof value === 'object') return JSON.stringify(value);
            return String(value);
        },

        toggleCompare(id) {
            const idx = this.compareSelected.indexOf(id);
            if (idx >= 0) {
                this.compareSelected = this.compareSelected.filter(x => x !== id);
            } else if (this.compareSelected.length < 2) {
                this.compareSelected = [...this.compareSelected, id];
            }
        },

        async startCompare() {
            if (this.compareSelected.length !== 2) return;
            this.compareReports = [];
            for (const id of this.compareSelected) {
                try {
                    const r = await api.getReport(id);
                    this.compareReports.push(r);
                } catch (e) {
                    console.error('Failed to load report for compare:', e);
                }
            }
            if (this.compareReports.length === 2) {
                this.compareMode = true;
            }
        },

        clearCompare() {
            this.compareSelected = [];
            this.compareMode = false;
            this.compareReports = [];
        },

        exitCompare() {
            this.compareMode = false;
            this.compareReports = [];
            this.compareSelected = [];
        },

        compareHighlight(key, report) {
            if (this.compareReports.length !== 2) return '';
            const other = this.compareReports.find(r => r.id !== report.id);
            if (!other?.full_data?.synthesis) return '';
            const thisVal = String(report.full_data?.synthesis?.[key] || '');
            const otherVal = String(other.full_data?.synthesis?.[key] || '');
            if (thisVal !== otherVal) return 'compare-diff';
            return '';
        },

        toggleDetailChapter(chId) {
            this.expandedDetailChapters = {
                ...this.expandedDetailChapters,
                [chId]: !this.expandedDetailChapters[chId],
            };
        },

        chapterOutputSummary(output) {
            if (!output || typeof output !== 'object') return '';
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
    },
};
