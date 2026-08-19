/**
 * Settings page component.
 */
const SettingsPage = {
    template: `
<div class="page-settings">
    <workspace-page-header eyebrow="基础设施 · 系统配置" title="系统设置" description="维护数据口径、模型连接与本地自动更新策略。">
        <template #meta><span class="page-header-chip" v-if="selectedProvider"><span>数据口径</span>{{ selectedProvider.label }}</span></template>
    </workspace-page-header>

    <div class="card">
        <div class="settings-section">
            <h3>数据源配置</h3>

            <div class="setting-item">
                <label>当前数据口径</label>
                <select v-model="form.data_provider" @change="onProviderChange">
                    <option v-for="provider in settings.data_providers || []" :key="provider.name" :value="provider.name">
                        {{ provider.label }}（{{ provider.access_mode }}）
                    </option>
                </select>
                <div class="setting-hint" v-if="selectedProvider">
                    {{ selectedProvider.description }}
                </div>
                <div class="setting-hint" v-if="selectedProvider && selectedProvider.limitations.length">
                    限制：{{ selectedProvider.limitations.join('；') }}
                </div>
            </div>

            <div class="setting-item" v-if="form.data_provider === 'tushare'">
                <label>Tushare Token</label>
                <div class="input-with-status">
                    <input
                        :type="showTushareToken ? 'text' : 'password'"
                        v-model="form.tushare_token"
                        :placeholder="tushareTokenPlaceholder"
                    />
                    <button class="btn btn-small" @click="showTushareToken = !showTushareToken">
                        {{ showTushareToken ? '隐藏' : '显示' }}
                    </button>
                    <span class="api-key-status" :class="settings.tushare_token_set ? 'set' : 'unset'">
                        {{ settings.tushare_token_set ? '✓ 已配置' : '✗ 未配置' }}
                    </span>
                </div>
                <div class="setting-hint">Token 只保存在本机 data/data_config.json，不会提交到仓库。</div>
            </div>

            <div class="setting-item">
                <label>历史数据起始日</label>
                <input type="date" v-model="form.data_start_date" />
                <div class="setting-hint">首次初始化未指定日期时使用；修改后不会自动删除已有数据。</div>
            </div>

            <div class="setting-item">
                <label class="checkbox-label">
                    <input type="checkbox" v-model="form.auto_update_enabled" :disabled="selectedProvider && !selectedProvider.supports_download" />
                    启用每日自动更新
                </label>
                <div class="setting-hint" v-if="selectedProvider && !selectedProvider.supports_download">
                    即时分析数据源不建立本地库，无需自动更新。
                </div>
            </div>

            <div class="setting-item" v-if="form.auto_update_enabled">
                <label>自动更新时间</label>
                <input type="time" v-model="form.auto_update_time" />
                <label class="checkbox-label" style="margin-top: 10px;">
                    <input type="checkbox" v-model="form.auto_update_financials" />
                    同步检查财务数据增量
                </label>
                <div class="setting-hint">应用运行期间到点触发；若当天错过时间，下一次启动后会补触发一次。</div>
            </div>

            <button class="btn btn-secondary" @click="testDataProvider" :disabled="testingProvider">
                {{ testingProvider ? '测试中...' : '测试数据源连接' }}
            </button>
            <span class="save-status" v-if="providerTestResult" :class="providerTestResult.success ? 'success' : 'error'">
                {{ providerTestResult.success ? '连接正常' : (providerTestResult.error || providerTestResult.message) }}
            </span>
        </div>

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
                <label>单次最大输出 Token</label>
                <input type="number" v-model.number="form.max_tokens" min="1024" max="65536" step="1024" />
                <div class="setting-hint">
                    Agent 章节和综合研判共用；报告被截断时可适当提高
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

        <div class="settings-section network-settings-section">
            <h3>网络访问</h3>

            <div class="setting-item">
                <label class="checkbox-label">
                    <input type="checkbox" v-model="form.lan_access_enabled" />
                    允许局域网设备访问
                </label>
                <div class="setting-hint">默认仅本机可访问。开启后，其他设备必须使用访问口令登录。</div>
            </div>

            <div class="network-settings-body" v-if="form.lan_access_enabled">
                <div class="network-security-notice">
                    局域网用户登录后与本机用户具有相同的研究、配置和任务操作权限。
                </div>

                <div class="setting-item">
                    <label>访问地址</label>
                    <div class="network-url-list" v-if="settings.lan_access_urls?.length">
                        <div class="network-url-row" v-for="url in settings.lan_access_urls" :key="url">
                            <code>{{ url }}</code>
                            <button class="btn btn-small" type="button" @click="copyNetworkValue(url)">复制</button>
                        </div>
                    </div>
                    <div class="setting-hint" v-else>暂未检测到可用的局域网 IPv4 地址。</div>
                    <div class="setting-hint">若其他设备无法打开，请在 Windows 防火墙中允许本应用访问专用网络。</div>
                </div>

                <div class="setting-item">
                    <label>访问口令</label>
                    <div class="network-token-actions">
                        <span class="api-key-status" :class="settings.lan_access_token_set ? 'set' : 'unset'">
                            {{ settings.lan_access_token_set ? '已生成' : '尚未生成' }}
                        </span>
                        <button class="btn btn-small" type="button" @click="resetNetworkToken" :disabled="resettingNetworkToken">
                            {{ resettingNetworkToken ? '正在生成…' : '重置口令' }}
                        </button>
                    </div>
                    <div class="setting-hint">口令仅在创建或重置时显示一次；遗忘后可直接重置。</div>
                </div>

                <div class="network-token-reveal" v-if="generatedNetworkToken">
                    <div><strong>新访问口令</strong><span>请现在复制保存</span></div>
                    <code>{{ generatedNetworkToken }}</code>
                    <button class="btn btn-small" type="button" @click="copyNetworkValue(generatedNetworkToken)">复制口令</button>
                </div>
            </div>

            <div class="network-restart-notice" v-if="settings.lan_access_restart_required">
                {{ networkRestartMessage }}
            </div>
            <div class="setting-hint" v-else-if="settings.lan_access_active">局域网访问已在本次启动中生效。</div>
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
                <span>Thesis Backtester</span>
            </div>
            <div class="about-row">
                <span class="about-label">版本</span>
                <span>{{ settings.app_display_version || '—' }}</span>
            </div>
            <div class="about-row">
                <span class="about-label">引擎</span>
                <span>结构化投研引擎</span>
            </div>
            <div class="about-row">
                <span class="about-label">数据源</span>
                <span>{{ selectedProvider ? selectedProvider.label : form.data_provider }}</span>
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
                max_tokens: 8192,
                concurrency: 3,
                data_provider: 'baostock',
                tushare_token: '',
                data_start_date: '2015-01-01',
                auto_update_enabled: false,
                auto_update_time: '18:30',
                auto_update_financials: true,
                lan_access_enabled: false,
            },
            showApiKey: false,
            showTushareToken: false,
            saving: false,
            saveMessage: '',
            saveSuccess: false,
            testing: false,
            testResult: null,
            testingProvider: false,
            providerTestResult: null,
            generatedNetworkToken: '',
            resettingNetworkToken: false,
        };
    },

    computed: {
        apiKeyPlaceholder() {
            if (this.settings.llm_api_key_set) {
                return this.settings.llm_api_key_masked || '已配置（留空保持不变）';
            }
            return '输入 API Key...';
        },
        tushareTokenPlaceholder() {
            if (this.settings.tushare_token_set) {
                return this.settings.tushare_token_masked || '已配置（留空保持不变）';
            }
            return '输入 Tushare Token...';
        },
        selectedProvider() {
            return (this.settings.data_providers || []).find(p => p.name === this.form.data_provider) || null;
        },
        networkRestartMessage() {
            return this.form.lan_access_enabled
                ? '设置已保存，重启软件后局域网访问才会生效。'
                : '设置已保存；本次运行仍会保持口令保护，重启后关闭局域网访问。';
        },
    },

    async created() {
        await this.loadSettings();
    },

    methods: {
        onProviderChange() {
            if (this.selectedProvider && !this.selectedProvider.supports_download) {
                this.form.auto_update_enabled = false;
            }
            this.providerTestResult = null;
        },

        async loadSettings() {
            try {
                this.settings = await api.getSettings();
                // Pre-fill form with current values (except API key which is masked)
                this.form.llm_base_url = this.settings.llm_base_url || '';
                this.form.llm_model = this.settings.llm_model || '';
                this.form.temperature = this.settings.temperature ?? 0.3;
                this.form.max_tokens = this.settings.max_tokens || 8192;
                this.form.concurrency = this.settings.concurrency || 3;
                this.form.data_provider = this.settings.data_provider || 'baostock';
                this.form.data_start_date = this.settings.data_start_date || '2015-01-01';
                this.form.auto_update_enabled = !!this.settings.auto_update_enabled;
                this.form.auto_update_time = this.settings.auto_update_time || '18:30';
                this.form.auto_update_financials = this.settings.auto_update_financials !== false;
                this.form.lan_access_enabled = !!this.settings.lan_access_enabled;
                this.form.llm_api_key = '';  // Don't pre-fill key
                this.form.tushare_token = '';
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
                payload.max_tokens = this.form.max_tokens;
                payload.concurrency = this.form.concurrency;
                payload.data_provider = this.form.data_provider;
                payload.data_start_date = this.form.data_start_date;
                payload.auto_update_enabled = this.form.auto_update_enabled;
                payload.auto_update_time = this.form.auto_update_time;
                payload.auto_update_financials = this.form.auto_update_financials;
                payload.lan_access_enabled = this.form.lan_access_enabled;
                if (this.form.tushare_token) {
                    payload.tushare_token = this.form.tushare_token;
                }

                const response = await api.updateSettings(payload);
                if (response.lan_access_token) {
                    this.generatedNetworkToken = response.lan_access_token;
                }
                delete response.lan_access_token;
                this.settings = response;
                this.saveSuccess = true;
                this.saveMessage = this.settings.lan_access_restart_required
                    ? '设置已保存，重启后生效'
                    : '设置已保存';
                this.form.llm_api_key = '';  // Clear key field after save
                this.form.tushare_token = '';
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

        async resetNetworkToken() {
            this.resettingNetworkToken = true;
            this.saveMessage = '';
            try {
                const response = await api.updateSettings({ reset_lan_access_token: true });
                this.generatedNetworkToken = response.lan_access_token || '';
                delete response.lan_access_token;
                this.settings = response;
                this.saveSuccess = true;
                this.saveMessage = '已生成新的访问口令';
            } catch (error) {
                this.saveSuccess = false;
                this.saveMessage = `口令重置失败: ${error.message}`;
            } finally {
                this.resettingNetworkToken = false;
            }
        },

        async copyNetworkValue(value) {
            try {
                await navigator.clipboard.writeText(value);
            } catch (_) {
                const textarea = document.createElement('textarea');
                textarea.value = value;
                textarea.style.position = 'fixed';
                textarea.style.opacity = '0';
                document.body.appendChild(textarea);
                textarea.select();
                document.execCommand('copy');
                textarea.remove();
            }
            this.saveSuccess = true;
            this.saveMessage = '已复制';
        },

        async testDataProvider() {
            this.testingProvider = true;
            this.providerTestResult = null;
            try {
                await this.saveSettings();
                this.providerTestResult = await api.testDataProvider(this.form.data_provider);
            } catch (e) {
                this.providerTestResult = { success: false, error: e.message };
            } finally {
                this.testingProvider = false;
            }
        },
    },
};
