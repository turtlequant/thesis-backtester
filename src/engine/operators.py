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
from typing import Any, Dict, List, Optional

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
    category: str = ""
    tags: List[str] = field(default_factory=list)
    data_needed: List[str] = field(default_factory=list)
    outputs: List[OperatorOutput] = field(default_factory=list)
    gate: Dict[str, Any] = field(default_factory=dict)  # 行业门控 {exclude_industry: [...]}
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
            category=meta.get('category', ''),
            tags=meta.get('tags', []),
            data_needed=meta.get('data_needed', []),
            outputs=outputs,
            gate=meta.get('gate', {}),
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

    # 行业别名映射：gate 里的标准名 → 实际数据中可能出现的行业名
    INDUSTRY_ALIASES = {
        '银行': ['银行'],
        '保险': ['保险'],
        '证券': ['证券'],
        '多元金融': ['多元金融'],
        '房地产': ['全国地产', '区域地产', '房产服务', '园区开发'],
        '煤炭': ['煤炭开采', '焦炭加工'],
        '钢铁': ['普钢', '特种钢', '钢加工'],
        '石油': ['石油开采', '石油加工', '石油贸易'],
        '化工': ['化工原料', '化纤', '染料涂料', '日用化工'],
        '公用事业': ['水力发电', '火力发电', '新型电力', '供气供热', '水务'],
        '食品饮料': ['白酒', '红黄酒', '啤酒', '软饮料', '食品', '乳制品'],
        '家电': ['家用电器', '家居用品'],
        '医药': ['化学制药', '中成药', '生物制药', '医药商业', '医疗保健'],
        '汽车': ['汽车整车', '汽车配件', '汽车服务'],
        '科技': ['软件服务', '半导体', 'IT设备', '通信设备', '互联网', '元器件'],
    }

    def _match_industry(self, gate_industry: str, actual_industry: str) -> bool:
        """检查 gate 中的行业名是否匹配实际行业。

        支持：精确匹配、子串包含、别名映射。
        """
        if not actual_industry:
            return False
        # 精确匹配
        if gate_industry == actual_industry:
            return True
        # 子串包含（如 gate 写"银行"，实际是"银行"）
        if gate_industry in actual_industry or actual_industry in gate_industry:
            return True
        # 别名映射
        aliases = self.INDUSTRY_ALIASES.get(gate_industry, [])
        return actual_industry in aliases

    def resolve(self, op_ids: List[str], industry: str = None) -> List[Operator]:
        """按 ID 列表解析算子, 保持顺序, 跳过找不到的。

        如果传入 industry，自动执行行业路由：
        1. 跳过 gate.exclude_industry 含该行业的算子
        2. 从算子库中补充 gate.only_industry 含该行业的替代算子
        """
        result = []
        skipped = []

        for op_id in op_ids:
            op = self.get(op_id)
            if not op:
                logger.warning(f"算子未找到: {op_id}")
                continue

            # 行业门控检查
            if industry and op.gate:
                exclude = op.gate.get('exclude_industry', [])
                if any(self._match_industry(ind, industry) for ind in exclude):
                    skipped.append(op_id)
                    logger.info(f"行业路由: 跳过 {op_id}（不适用于 {industry}）")
                    continue

            result.append(op)

        # 注意：行业专用算子不自动补充到章节中。
        # 自动路由只负责"跳过不适用的算子"。
        # 行业专用算子（如银行 PB-ROE 估值）应在策略编排中显式配置。
        # 这样避免跨章节误注入的问题。

        if skipped:
            logger.info(f"行业路由: 已跳过 {skipped}，最终 {len(result)} 个算子")

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

    def compose_content(self, op_ids: List[str], industry: str = None) -> str:
        """将多个算子的内容合并为一段分析指令"""
        ops = self.resolve(op_ids, industry=industry)
        if not ops:
            return ""
        parts = []
        for op in ops:
            parts.append(f"### {op.name}\n\n{op.content}")
        return "\n\n---\n\n".join(parts)

    def compose_data_needed(self, op_ids: List[str], industry: str = None) -> List[str]:
        """合并多个算子的 data_needed (去重)"""
        seen = set()
        result = []
        for op in self.resolve(op_ids, industry=industry):
            for d in op.data_needed:
                if d not in seen:
                    seen.add(d)
                    result.append(d)
        return result

    def compose_schema_text(self, op_ids: List[str], industry: str = None) -> str:
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
        ops = self.resolve(op_ids, industry=industry)
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
