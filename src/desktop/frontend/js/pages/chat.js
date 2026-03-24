/**
 * Chat assistant component — floating panel accessible from any page.
 *
 * Always mounted (not destroyed on page switch).
 */
const ChatAssistant = {
    props: ['currentPage', 'pageContext'],

    setup(props) {
        const isOpen = ref(false);
        const messages = ref([]);
        const inputText = ref('');
        const isLoading = ref(false);
        const messagesContainer = ref(null);

        function togglePanel() {
            isOpen.value = !isOpen.value;
            if (isOpen.value) {
                Vue.nextTick(() => scrollToBottom());
            }
        }

        function scrollToBottom() {
            const el = messagesContainer.value;
            if (el) {
                el.scrollTop = el.scrollHeight;
            }
        }

        async function sendMessage() {
            const text = inputText.value.trim();
            if (!text || isLoading.value) return;

            // Add user message
            messages.value.push({
                role: 'user',
                content: text,
                timestamp: Date.now() / 1000,
            });
            inputText.value = '';
            isLoading.value = true;

            Vue.nextTick(() => scrollToBottom());

            // Streaming SSE response — read context directly from global store
            const context = {
                page: props.currentPage || '',
                ...(window._appContext || {}),
            };
            const assistantMsg = {
                role: 'assistant',
                content: '',
                timestamp: Date.now() / 1000,
            };
            messages.value.push(assistantMsg);

            try {
                const response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text, context }),
                });

                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop() || '';

                    for (const line of lines) {
                        if (!line.startsWith('data: ')) continue;
                        const payload = line.slice(6).trim();
                        if (payload === '[DONE]') break;
                        try {
                            const data = JSON.parse(payload);
                            if (data.delta) {
                                assistantMsg.content += data.delta;
                                Vue.nextTick(() => scrollToBottom());
                            }
                        } catch (e) {}
                    }
                }
            } catch (err) {
                if (!assistantMsg.content) {
                    assistantMsg.content = '网络错误，请检查服务是否正常运行。' + (err.message || '');
                }
            } finally {
                isLoading.value = false;
                Vue.nextTick(() => scrollToBottom());
            }
        }

        async function clearHistory() {
            try {
                await apiFetch('/api/chat/history', { method: 'DELETE' });
                messages.value = [];
            } catch (err) {
                console.error('Failed to clear chat history:', err);
            }
        }

        async function loadHistory() {
            try {
                const data = await apiFetch('/api/chat/history');
                if (Array.isArray(data) && data.length > 0) {
                    messages.value = data;
                }
            } catch (err) {
                // Ignore — fresh start
            }
        }

        function handleKeydown(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        }

        function formatTime(ts) {
            if (!ts) return '';
            const d = new Date(ts * 1000);
            return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
        }

        function renderMd(text) {
            if (!text) return '';
            try {
                return marked.parse(text);
            } catch (e) {
                return text;
            }
        }

        onMounted(() => {
            loadHistory();
        });

        return {
            isOpen,
            messages,
            inputText,
            isLoading,
            messagesContainer,
            togglePanel,
            sendMessage,
            clearHistory,
            handleKeydown,
            formatTime,
            renderMd,
        };
    },

    template: `
<!-- Floating Action Button -->
<div class="chat-fab" @click="togglePanel" :class="{ 'chat-fab-hidden': isOpen }">
    <span class="chat-fab-icon">&#128172;</span>
</div>

<!-- Chat Panel -->
<transition name="chat-slide">
<div class="chat-panel" v-if="isOpen">
    <!-- Header -->
    <div class="chat-panel-header">
        <span class="chat-panel-title">&#129302; 智能助手</span>
        <div class="chat-panel-actions">
            <button class="chat-btn-clear" @click="clearHistory" title="清除对话">
                &#128465;
            </button>
            <button class="chat-btn-close" @click="togglePanel" title="收起">
                &#10005;
            </button>
        </div>
    </div>

    <!-- Messages -->
    <div class="chat-messages" ref="messagesContainer">
        <div v-if="messages.length === 0" class="chat-empty">
            <div class="chat-empty-icon">&#128075;</div>
            <div class="chat-empty-text">你好！我是投研助手，可以帮你：</div>
            <ul class="chat-empty-tips">
                <li>理解分析报告内容</li>
                <li>配置策略和算子</li>
                <li>解答平台使用问题</li>
            </ul>
        </div>

        <div
            v-for="(msg, idx) in messages"
            :key="idx"
            class="chat-msg"
            :class="'chat-msg-' + msg.role"
        >
            <div class="chat-msg-bubble" v-if="msg.role === 'user'">{{ msg.content }}</div>
            <div class="chat-msg-bubble chat-md" v-else v-html="renderMd(msg.content)"></div>
            <div class="chat-msg-time">{{ formatTime(msg.timestamp) }}</div>
        </div>

        <!-- Typing indicator -->
        <div v-if="isLoading" class="chat-msg chat-msg-assistant">
            <div class="chat-msg-bubble chat-typing">
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
            </div>
        </div>
    </div>

    <!-- Input -->
    <div class="chat-input-area">
        <textarea
            class="chat-input"
            v-model="inputText"
            @keydown="handleKeydown"
            placeholder="输入问题..."
            rows="1"
            :disabled="isLoading"
        ></textarea>
        <button class="chat-btn-send" @click="sendMessage" :disabled="isLoading || !inputText.trim()">
            &#10148;
        </button>
    </div>
</div>
</transition>
    `,
};
