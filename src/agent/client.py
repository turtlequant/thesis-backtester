"""
LLM 客户端 — OpenAI 兼容格式

支持任意 OpenAI chat completions 兼容的 API provider。
配置通过环境变量或 strategy.yaml 的 llm 节传入。

用法:
    client = LLMClient.from_config(strategy_config)
    response = await client.chat(messages, tools)
"""
import asyncio
import os
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from openai import AsyncOpenAI, APIError, APIConnectionError, RateLimitError, APITimeoutError

logger = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    """LLM 连接配置"""
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o"
    max_tokens: int = 8192
    temperature: float = 0.1

    @classmethod
    def from_strategy(cls, config) -> "LLMConfig":
        """从 StrategyConfig 加载 LLM 配置"""
        llm_raw = config.raw.get("llm", {})

        # 环境变量优先，YAML 中配置的是 env var 的名称
        base_url_env = llm_raw.get("base_url_env", "LLM_BASE_URL")
        api_key_env = llm_raw.get("api_key_env", "LLM_API_KEY")

        base_url = os.environ.get(base_url_env, llm_raw.get("base_url", "https://api.openai.com/v1"))
        api_key = os.environ.get(api_key_env, "")

        if not api_key:
            raise ValueError(
                f"LLM API key not found. Set environment variable '{api_key_env}' "
                f"or configure llm.api_key_env in strategy.yaml"
            )

        # model: 环境变量 LLM_MODEL > YAML > 默认 gpt-4o
        model_env = llm_raw.get("model_env", "LLM_MODEL")
        model = os.environ.get(model_env) or llm_raw.get("model", "gpt-4o")

        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            max_tokens=llm_raw.get("max_tokens", 8192),
            temperature=llm_raw.get("temperature", 0.1),
        )


class LLMClient:
    """OpenAI 兼容的异步 LLM 客户端"""

    def __init__(self, llm_config: LLMConfig):
        self.config = llm_config
        self._client = AsyncOpenAI(
            base_url=llm_config.base_url,
            api_key=llm_config.api_key,
        )

    @classmethod
    def from_strategy(cls, config) -> "LLMClient":
        """从 StrategyConfig 创建客户端"""
        llm_config = LLMConfig.from_strategy(config)
        logger.info(f"LLM: {llm_config.base_url} / {llm_config.model}")
        return cls(llm_config)

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_retries: int = 3,
        timeout: float = 600,
    ) -> Any:
        """
        发送聊天请求（带重试和超时）

        Args:
            messages: OpenAI 格式的消息列表
            tools: OpenAI 格式的工具定义列表
            max_retries: 最大重试次数
            timeout: 单次请求超时秒数

        Returns:
            ChatCompletion response
        """
        kwargs = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "timeout": timeout,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                response = await self._client.chat.completions.create(**kwargs)
                return response
            except RateLimitError as e:
                last_error = e
                wait = min(2 ** attempt * 5, 60)  # 10s, 20s, 40s (max 60s)
                logger.warning(f"限流，{wait}s 后重试 (第{attempt}次): {e}")
                await asyncio.sleep(wait)
            except (APIConnectionError, APITimeoutError) as e:
                last_error = e
                wait = 2 ** attempt * 2  # 4s, 8s, 16s
                logger.warning(f"连接/超时错误，{wait}s 后重试 (第{attempt}次): {e}")
                await asyncio.sleep(wait)
            except APIError as e:
                # 5xx 服务端错误可重试，4xx 客户端错误不重试
                if e.status_code and e.status_code >= 500:
                    last_error = e
                    wait = 2 ** attempt * 3
                    logger.warning(f"服务端错误 {e.status_code}，{wait}s 后重试 (第{attempt}次)")
                    await asyncio.sleep(wait)
                else:
                    raise  # 400/401/403 等直接抛出

        raise last_error  # 重试耗尽

    async def close(self):
        """关闭客户端连接"""
        await self._client.close()
