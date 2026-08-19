/** Product guide shared by first-run onboarding and the permanent help entry. */
const ProductGuide = {
    props: {
        open: { type: Boolean, default: false },
        mode: { type: String, default: 'full' },
        guide: { type: Object, default: () => ({}) },
        currentPage: { type: String, default: '' },
    },
    emits: ['close', 'show-full'],

    setup(props, { emit }) {
        const contentContainer = ref(null);
        const activeSection = ref('overview');
        const pageSections = {
            datasources: 'infrastructure',
            factors: 'infrastructure',
            operators: 'engine',
            frameworks: 'engine',
            settings: 'infrastructure',
            analysis: 'qualitative',
            'qualitative-latest': 'qualitative',
            'qualitative-validation': 'qualitative',
            reports: 'qualitative',
            'screening-strategies': 'cross_section',
            'screening-current': 'cross_section',
            'screening-backtest': 'cross_section',
        };

        function renderMd(content) {
            try {
                return marked.parse(content || '');
            } catch (_) {
                return content || '';
            }
        }

        function parseSections(source) {
            const heading = /^##\s+(.+?)\s+\{#([A-Za-z0-9_-]+)\}\s*$/gm;
            const matches = [...source.matchAll(heading)];
            return matches.map((match, index) => {
                const bodyStart = match.index + match[0].length;
                const bodyEnd = index + 1 < matches.length ? matches[index + 1].index : source.length;
                const body = source.slice(bodyStart, bodyEnd)
                    .replace(/<!--\s*guide:intro:(?:start|end)\s*-->/g, '')
                    .trim();
                return {
                    id: match[2],
                    title: match[1],
                    html: renderMd(body),
                };
            });
        }

        const introSections = computed(() => parseSections(props.guide.intro || ''));
        const sections = computed(() => parseSections(props.guide.content || ''));

        function scrollToSection(id, behavior = 'smooth') {
            activeSection.value = id;
            Vue.nextTick(() => {
                const container = contentContainer.value;
                const target = container?.querySelector(`[data-guide-section="${id}"]`);
                if (target) target.scrollIntoView({ behavior, block: 'start' });
            });
        }

        function close() {
            emit('close');
        }

        function showFull() {
            emit('show-full');
        }

        Vue.watch(
            () => [props.open, props.mode, props.currentPage, props.guide.version],
            ([open, mode]) => {
                if (!open || mode !== 'full') return;
                const section = pageSections[props.currentPage] || 'overview';
                scrollToSection(section, 'auto');
            },
        );

        return {
            contentContainer,
            activeSection,
            introSections,
            sections,
            close,
            showFull,
            scrollToSection,
        };
    },

    template: `
<div v-if="open" class="guide-overlay" @click.self="close">
    <section class="guide-dialog" :class="{ 'guide-dialog-intro': mode === 'intro' }">
        <header class="guide-header">
            <div>
                <div class="guide-eyebrow">PRODUCT GUIDE · v{{ guide.version }}</div>
                <h1>{{ mode === 'intro' ? '认识 Thesis Backtester' : '功能指引' }}</h1>
                <p>{{ mode === 'intro' ? '用确定性研究流程承载方法，让 LLM 做辅助。' : '理解每个工作区在完整研究流程中的位置。' }}</p>
            </div>
            <button class="guide-close" @click="close" aria-label="关闭功能指引">×</button>
        </header>

        <template v-if="mode === 'intro'">
            <div class="guide-intro-content">
                <section class="guide-intro-card" v-for="(section, index) in introSections" :key="section.id">
                    <div class="guide-intro-number">0{{ index + 1 }}</div>
                    <h2>{{ section.title }}</h2>
                    <div class="guide-markdown" v-html="section.html"></div>
                </section>
            </div>
            <footer class="guide-intro-footer">
                <span>当前版本只会自动展示一次，之后可从左下角重新打开。</span>
                <div class="guide-intro-actions">
                    <button class="btn btn-secondary" @click="showFull">查看完整指引</button>
                    <button class="btn btn-primary" @click="close">开始使用</button>
                </div>
            </footer>
        </template>

        <div v-else class="guide-body">
            <nav class="guide-toc" aria-label="功能指引目录">
                <button
                    v-for="section in sections"
                    :key="section.id"
                    :class="{ active: activeSection === section.id }"
                    @click="scrollToSection(section.id)"
                >{{ section.title }}</button>
            </nav>
            <article class="guide-content" ref="contentContainer">
                <section
                    v-for="section in sections"
                    :key="section.id"
                    class="guide-section"
                    :data-guide-section="section.id"
                >
                    <h2>{{ section.title }}</h2>
                    <div class="guide-markdown" v-html="section.html"></div>
                </section>
            </article>
        </div>
    </section>
</div>
    `,
};
