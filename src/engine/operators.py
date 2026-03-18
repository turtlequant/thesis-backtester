"""
分析算子注册表

加载、解析、管理分析算子（Operator）。
算子 = Markdown 文件 + YAML frontmatter，是独立的非结构化分析指令单元。

解析优先级:
    1. strategies/<name>/operators/  (策略私有)
    2. operators/                     (全局共享)

用法:
    registry = OperatorRegistry(config)
    op = registry.get("debt_structure")
    ops = registry.resolve(["debt_structure", "cycle_analysis"])
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from src.data.settings import PROJECT_ROOT

logger = logging.getLogger(__name__)


@dataclass
class OperatorOutput:
    """算子输出字段定义"""
    field: str          # 字段名
    type: str = "str"   # 类型: str, float, bool, int, list
    desc: str = ""      # 字段说明


@dataclass
class Operator:
    """一个分析算子 (非结构化/定性)"""
    id: str
    name: str
    tags: List[str] = field(default_factory=list)
    data_needed: List[str] = field(default_factory=list)
    outputs: List[OperatorOutput] = field(default_factory=list)
    weight: float = 1.0         # LLM 评分权重 (多算子加权平均)
    score_range: str = "0-100"  # 评分范围
    content: str = ""           # markdown 正文 (不含 frontmatter)
    source_path: Path = None    # 来源文件路径

    @classmethod
    def from_file(cls, path: Path) -> Optional["Operator"]:
        """从 markdown 文件解析算子"""
        try:
            text = path.read_text(encoding='utf-8')
        except Exception as e:
            logger.warning(f"无法读取算子文件 {path}: {e}")
            return None

        # 分离 frontmatter 和正文
        meta, body = _split_frontmatter(text)
        if not meta:
            logger.warning(f"算子文件缺少 frontmatter: {path}")
            return None

        op_id = meta.get('id', path.stem)

        # 解析 outputs 字段定义
        raw_outputs = meta.get('outputs', [])
        outputs = []
        for item in raw_outputs:
            if isinstance(item, dict) and 'field' in item:
                outputs.append(OperatorOutput(
                    field=item['field'],
                    type=item.get('type', 'str'),
                    desc=item.get('desc', ''),
                ))

        return cls(
            id=op_id,
            name=meta.get('name', op_id),
            tags=meta.get('tags', []),
            data_needed=meta.get('data_needed', []),
            outputs=outputs,
            weight=float(meta.get('weight', 1.0)),
            score_range=meta.get('score_range', '0-100'),
            content=body.strip(),
            source_path=path,
        )


def _split_frontmatter(text: str) -> tuple:
    """分离 YAML frontmatter 和 Markdown 正文"""
    text = text.strip()
    if not text.startswith('---'):
        return {}, text

    # 找第二个 ---
    end = text.find('---', 3)
    if end == -1:
        return {}, text

    front = text[3:end].strip()
    body = text[end + 3:]

    try:
        meta = yaml.safe_load(front) or {}
    except yaml.YAMLError:
        meta = {}

    return meta, body


class OperatorRegistry:
    """算子注册表 — 扫描并管理所有可用算子"""

    def __init__(self, strategy_dir: Path = None, operators_dir: str = None):
        """
        Args:
            strategy_dir: 策略目录 (可选, 用于加载策略私有算子)
            operators_dir: 算子版本目录 (如 'operators/v1')，None 使用默认 'operators/'
        """
        self._operators: Dict[str, Operator] = {}
        self._load_global(operators_dir)
        if strategy_dir:
            self._load_strategy(strategy_dir)

    def _load_global(self, operators_dir: str = None):
        """加载全局算子

        Args:
            operators_dir: 指定算子目录（如 'operators/v1'），None 则使用默认 'operators/v2'
        """
        if operators_dir:
            global_dir = PROJECT_ROOT / operators_dir
        else:
            global_dir = PROJECT_ROOT / "operators" / "v2"
        self._load_dir(global_dir)

    def _load_strategy(self, strategy_dir: Path):
        """加载策略私有算子 (覆盖同名全局算子)"""
        ops_dir = strategy_dir / "operators"
        self._load_dir(ops_dir)

    def _load_dir(self, directory: Path):
        """从目录递归加载所有 .md 算子文件（支持子目录分类）"""
        if not directory.is_dir():
            return
        for path in sorted(directory.rglob("*.md")):
            if path.name.startswith('README'):
                continue
            op = Operator.from_file(path)
            if op:
                self._operators[op.id] = op

    def get(self, op_id: str) -> Optional[Operator]:
        """按 ID 获取算子"""
        return self._operators.get(op_id)

    def resolve(self, op_ids: List[str]) -> List[Operator]:
        """按 ID 列表解析算子, 保持顺序, 跳过找不到的"""
        result = []
        for op_id in op_ids:
            op = self.get(op_id)
            if op:
                result.append(op)
            else:
                logger.warning(f"算子未找到: {op_id}")
        return result

    def list_all(self) -> List[Operator]:
        """列出所有可用算子"""
        return list(self._operators.values())

    def list_by_tag(self, tag: str) -> List[Operator]:
        """按标签筛选算子"""
        return [op for op in self._operators.values() if tag in op.tags]

    def all_tags(self) -> List[str]:
        """获取所有标签"""
        tags = set()
        for op in self._operators.values():
            tags.update(op.tags)
        return sorted(tags)

    def compose_content(self, op_ids: List[str]) -> str:
        """将多个算子的内容合并为一段分析指令"""
        ops = self.resolve(op_ids)
        if not ops:
            return ""
        parts = []
        for op in ops:
            parts.append(f"### {op.name}\n\n{op.content}")
        return "\n\n---\n\n".join(parts)

    def compose_data_needed(self, op_ids: List[str]) -> List[str]:
        """合并多个算子的 data_needed (去重)"""
        seen = set()
        result = []
        for op in self.resolve(op_ids):
            for d in op.data_needed:
                if d not in seen:
                    seen.add(d)
                    result.append(d)
        return result

    def compose_schema_text(self, op_ids: List[str]) -> str:
        """
        从算子 outputs 定义自动生成章节 schema 描述文本

        格式与 schema_to_prompt_description() 输出一致，
        可直接注入 system prompt。

        Returns:
            schema 描述文本，如无 outputs 则返回空字符串
        """
        TYPE_MAP = {
            'str': 'string',
            'float': 'number',
            'int': 'integer',
            'bool': 'boolean',
            'list': 'array of strings',
        }
        ops = self.resolve(op_ids)
        lines = []
        seen_fields = set()
        for op in ops:
            for out in op.outputs:
                if out.field in seen_fields:
                    continue
                seen_fields.add(out.field)
                type_label = TYPE_MAP.get(out.type, out.type)
                desc_part = f" — {out.desc}" if out.desc else ""
                lines.append(f"- **{out.field}** ({type_label}){desc_part}")
        if not lines:
            return ""
        return "字段列表：\n" + "\n".join(lines)
