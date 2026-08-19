/** Indexed report library, structured reader and constrained comparison. */
const ReportsPage = {
    template: `
<div class="page page-reports reports-workspace">
    <template v-if="viewMode === 'library'">
        <workspace-page-header eyebrow="结构化投研 · 研究归档" title="分析报告" description="统一检索正式个股报告、最新批量研判与历史回测样本，并通过来源标记保持研究口径清晰。">
            <template #meta><span class="page-header-chip"><span>已索引</span>{{ indexedReports }} 份报告</span></template>
            <template #actions><button class="btn btn-secondary btn-small" @click="loadReports(true)" :disabled="loading">{{ loading ? '索引中…' : '刷新索引' }}</button></template>
        </workspace-page-header>

        <section class="card report-library-card">
            <div class="section-title-row reports-library-head">
                <div><h2>报告库</h2><p>报告文件是事实来源，SQLite 只承担检索索引；当前条件下 {{ totalReports }} 份。</p></div>
            </div>

            <div class="report-filter-grid">
                <div class="setting-item report-filter-search"><label>搜索报告</label><input type="text" v-model.trim="filters.query" placeholder="输入股票代码、名称、研究框架或核心逻辑" /></div>
                <div class="setting-item"><label>研究框架</label><select v-model="filters.framework"><option value="">全部框架</option><option v-for="item in frameworkOptions" :key="item.id" :value="item.id">{{ item.name }}</option></select></div>
                <div class="setting-item"><label>最终建议</label><select v-model="filters.recommendation"><option value="">全部建议</option><option value="买入">买入</option><option value="观望">观望</option><option value="回避">回避</option></select></div>
                <div class="setting-item"><label>报告来源</label><select v-model="filters.origin"><option value="">全部来源</option><option value="individual">个股分析</option><option value="latest_judgement">最新研判</option><option value="historical_backtest">历史回测样本</option></select></div>
                <div class="setting-item"><label>起始日期</label><input type="date" v-model="filters.start_date" /></div>
                <div class="setting-item"><label>结束日期</label><input type="date" v-model="filters.end_date" /></div>
            </div>

            <div class="error-msg" v-if="error">{{ error }}</div>
            <div class="table-container report-library-table-wrap" v-if="reports.length">
                <table class="report-library-table">
                    <thead><tr><th>股票</th><th>研究框架</th><th>截面与来源</th><th>判断</th><th>核心逻辑</th><th>操作</th></tr></thead>
                    <tbody>
                        <tr v-for="report in reports" :key="report.id" @click="openReport(report.id)">
                            <td class="report-stock-cell"><strong>{{ report.stock_name || report.ts_code }}</strong><small>{{ report.ts_code }}</small></td>
                            <td><strong>{{ report.framework_name || report.strategy }}</strong><small v-if="report.framework_version">{{ report.framework_version }}</small></td>
                            <td><strong>{{ report.cutoff_date }}</strong><small>{{ originLabel(report.origin) }}</small></td>
                            <td><span class="score-badge" :class="scoreClass(report.score)">{{ report.score ?? '—' }}</span><span class="rec-badge" :class="recClass(report.recommendation)">{{ report.recommendation || '—' }}</span><small v-if="report.confidence">信心 {{ report.confidence }}</small></td>
                            <td class="report-logic-cell">{{ report.core_logic || '尚未形成统一核心逻辑' }}</td>
                            <td class="action-cell">
                                <button class="btn btn-small" :class="compareSelected.includes(report.id) ? 'btn-primary' : 'btn-secondary'" @click.stop="toggleCompare(report)" :disabled="!canSelectCompare(report)">{{ compareSelected.includes(report.id) ? '已选' : '对比' }}</button>
                                <button v-if="!report.read_only" class="btn btn-small btn-danger" @click.stop="confirmDelete(report.id)">删除</button>
                                <span v-else class="report-readonly-label">只读</span>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
            <div class="report-pagination" v-if="totalReports > 0 && !loading">
                <span>第 {{ page }} / {{ totalPages }} 页 · 共 {{ totalReports }} 份</span>
                <div>
                    <button class="btn btn-small btn-secondary" @click="goToPage(page - 1)" :disabled="page <= 1">上一页</button>
                    <button v-for="number in visiblePages" :key="number" class="btn btn-small" :class="number === page ? 'btn-primary' : 'btn-secondary'" @click="goToPage(number)">{{ number }}</button>
                    <button class="btn btn-small btn-secondary" @click="goToPage(page + 1)" :disabled="page >= totalPages">下一页</button>
                </div>
                <label>每页<select v-model.number="pageSize"><option :value="10">10</option><option :value="20">20</option><option :value="50">50</option></select>份</label>
            </div>
            <div class="empty-state" v-else-if="!loading && !reports.length">{{ indexedReports ? '没有符合当前条件的报告' : '暂无分析报告' }}</div>
            <div class="loading-state" v-if="loading">正在加载报告…</div>
        </section>

        <div class="compare-bar report-compare-bar" v-if="compareSelected.length">
            <div><strong>报告对比</strong><span>{{ compareHint }}</span></div>
            <span>已选 {{ compareSelected.length }} / 2</span>
            <button class="btn btn-primary btn-small" @click="startCompare" :disabled="compareSelected.length !== 2">开始对比</button>
            <button class="btn btn-secondary btn-small" @click="clearCompare">清除</button>
        </div>
    </template>

    <template v-else-if="viewMode === 'reader' && detail">
        <div class="report-mode-toolbar">
            <button class="btn btn-secondary" @click="backToLibrary">← 返回报告库</button>
            <div><strong>{{ detail.stock_name || detail.ts_code }}</strong><span>{{ detail.ts_code }} · {{ detail.framework_name || detail.strategy }} · {{ detail.cutoff_date }}</span></div>
            <button class="btn btn-secondary" @click="loadDetail(detail.id)">刷新报告</button>
        </div>

        <section class="report-reader">
            <aside class="report-reader-aside">
                <div class="report-reader-score">
                    <div><span>综合评分</span><strong :class="scoreClass(detail.score)">{{ detail.score ?? '—' }}</strong></div>
                    <span class="rec-badge" :class="recClass(detail.recommendation)">{{ detail.recommendation || '未形成建议' }}</span>
                </div>
                <div class="report-reader-meta"><span>{{ detail.framework_name || detail.strategy }}</span><span>{{ detail.cutoff_date }}</span><span>{{ originLabel(detail.origin) }}</span><span v-if="detail.confidence">信心 {{ detail.confidence }}</span></div>

                <div class="report-aside-section" v-if="detail.core_logic"><h3>核心逻辑</h3><p>{{ detail.core_logic }}</p></div>
                <div class="report-aside-section report-risk-summary" v-if="detail.risks"><h3>关键风险</h3><p>{{ detail.risks }}</p></div>

                <div class="report-aside-section report-toc-section" v-if="detailToc.length">
                    <h3>报告目录</h3>
                    <button v-for="item in detailToc" :key="item.anchor" :class="'report-toc-level-' + item.level" @click="scrollToAnchor(item.anchor)">{{ item.text }}</button>
                </div>

                <details class="report-runtime-meta"><summary>运行信息</summary><span v-if="detail.model">模型：{{ detail.model }}</span><span v-if="detail.elapsed_seconds">耗时：{{ detail.elapsed_seconds }} 秒</span><span>创建：{{ detail.created_at }}</span></details>
            </aside>

            <main class="report-reader-body" ref="reportBody">
                <article class="report-markdown" v-if="detail.report_text" v-html="detailReportHtml"></article>
                <div class="empty-state" v-else>此报告没有 Markdown 正文，可继续查看结构化证据。</div>

                <section class="report-evidence" v-if="orderedChapters.length">
                    <div class="report-evidence-title"><div><div class="workspace-eyebrow">结构化底稿</div><h2>算子证据链</h2><p>正文用于阅读；这里保留各章节的结构化输出，默认折叠。</p></div></div>
                    <div v-for="chapter in orderedChapters" :key="chapter.id" class="report-evidence-chapter">
                        <button class="report-evidence-toggle" @click="toggleDetailChapter(chapter.id)">
                            <span>{{ expandedDetailChapters[chapter.id] ? '▾' : '▸' }}</span>
                            <strong>{{ chapter.title }}</strong>
                            <small>{{ chapter.id }}</small>
                            <em>{{ chapterOutputSummary(chapter.output) }}</em>
                        </button>
                        <div class="report-evidence-fields" v-if="expandedDetailChapters[chapter.id] && isPlainRecord(chapter.output)">
                            <div v-for="(value, key) in chapter.output" :key="key"><span>{{ key }}</span><pre>{{ formatEvidence(value) }}</pre></div>
                        </div>
                        <pre class="report-evidence-raw" v-else-if="expandedDetailChapters[chapter.id]">{{ formatEvidence(chapter.output) }}</pre>
                    </div>
                </section>
            </main>
        </section>
    </template>

    <template v-else-if="viewMode === 'compare' && compareReports.length === 2">
        <div class="report-mode-toolbar">
            <button class="btn btn-secondary" @click="backToLibrary">← 返回报告库</button>
            <div><strong>{{ compareModeLabel }}</strong><span>{{ compareReports[0].ts_code }}</span></div>
            <button class="btn btn-secondary" @click="clearCompare">结束对比</button>
        </div>

        <section class="card report-compare-panel">
            <div class="report-compare-heading"><div class="workspace-eyebrow">结构化差异</div><h1>报告对比</h1><p>只比较同一股票、且日期或框架至少一项相同的两份报告。</p></div>
            <div class="report-compare-grid report-compare-heads">
                <div></div>
                <div v-for="report in compareReports" :key="report.id"><strong>{{ report.framework_name || report.strategy }}</strong><span>{{ report.cutoff_date }} · {{ originLabel(report.origin) }}</span></div>
            </div>
            <div class="report-compare-grid report-compare-row" v-for="row in comparisonRows" :key="row.key">
                <div><strong>{{ row.label }}</strong></div>
                <div v-for="(value, index) in row.values" :key="index" :class="{ 'report-compare-diff': row.different }">{{ value || '—' }}</div>
            </div>

            <div class="report-compare-chapters">
                <div v-for="report in compareReports" :key="report.id">
                    <h2>{{ report.framework_name || report.strategy }} · 章节结论</h2>
                    <details v-for="chapter in comparisonChapters(report)" :key="chapter.id" class="report-compare-chapter">
                        <summary><strong>{{ chapter.title }}</strong><small>{{ chapterOutputSummary(chapter.output) || '展开结构化结论' }}</small></summary>
                        <pre>{{ formatEvidence(chapter.output) }}</pre>
                    </details>
                </div>
            </div>
        </section>
    </template>
</div>`,

    data() {
        return {
            reports: [],
            indexedReports: 0,
            totalReports: 0,
            page: 1,
            pageSize: 20,
            totalPages: 1,
            frameworkOptions: [],
            loadSequence: 0,
            filterTimer: null,
            loading: false,
            error: '',
            filters: { query: '', framework: '', recommendation: '', origin: '', start_date: '', end_date: '' },
            viewMode: 'library',
            detail: null,
            expandedDetailChapters: {},
            compareSelected: [],
            compareReports: [],
            compareCandidates: [],
        };
    },

    computed: {
        visiblePages() {
            const count = Math.min(5, this.totalPages);
            const start = Math.max(1, Math.min(this.page - 2, this.totalPages - count + 1));
            return Array.from({ length: count }, (_, index) => start + index);
        },
        selectedReports() { return this.compareSelected.map(id => this.reports.find(item => item.id === id) || this.compareCandidates.find(item => item.id === id)).filter(Boolean); },
        compareHint() {
            if (!this.compareSelected.length) return '';
            if (this.compareSelected.length === 1) return '请选择同一股票、同框架不同日期，或同日期不同框架的报告';
            return this.compareModeLabel;
        },
        compareModeLabel() {
            if (this.compareReports.length === 2) return this.comparisonLabel(this.compareReports);
            return this.comparisonLabel(this.selectedReports);
        },
        detailNormalized() {
            const raw = this.detail?.report_text || '';
            if (!raw) return { toc: [], html: '' };
            const titles = { synthesis: '综合研判', synthesis_conclusion: '综合研判', ...(this.detail.chapter_titles || {}) };
            const headings = [];
            const seen = {};
            const slug = text => {
                let value = text.replace(/[\s#\\/\?"'`]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60) || 'section';
                seen[value] = (seen[value] || 0) + 1;
                if (seen[value] > 1) value += '-' + seen[value];
                return value;
            };
            const mapped = raw.split('\n').map(line => {
                const match = line.match(/^(#{1,4})\s+(.+?)\s*$/);
                if (!match) return line;
                const level = match[1].length;
                const text = level === 1 && titles[match[2].trim()] ? titles[match[2].trim()] : match[2].trim();
                headings.push({ level, text, anchor: slug(text) });
                return `${match[1]} ${text}`;
            }).join('\n');
            try {
                const safeMarkdown = mapped.replace(/</g, '&lt;').replace(/>/g, '&gt;');
                let index = 0;
                let html = marked.parse(safeMarkdown);
                html = html.replace(/<h([1-6])(?:\s[^>]*)?>([\s\S]*?)<\/h\1>/gi, (full, level, inner) => {
                    const heading = headings[index++];
                    return heading ? `<h${level} id="report-${heading.anchor}" class="report-heading report-heading-${heading.level}">${inner}</h${level}>` : full;
                });
                return { toc: headings.filter(item => item.level <= 2), html };
            } catch (_) {
                return { toc: [], html: `<pre>${mapped.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')}</pre>` };
            }
        },
        detailToc() { return this.detailNormalized.toc; },
        detailReportHtml() { return this.detailNormalized.html; },
        orderedChapters() { return this.chaptersFor(this.detail); },
        comparisonRows() {
            if (this.compareReports.length !== 2) return [];
            const [left, right] = this.compareReports;
            const rows = [
                ['score', '综合评分', left.score, right.score],
                ['recommendation', '最终建议', left.recommendation, right.recommendation],
                ['confidence', '信心水平', left.confidence, right.confidence],
                ['core_logic', '核心逻辑', left.core_logic, right.core_logic],
                ['risks', '关键风险', left.risks, right.risks],
            ];
            return rows.map(([key, label, a, b]) => ({ key, label, values: [a, b], different: String(a || '') !== String(b || '') }));
        },
    },

    watch: {
        filters: { deep: true, handler() { this.page = 1; this.scheduleReportLoad(); } },
        pageSize() { this.page = 1; this.loadReports(false); },
    },

    methods: {
        scheduleReportLoad() {
            clearTimeout(this.filterTimer);
            this.filterTimer = setTimeout(() => this.loadReports(false), 300);
        },
        async loadReports(refresh = false) {
            const sequence = ++this.loadSequence;
            this.loading = true; this.error = '';
            try {
                const result = await api.listReports({ page: this.page, page_size: this.pageSize, ...this.filters, refresh });
                if (sequence !== this.loadSequence) return;
                this.reports = result.items || [];
                this.indexedReports = Number(result.index_total || 0);
                this.totalReports = Number(result.total || 0);
                this.page = Number(result.page || 1);
                this.pageSize = Number(result.page_size || this.pageSize);
                this.totalPages = Number(result.pages || 1);
                this.frameworkOptions = result.frameworks || [];
            }
            catch (error) { if (sequence === this.loadSequence) this.error = error.message; }
            finally { if (sequence === this.loadSequence) this.loading = false; }
        },
        goToPage(page) { const target = Math.max(1, Math.min(Number(page), this.totalPages)); if (target === this.page) return; this.page = target; this.loadReports(false); window.scrollTo({ top: 0, behavior: 'auto' }); },
        async openReport(id) { await this.loadDetail(id); if (this.detail) { this.viewMode = 'reader'; window.scrollTo({ top: 0, behavior: 'auto' }); } },
        async loadDetail(id) {
            this.error = ''; this.expandedDetailChapters = {};
            try {
                this.detail = await api.getReport(id);
                if (window.setAppContext) window.setAppContext({ report_id: id, report_title: `${this.detail.stock_name || this.detail.ts_code} · ${this.detail.framework_name || this.detail.strategy}`, stock_code: this.detail.ts_code, report_summary: { score: this.detail.score, recommendation: this.detail.recommendation, confidence: this.detail.confidence, core_logic: this.detail.core_logic, risks: this.detail.risks } });
            } catch (error) { this.error = error.message; }
        },
        backToLibrary() { this.viewMode = 'library'; this.detail = null; this.compareReports = []; if (window.setAppContext) window.setAppContext({ research_path: '分析报告' }); },
        async confirmDelete(id) {
            if (!confirm('确定删除这份报告的结构化文件与 Markdown 正文？此操作不可撤销。')) return;
            try { await api.deleteReport(id); this.compareSelected = this.compareSelected.filter(item => item !== id); this.compareCandidates = this.compareCandidates.filter(item => item.id !== id); await this.loadReports(false); }
            catch (error) { this.error = error.message; }
        },
        toggleCompare(report) {
            if (this.compareSelected.includes(report.id)) { this.compareSelected = this.compareSelected.filter(id => id !== report.id); this.compareCandidates = this.compareCandidates.filter(item => item.id !== report.id); return; }
            if (!this.canSelectCompare(report)) return;
            this.compareSelected = [...this.compareSelected, report.id].slice(0, 2);
            this.compareCandidates = [...this.compareCandidates.filter(item => item.id !== report.id), report].slice(-2);
        },
        canSelectCompare(report) {
            if (this.compareSelected.includes(report.id)) return true;
            if (this.compareSelected.length >= 2) return false;
            if (!this.compareSelected.length) return true;
            return this.isComparable(this.selectedReports[0], report);
        },
        isComparable(left, right) { return Boolean(left && right && left.ts_code === right.ts_code && (left.cutoff_date === right.cutoff_date || left.strategy === right.strategy)); },
        comparisonLabel(reports) {
            if (reports.length !== 2) return '等待第二份可比较报告';
            if (reports[0].cutoff_date === reports[1].cutoff_date) return '同一截面 · 不同框架';
            if (reports[0].strategy === reports[1].strategy) return '同一框架 · 不同日期';
            return '不可比较';
        },
        async startCompare() {
            if (this.compareSelected.length !== 2) return;
            try {
                this.compareReports = await Promise.all(this.compareSelected.map(id => api.getReport(id)));
                if (!this.isComparable(...this.compareReports)) throw new Error('两份报告不满足同股、同日期或同框架的比较条件');
                this.viewMode = 'compare'; window.scrollTo({ top: 0, behavior: 'auto' });
                if (window.setAppContext) window.setAppContext({ research_path: '报告对比', comparison_type: this.compareModeLabel, reports: this.compareReports.map(item => ({ id: item.id, stock_code: item.ts_code, framework: item.framework_name, date: item.cutoff_date, score: item.score, recommendation: item.recommendation })) });
            } catch (error) { this.error = error.message; this.compareReports = []; }
        },
        clearCompare() { this.compareSelected = []; this.compareReports = []; this.compareCandidates = []; if (this.viewMode === 'compare') this.backToLibrary(); },
        chaptersFor(report) {
            const outputs = report?.full_data?.chapter_outputs || {};
            const order = [...(report?.chapter_order || []), ...Object.keys(outputs).filter(id => !(report?.chapter_order || []).includes(id))];
            return order.filter(id => outputs[id]).map(id => ({ id, title: report?.chapter_titles?.[id] || id, output: outputs[id] }));
        },
        comparisonChapters(report) { return this.chaptersFor(report); },
        toggleDetailChapter(id) { this.expandedDetailChapters = { ...this.expandedDetailChapters, [id]: !this.expandedDetailChapters[id] }; },
        scrollToAnchor(anchor) { const element = document.getElementById('report-' + anchor); if (element) { element.scrollIntoView({ behavior: 'smooth', block: 'start' }); element.classList.add('report-heading-flash'); setTimeout(() => element.classList.remove('report-heading-flash'), 1000); } },
        originLabel(value) { return ({ latest_judgement: '最新研判', historical_backtest: '历史回测样本', individual: '个股分析' })[value] || '个股分析'; },
        scoreClass(value) { if (value === null || value === undefined || value === '') return ''; const score = Number(value); return score >= 75 ? 'score-buy' : (score >= 50 ? 'score-watch' : (Number.isFinite(score) ? 'score-avoid' : '')); },
        recClass(value) { const text = String(value || ''); return /买入|建仓|值得深入/.test(text) ? 'rec-buy' : (/观望/.test(text) ? 'rec-watch' : (text ? 'rec-avoid' : '')); },
        isPlainRecord(value) { return Boolean(value && typeof value === 'object' && !Array.isArray(value)); },
        formatEvidence(value) { return typeof value === 'string' ? value : JSON.stringify(value, null, 2); },
        chapterOutputSummary(output) { if (!output || typeof output !== 'object') return ''; return Object.entries(output).filter(([, value]) => value !== null && value !== '' && typeof value !== 'object').slice(0, 2).map(([key, value]) => `${key}: ${String(value).slice(0, 28)}`).join(' · '); },
    },

    created() { this.loadReports(true); },
};
