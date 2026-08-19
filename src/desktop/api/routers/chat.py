"""
Chat assistant endpoints — floating AI assistant for the desktop tool.

Provides context-aware chat using the same LLM configured in settings.
Maintains independent page-scoped histories (max 20 messages each).
Supports streaming (SSE) for real-time token display.
"""
import json
import logging
import re
import time
from pathlib import Path
from threading import RLock
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Config path — set by main.py
_config_path: Optional[Path] = None
_project_root: Optional[Path] = None

# In-memory conversation histories, keyed by ``workspace:page``.
_histories: Dict[str, List[dict]] = {}
MAX_HISTORY = 20
_history_path: Optional[Path] = None
_history_lock = RLock()
_CONVERSATION_PATTERN = re.compile(r"^[A-Za-z0-9_-]+:[A-Za-z0-9_-]+$")
_LEGACY_CONVERSATION = "qualitative:analysis"


def _conversation_key(value: str) -> str:
    key = str(value or "").strip()
    if len(key) > 120 or not _CONVERSATION_PATTERN.fullmatch(key):
        raise HTTPException(status_code=400, detail="无效的对话标识")
    return key


def _normalize_messages(value: object) -> List[dict]:
    if not isinstance(value, list):
        return []
    messages = []
    for item in value[-MAX_HISTORY:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", ""))
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        try:
            timestamp = float(item.get("timestamp", 0.0))
        except (TypeError, ValueError):
            timestamp = 0.0
        messages.append({"role": role, "content": content, "timestamp": timestamp})
    return messages


def _save_history():
    """Persist every conversation to one external, atomically replaced file."""
    if not _history_path:
        return
    with _history_lock:
        try:
            _history_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": 1,
                "conversations": _histories,
            }
            temporary = _history_path.with_suffix(_history_path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(_history_path)
        except Exception as exc:
            logger.warning("Failed to save chat histories: %s", exc)


def _load_history():
    """Load histories and upgrade the legacy single-list representation."""
    global _histories
    with _history_lock:
        _histories = {}
        if not _history_path or not _history_path.exists():
            return
        try:
            stored = json.loads(_history_path.read_text(encoding="utf-8"))
            if isinstance(stored, list):
                _histories[_LEGACY_CONVERSATION] = _normalize_messages(stored)
                _save_history()
            elif isinstance(stored, dict):
                conversations = stored.get("conversations", {})
                if isinstance(conversations, dict):
                    for key, messages in conversations.items():
                        if _CONVERSATION_PATTERN.fullmatch(str(key)):
                            _histories[str(key)] = _normalize_messages(messages)
            total = sum(len(messages) for messages in _histories.values())
            logger.info(
                "Loaded %s chat messages across %s conversations from %s",
                total,
                len(_histories),
                _history_path,
            )
        except Exception as exc:
            logger.warning("Failed to load chat histories: %s", exc)
            _histories = {}


def set_config(
    config_path: Path,
    project_root: Path,
    history_path: Optional[Path] = None,
):
    """Set paths (called during startup)."""
    global _config_path, _project_root, _history_path
    _config_path = config_path
    _project_root = project_root
    _history_path = history_path or config_path.parent / "chat_history.json"
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
        "你是 Thesis Backtester 中的投研辅助 Agent。帮助用户理解报告、使用功能、设计算子和研究框架。\n\n"
        "## 工作边界\n"
        "- 算子是研究方法片段；一个分析方向可以组合多个算子。\n"
        "- 分析方向/章节之间由固定 DAG 调度。分析运行期间不得建议或尝试动态改变 DAG。\n"
        "- 中央结构化页面是权威状态，你负责辅助用户操作，不用自由 Agent 取代既有管线。\n"
        "- 人工操作和你的操作使用相同的现有 API、相同字段和相同权限。\n\n"
        "## 平台功能概览\n"
        "- **基础设施工作区**：维护数据、算子、研究框架和系统设置\n"
        "- **结构化投研工作区**：按固定章节 DAG 完成个股分析、最新批量研判、严格历史框架验证并管理报告\n"
        "- **截面筛选工作区**：维护纯数值策略，执行当前截面并验证历史前向收益；LLM 只辅助配置和解释\n\n"
        "## 结构化修改\n"
        "当且仅当用户明确要求创建或修改算子、研究框架或筛选策略，并且上下文足够时，在简短说明后输出一个 "
        "```app-action 代码块。代码块内只能是一个 JSON 对象或数组，不要把普通示例放进该代码块。\n"
        "每个对象格式：\n"
        '{"title":"修改摘要","description":"变化说明","method":"POST或PUT",'
        '"path":"现有API路径","body":{}}\n'
        "允许的写入路径只有：POST /api/operators、PUT /api/operators/{id}、"
        "POST /api/frameworks、PUT /api/frameworks/{name}、"
        "POST /api/research/screening-strategies、"
        "PUT /api/research/screening-strategies/{id}。不要省略 /api/research 前缀，也不要创造新的 API。\n"
        "算子更新 body 可包含 name、tags、data_needed、outputs、gate、weight、score_range、content。\n"
        "算子创建 body 必须包含 id、name、category，可包含上述其余字段。\n"
        "框架更新 body 可包含 display_name、version、operators_dir、analyst_role、chapters、synthesis；"
        "chapters 中每项包含 id、chapter、title、operators、dependencies。\n"
        "筛选策略 body 必须完整包含 name、description、definition；definition 必须包含 "
        "exclude_st、industry_cap、filters、ranking。filters 只能使用当前页面 available_fields 中的字段 id，"
        "每项格式为 field、enabled、mode 以及对应的 min/max 或 percentile_min/percentile_max；"
        "ranking 每项格式为 field、weight、direction、na_handling。修改策略使用当前 screening_strategy.id。\n"
        "注意字段单位：total_mv 和 circ_mv 的单位是万元，例如 50 亿元必须写成 500000 万元；"
        "market_cap_yi 和 circ_mv_yi 的单位才是亿元。修改数值前必须按 available_fields 的名称和说明换算，"
        "不得把自然语言中的元或亿元数值直接填入万元字段。\n"
        "输出 app-action 只表示生成了待应用修改，必须提示用户点击“应用修改”，不得声称已经提交或生效。\n"
        "不要直接修改正在执行的分析；框架修改只作用于后续运行。\n\n"
        "回答要简洁、具体。解释问题时只回答，不输出 app-action。"
    )

    page = context.get("page", "")
    extra_context = []

    if page == "reports" and context.get("report_id"):
        report_content = _load_report_context(context["report_id"])
        if report_content:
            extra_context.append(
                f"\n## 当前查看的报告（完整正文，共 {len(report_content)} 字符）\n"
                "以下内容是报告阅读器展示的完整正文。解读时必须覆盖相关章节与最终综合结论，"
                "不要只根据开头章节推断。\n"
                f"{report_content}"
            )

    if page == "analysis":
        parts = ["\n## 当前页面：个股分析"]
        if context.get("stock_code"):
            parts.append(f"用户正在分析的股票：{context['stock_code']}")
        if context.get("strategy"):
            parts.append(f"使用的策略：{context['strategy']}")
        extra_context.append("\n".join(parts))

    if page in {"qualitative-latest", "qualitative-validation"}:
        boundary = (
            "这是最新截面批量研判。筛选策略只负责数值候选池，固定研究框架负责逐股结论。"
            if page == "qualitative-latest"
            else "这是严格历史框架验证。必须比较市场、纯筛选池与框架研判层，且不能绕过历史可用性拦截。"
        )
        extra_context.append(f"\n## 当前页面：结构化投研批量流程\n{boundary}")

    if page == "operators":
        operators_summary = _load_operators_summary()
        if operators_summary:
            extra_context.append(f"\n## 可用算子列表\n{operators_summary}")

    if page == "frameworks":
        frameworks_summary = _load_frameworks_summary()
        if frameworks_summary:
            extra_context.append(f"\n## 可用策略框架\n{frameworks_summary}")

    # 前端传入当前选中对象或编辑草稿，使助手能够操作中央页面的同一状态。
    # 限制长度，避免意外把整个运行报告或过大的页面状态塞入上下文。
    visible_context = {
        key: value for key, value in context.items()
        if key not in {"report_content", "raw_data"}
    }
    try:
        context_json = json.dumps(visible_context, ensure_ascii=False, indent=2)
        if len(context_json) > 16000:
            context_json = context_json[:16000] + "\n...（页面上下文已截断）"
        extra_context.append(f"\n## 当前页面结构化上下文\n```json\n{context_json}\n```")
    except (TypeError, ValueError):
        pass

    return base + "\n".join(extra_context)


