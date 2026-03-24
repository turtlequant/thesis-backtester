/**
 * Settings page component.
 */
const SettingsPage = {
    template: `
<div class="page-settings">
    <div class="card">
        <h2>设置</h2>

        <div class="settings-section">
            <h3>LLM 配置</h3>

            <div class="setting-item">
                <label>API Key</label>
                <div class="input-with-status">
                    <input
                        :type="showApiKey ? 'text' : 'password'"
                        v-model="form.llm_api_key"
                        :placeholder="apiKeyPlaceholder"
                    />
                    <button class="btn btn-small" @click="showApiKey = !showApiKey">
                        {{ showApiKey ? '隐藏' : '显示' }}
                    </button>
                    <span class="api-key-status" :class="settings.llm_api_key_set ? 'set' : 'unset'">
                        {{ settings.llm_api_key_set ? '✓ 已配置' : '✗ 未配置' }}
                    </span>
                </div>
                <div class="setting-hint" v-if="!settings.llm_api_key_set">
                    请填入 LLM API Key（如 DeepSeek），分析功能依赖此配置
                </div>
                <div class="setting-hint" v-else>
                    留空保存 = 保持当前 Key 不变；填入新 Key = 覆盖更新
                </div>
            </div>

            <div class="setting-item">
                <label>Base URL</label>
                <input
                    type="text"
                    v-model="form.llm_base_url"
                    placeholder="https://api.deepseek.com"
                />
                <div class="setting-hint">
                    支持 OpenAI 兼容格式的 API 端点
                </div>
            </div>

            <div class="setting-item">
                <label>模型</label>
                <input
                    type="text"
                    v-model="form.llm_model"
                    placeholder="deepseek-chat"
                />
                <div class="setting-hint">
                    推荐: deepseek-chat, gpt-4o
                </div>
            </div>

            <div class="setting-item">
                <label>温度 (Temperature)</label>
                <div class="temp-input-row">
                    <input
                        type="range"
                        v-model.number="form.temperature"
                        min="0"
                        max="1.5"
                        step="0.1"
                        class="temp-slider"
                    />
                    <span class="temp-value">{{ form.temperature.toFixed(1) }}</span>
                </div>
                <div class="setting-hint">
                    0 = 确定性最高（推荐投研分析），1.0+ = 更有创造性
                </div>
            </div>

            <div class="setting-item">
                <label>并发数</label>
                <input
                    type="number"
                    v-model.number="form.concurrency"
                    min="1"
                    max="10"
                />
                <div class="setting-hint">
                    同时分析的章节数 (1-10)
                </div>
            </div>
        </div>

        <div class="settings-actions">
            <button class="btn btn-primary" @click="saveSettings" :disabled="saving">
                {{ saving ? '保存中...' : '保存设置' }}
            </button>
            <button class="btn btn-secondary" @click="testConnection" :disabled="testing" style="margin-left: 8px;">
                {{ testing ? '测试中...' : '测试连接' }}
            </button>
            <span class="save-status" v-if="saveMessage" :class="saveSuccess ? 'success' : 'error'">
                {{ saveMessage }}
            </span>
        </div>
        <div class="test-result-card" v-if="testResult">
            <div class="test-result-header" :class="testResult.success ? 'success' : 'error'">
                {{ testResult.success ? '✓ 连接成功' : '✗ 连接失败' }}
            </div>
            <div class="test-result-detail" v-if="testResult.model">模型: {{ testResult.model }}</div>
            <div class="test-result-detail" v-if="testResult.reply">回复: {{ testResult.reply }}</div>
            <div class="test-result-detail" v-if="testResult.elapsed">耗时: {{ testResult.elapsed }}s</div>
            <div class="test-result-detail error" v-if="testResult.error">错误: {{ testResult.error }}</div>
        </div>
    </div>

    <div class="card">
        <h3>关于</h3>
        <div class="about-info">
            <div class="about-row">
                <span class="about-label">应用名称</span>
                <span>投研分析工具</span>
            </div>
            <div class="about-row">
                <span class="about-label">版本</span>
                <span>1.0.0</span>
            </div>
            <div class="about-row">
                <span class="about-label">引擎</span>
                <span>Thesis-Backtester Engine</span>
            </div>
            <div class="about-row">
                <span class="about-label">数据源</span>
                <span>AKShare (免费)</span>
            </div>
        </div>
    </div>
</div>
    `,

    data() {
        return {
            settings: {},
            form: {
                llm_api_key: '',
                llm_base_url: '',
                llm_model: '',
                temperature: 0.3,
                concurrency: 3,
            },
            showApiKey: false,
            saving: false,
            saveMessage: '',
            saveSuccess: false,
            testing: false,
            testResult: null,
        };
    },

    computed: {
        apiKeyPlaceholder() {
            if (this.settings.llm_api_key_set) {
                return this.settings.llm_api_key_masked || '已配置（留空保持不变）';
            }
            return '输入 API Key...';
        },
    },

    async created() {
        await this.loadSettings();
    },

    methods: {
        async loadSettings() {
            try {
                this.settings = await api.getSettings();
                // Pre-fill form with current values (except API key which is masked)
                this.form.llm_base_url = this.settings.llm_base_url || '';
                this.form.llm_model = this.settings.llm_model || '';
                this.form.temperature = this.settings.temperature ?? 0.3;
                this.form.concurrency = this.settings.concurrency || 3;
                this.form.llm_api_key = '';  // Don't pre-fill key
            } catch (e) {
                console.error('Failed to load settings:', e);
            }
        },

        async saveSettings() {
            this.saving = true;
            this.saveMessage = '';

            try {
                // Only send non-empty fields
                const payload = {};
                if (this.form.llm_api_key) {
                    payload.llm_api_key = this.form.llm_api_key;
                }
                if (this.form.llm_base_url) {
                    payload.llm_base_url = this.form.llm_base_url;
                }
                if (this.form.llm_model) {
                    payload.llm_model = this.form.llm_model;
                }
                payload.temperature = this.form.temperature;
                payload.concurrency = this.form.concurrency;

                this.settings = await api.updateSettings(payload);
                this.saveSuccess = true;
                this.saveMessage = '设置已保存';
                this.form.llm_api_key = '';  // Clear key field after save
            } catch (e) {
                this.saveSuccess = false;
                this.saveMessage = `保存失败: ${e.message}`;
            } finally {
                this.saving = false;
                // Clear message after 3 seconds
                setTimeout(() => { this.saveMessage = ''; }, 3000);
            }
        },

        async testConnection() {
            this.testing = true;
            this.testResult = null;
            // Auto save before testing
            try {
                await this.saveSettings();
            } catch (e) {
                // Continue even if save fails
            }
            try {
                const resp = await fetch('/api/settings/test-llm');
                const data = await resp.json();
                this.testResult = data;
            } catch (e) {
                this.testResult = { success: false, error: e.message };
            } finally {
                this.testing = false;
            }
        },
    },
};
