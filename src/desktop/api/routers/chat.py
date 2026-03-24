"""
Chat assistant endpoints — floating AI assistant for the desktop tool.

Provides context-aware chat using the same LLM configured in settings.
Maintains conversation history in memory (max 20 messages).
Supports streaming (SSE) for real-time token display.
"""
import json
import logging
import time
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Config path — set by main.py
_config_path: Optional[Path] = None
_project_root: Optional[Path] = None

# In-memory conversation history
_history: List[dict] = []
MAX_HISTORY = 20
_history_path: Optional[Path] = None


def _save_history():
    """Persist history to disk."""
    if _history_path:
        try:
            _history_path.write_text(
                json.dumps(_history, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"Failed to save chat history: {e}")


def _load_history():
    """Load history from disk on startup."""
    global _history
    if _history_path and _history_path.exists():
        try:
            _history = json.loads(_history_path.read_text(encoding="utf-8"))
            logger.info(f"Loaded {len(_history)} chat messages from {_history_path}")
        except Exception as e:
            logger.warning(f"Failed to load chat history: {e}")
            _history = []


def set_config(config_path: Path, project_root: Path):
    """Set paths (called during startup)."""
    global _config_path, _project_root, _history_path
    _config_path = config_path
    _project_root = project_root
    _history_path = config_path.parent / "chat_history.json"
    _load_history()


def _load_llm_settings() -> dict:
    """Load LLM settings from config.json."""
    if _config_path and _config_path.exists():
        try:
            data = json.loads(_config_path.read_text(encoding="utf-8"))
            return {
                "api_key": data.get("llm_api_key", ""),
                "base_url": data.get("llm_base_url", "https://api.deepseek.com"),
                "model": data.get("llm_model", "deepseek-chat"),
                "temperature": data.get("temperature", 0.3),
            }
        except Exception as e:
            logger.warning(f"Failed to load config for chat: {e}")
    return {
        "api_key": "",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "temperature": 0.3,
    }


def _build_system_prompt(context: dict) -> str:
    """Build context-aware system prompt for the chat assistant."""
    base = (
        "你是投研分析工具的智能助手，帮助用户使用平台功能、理解分析报告、配置算子和策略。\n\n"
        "## 平台功能概览\n"
        "- **分析页**：输入股票代码和策略，启动AI深度分析，实时查看进度\n"
        "- **报告页**：查看和管理所有已完成的分析报告\n"
        "- **算子页**：浏览和编辑分析算子（.md文件），算子定义分析逻辑\n"
        "- **编排页**：管理策略框架，配置章节和算子组合\n"
        "- **数据页**：管理数据源状态和更新\n"
        "- **设置页**：配置LLM API连接参数\n\n"
        "回答要简洁实用，直接帮助用户解决问题。如果用户问的是报告内容相关的问题，基于提供的上下文回答。"
    )

    page = context.get("page", "")
    extra_context = []

    if page == "reports" and context.get("report_id"):
        report_content = _load_report_context(context["report_id"])
        if report_content:
            extra_context.append(f"\n## 当前查看的报告\n{report_content}")

    if page == "analysis":
        parts = ["\n## 当前页面：分析"]
        if context.get("stock_code"):
            parts.append(f"用户正在分析的股票：{context['stock_code']}")
        if context.get("strategy"):
            parts.append(f"使用的策略：{context['strategy']}")
        extra_context.append("\n".join(parts))

    if page == "operators":
        operators_summary = _load_operators_summary()
        if operators_summary:
            extra_context.append(f"\n## 可用算子列表\n{operators_summary}")

    if page == "frameworks":
        frameworks_summary = _load_frameworks_summary()
        if frameworks_summary:
            extra_context.append(f"\n## 可用策略框架\n{frameworks_summary}")

    return base + "\n".join(extra_context)


def _load_report_context(report_id: str) -> str:
    """Try to load report content for context injection.

    report_id format: 'strategy__stock_date_structured' (e.g., 'v6_enhanced__000001.SZ_2026-03-23_structured')
    """
    if not _project_root:
        return ""
    try:
        strategies_dir = _project_root / "strategies"
        if not strategies_dir.exists():
            return ""

        # Parse report_id: strategy__run_dir_structured
        strategy_name = None
        run_dir_name = None
        if "__" in report_id:
            strategy_name, rest = report_id.split("__", 1)
            # Remove '_structured' suffix to get directory name
            run_dir_name = rest.replace("_structured", "")

        if strategy_name and run_dir_name:
            # Direct lookup
            run_dir = strategies_dir / strategy_name / "live" / run_dir_name
            if run_dir.is_dir():
                for pattern in ["*_report.md", "report.md"]:
                    for report_file in run_dir.glob(pattern):
                        content = report_file.read_text(encoding="utf-8")
                        if len(content) > 4000:
                            content = content[:4000] + "\n...(报告内容已截断)"
                        return content

        # Fallback: search all directories
        for strategy_dir in strategies_dir.iterdir():
            if not strategy_dir.is_dir():
                continue
            live_dir = strategy_dir / "live"
            if not live_dir.exists():
                continue
            for run_dir in live_dir.iterdir():
                if not run_dir.is_dir():
                    continue
                if report_id in run_dir.name or run_dir.name in report_id:
                    for pattern in ["*_report.md", "report.md"]:
                        for report_file in run_dir.glob(pattern):
                            content = report_file.read_text(encoding="utf-8")
                            if len(content) > 4000:
                                content = content[:4000] + "\n...(报告内容已截断)"
                            return content
    except Exception as e:
        logger.warning(f"Failed to load report context: {e}")
    return ""


def _load_operators_summary() -> str:
    """Load a brief summary of all operators."""
    if not _project_root:
        return ""
    try:
        from src.engine.operators import OperatorRegistry
        registry = OperatorRegistry(operators_dir="operators/v2")
        operators = registry.list_all()
        lines = []
        for op in operators[:30]:
            lines.append(f"- {op.id}: {op.name}")
        if len(operators) > 30:
            lines.append(f"  ...共{len(operators)}个算子")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Failed to load operators summary: {e}")
        return ""


def _load_frameworks_summary() -> str:
    """Load a brief summary of all frameworks."""
    if not _project_root:
        return ""
    try:
        strategies_dir = _project_root / "strategies"
        if not strategies_dir.exists():
            return ""
        lines = []
        for strategy_dir in sorted(strategies_dir.iterdir()):
            yaml_path = strategy_dir / "strategy.yaml"
            if not yaml_path.exists():
                continue
            try:
                from src.engine.config import StrategyConfig
                config = StrategyConfig.from_yaml(yaml_path)
                chapter_defs = config.get_chapter_defs()
                total_ops = sum(len(ch.get("operators", [])) for ch in chapter_defs)
                lines.append(
                    f"- {strategy_dir.name}: {config.name} "
                    f"(v{config.version}, {len(chapter_defs)}章, {total_ops}算子)"
                )
            except Exception:
                lines.append(f"- {strategy_dir.name}: (加载失败)")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Failed to load frameworks summary: {e}")
        return ""


class ChatRequest(BaseModel):
    message: str
    context: dict = {}


@router.post("")
async def chat(request: ChatRequest):
    """Send a message to the chat assistant (streaming SSE)."""
    logger.debug(f"Chat request: context={request.context}")
    settings = _load_llm_settings()

    if not settings["api_key"]:
        async def error_stream():
            yield f"data: {json.dumps({'delta': '尚未配置 LLM API Key，请先到「设置」页面配置 API 连接参数。'})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    # Add user message to history
    user_msg = {
        "role": "user",
        "content": request.message,
        "timestamp": time.time(),
    }
    _history.append(user_msg)

    # Trim history
    while len(_history) > MAX_HISTORY:
        _history.pop(0)
    _save_history()

    # Build messages for LLM
    system_prompt = _build_system_prompt(request.context)
    messages = [{"role": "system", "content": system_prompt}]
    for msg in _history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    async def stream_response():
        full_reply = ""
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=settings["api_key"],
                base_url=settings["base_url"],
            )
            response = client.chat.completions.create(
                model=settings["model"],
                messages=messages,
                max_tokens=2048,
                temperature=settings["temperature"],
                stream=True,
            )
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    delta = chunk.choices[0].delta.content
                    full_reply += delta
                    yield f"data: {json.dumps({'delta': delta})}\n\n"
        except Exception as e:
            logger.error(f"Chat LLM stream failed: {e}")
            error_msg = f"调用 LLM 失败：{str(e)[:200]}"
            full_reply = error_msg
            yield f"data: {json.dumps({'delta': error_msg})}\n\n"

        # Save assistant reply to history
        _history.append({
            "role": "assistant",
            "content": full_reply,
            "timestamp": time.time(),
        })
        while len(_history) > MAX_HISTORY:
            _history.pop(0)
        _save_history()

        yield "data: [DONE]\n\n"

    return StreamingResponse(stream_response(), media_type="text/event-stream")


@router.get("/history")
async def get_history():
    """Return chat history."""
    return [
        {"role": msg["role"], "content": msg["content"], "timestamp": msg["timestamp"]}
        for msg in _history
    ]


@router.delete("/history")
async def clear_history():
    """Clear chat history."""
    _history.clear()
    _save_history()
    return {"message": "Chat history cleared"}