def _load_report_context(report_id: str) -> str:
    """Load the complete indexed report source for assistant context."""
    if not _project_root:
        return ""
    try:
        from src.desktop.api.services import report_index

        content = report_index.load_report_source_text(report_id, _project_root)
        logger.debug(
            "Loaded report context: report_id=%s chars=%s",
            report_id,
            len(content),
        )
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
    context: dict = Field(default_factory=dict)
    conversation_id: str = Field(
        default=_LEGACY_CONVERSATION,
        min_length=3,
        max_length=120,
        pattern=r"^[A-Za-z0-9_-]+:[A-Za-z0-9_-]+$",
    )


@router.post("")
async def chat(request: ChatRequest):
    """Send a message to the chat assistant (streaming SSE)."""
    logger.debug(f"Chat request: context={request.context}")
    settings = _load_llm_settings()
    conversation_id = _conversation_key(request.conversation_id)

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
    with _history_lock:
        history = _histories.setdefault(conversation_id, [])
        history.append(user_msg)
        del history[:-MAX_HISTORY]
    _save_history()

    # Build messages for LLM
    system_prompt = _build_system_prompt(request.context)
    messages = [{"role": "system", "content": system_prompt}]
    with _history_lock:
        history_snapshot = list(_histories.get(conversation_id, []))
    for msg in history_snapshot:
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
                max_tokens=4096,
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
        with _history_lock:
            history = _histories.setdefault(conversation_id, [])
            history.append({
                "role": "assistant",
                "content": full_reply,
                "timestamp": time.time(),
            })
            del history[:-MAX_HISTORY]
        _save_history()

        yield "data: [DONE]\n\n"

    return StreamingResponse(stream_response(), media_type="text/event-stream")


@router.get("/conversations")
async def list_conversations():
    """List persisted conversations without returning their message bodies."""
    with _history_lock:
        return [
            {
                "id": key,
                "message_count": len(messages),
                "updated_at": max(
                    (float(message.get("timestamp", 0.0)) for message in messages),
                    default=0.0,
                ),
            }
            for key, messages in sorted(_histories.items())
        ]


@router.get("/history")
async def get_history(conversation_id: str = _LEGACY_CONVERSATION):
    """Return chat history."""
    key = _conversation_key(conversation_id)
    with _history_lock:
        return [dict(message) for message in _histories.get(key, [])]


@router.delete("/history")
async def clear_history(conversation_id: str = _LEGACY_CONVERSATION):
    """Clear only the selected page conversation."""
    key = _conversation_key(conversation_id)
    with _history_lock:
        _histories.pop(key, None)
    _save_history()
    return {"message": "Chat history cleared", "conversation_id": key}
