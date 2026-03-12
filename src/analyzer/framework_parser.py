"""
框架解析器

将投资分析模版解析为多个章节chunk，供 prompt_builder 使用。
支持通过 StrategyConfig 配置不同的模版和章节定义。

用法:
    python -m src.analyzer.framework_parser
    python -m src.analyzer.framework_parser strategies/v556_value/strategy.yaml
"""
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, TYPE_CHECKING

import re

from src.data.settings import PROJECT_ROOT

if TYPE_CHECKING:
    from src.engine.config import StrategyConfig

# ==================== 默认值（向后兼容） ====================

TEMPLATE_PATH = PROJECT_ROOT / "strategies" / "v556_value" / "template.md"
CHUNKS_DIR = PROJECT_ROOT / "strategies" / "v556_value" / "chunks"

CHAPTER_DEFS = [
    {
        "id": "ch01_data_verify",
        "chapter": 1,
        "title": "数据核查与地缘政治排除",
        "pattern": "## 第一章",
        "dependencies": [],
        "focus": "数据源分级、地缘政治排除、快速初筛（5分钟排除法）、负债扫描",
        "data_needed": ["price_summary", "basic_info"],
        "output_type": "screening",
    },
    {
        "id": "ch02_soe_stream",
        "chapter": 2,
        "title": "央国企筛选与流派识别",
        "pattern": "## 第二章",
        "dependencies": ["ch01_data_verify"],
        "focus": "国企背景判定、四流派分类（纯硬收息/价值发现/烟蒂股/关联方资源）",
        "data_needed": ["top10_holders", "basic_info", "daily_indicators"],
        "output_type": "classification",
    },
    {
        "id": "ch03_debt_cycle",
        "chapter": 3,
        "title": "深度负债与周期分析",
        "pattern": "## 第三章",
        "dependencies": ["ch01_data_verify", "ch02_soe_stream"],
        "focus": "有息vs经营性负债、无有息负债特殊识别、周期性行业负债特判、管理人诚信评估",
        "data_needed": ["balancesheet", "income"],
        "output_type": "debt_analysis",
    },
    {
        "id": "ch04_cash_trend",
        "chapter": 4,
        "title": "动态现金与周期拐点",
        "pattern": "## 第四章",
        "dependencies": ["ch01_data_verify", "ch03_debt_cycle"],
        "focus": "5年现金余额趋势、行业周期拐点判断、非现金项目还原",
        "data_needed": ["cashflow", "balancesheet", "income"],
        "output_type": "cash_analysis",
    },
    {
        "id": "ch05_stress_test",
        "chapter": 5,
        "title": "极端情景测试",
        "pattern": "## 第五章",
        "dependencies": ["ch03_debt_cycle", "ch04_cash_trend"],
        "focus": "连续三年营收下降10%压力测试、分红可持续性验证",
        "data_needed": ["income", "cashflow", "dividend"],
        "output_type": "stress_test",
    },
    {
        "id": "ch06_valuation",
        "chapter": 6,
        "title": "估值与安全边际",
        "pattern": "## 第六章",
        "dependencies": ["ch03_debt_cycle", "ch04_cash_trend", "ch05_stress_test"],
        "focus": "V2债券视角/V3业主视角/V3.5FCEV估值、剔除净现金FCF倍数、FCF计算规范化、动态安全边际",
        "data_needed": ["income", "cashflow", "balancesheet", "daily_indicators", "dividend"],
        "output_type": "valuation",
    },
    {
        "id": "ch07_decision",
        "chapter": 7,
        "title": "决策流程与持仓管理",
        "pattern": "## 第七章",
        "dependencies": ["ch02_soe_stream", "ch06_valuation"],
        "focus": "核心卫星仓位、动态退出纪律、试探建仓与网格加仓、持仓状态标签、组合韧性评估",
        "data_needed": ["daily_indicators", "price_summary"],
        "output_type": "decision",
    },
    {
        "id": "ch08_cigar_butt",
        "chapter": 8,
        "title": "高级烟蒂股分析框架",
        "pattern": "## 第八章",
        "dependencies": ["ch02_soe_stream", "ch03_debt_cycle", "ch06_valuation"],
        "focus": "T级资产分层、REITs期限结构、债务偿还路径、静态价值型三要义",
        "data_needed": ["balancesheet", "income", "cashflow"],
        "output_type": "cigar_butt",
    },
    {
        "id": "ch09_repair",
        "chapter": 9,
        "title": "估值修复框架",
        "pattern": "## 第九章",
        "dependencies": ["ch02_soe_stream", "ch06_valuation"],
        "focus": "跨流派买卖逻辑统一、苹果买卖模型、一句话买入逻辑声明",
        "data_needed": ["daily_indicators", "price_summary"],
        "output_type": "repair_framework",
    },
    {
        "id": "ch10_light_asset",
        "chapter": 10,
        "title": "特殊轻资产模式",
        "pattern": "## 第十章",
        "dependencies": ["ch06_valuation"],
        "focus": "航空IT等特殊商业模式估值",
        "data_needed": ["income", "cashflow"],
        "output_type": "light_asset",
    },
]


@dataclass
class FrameworkChunk:
    """解析后的框架章节"""
    id: str
    chapter: int
    title: str
    content: str
    dependencies: List[str]
    focus: str
    data_needed: List[str]
    output_type: str
    line_count: int = 0
    char_count: int = 0


def _resolve_chapter_defs(config: Optional["StrategyConfig"] = None) -> List[dict]:
    """从 config 或默认值获取章节定义"""
    if config is not None:
        return config.get_chapter_defs()
    return CHAPTER_DEFS


def _resolve_template_path(config: Optional["StrategyConfig"] = None) -> Path:
    """从 config 或默认值获取模版路径"""
    if config is not None:
        return config.get_template_path()
    return TEMPLATE_PATH


def _resolve_chunks_dir(config: Optional["StrategyConfig"] = None) -> Path:
    """从 config 或默认值获取 chunks 目录"""
    if config is not None:
        return config.get_chunks_dir()
    return CHUNKS_DIR


def parse_template(config: Optional["StrategyConfig"] = None) -> List[FrameworkChunk]:
    """解析模版文件为章节列表"""
    template_path = _resolve_template_path(config)
    chapter_defs = _resolve_chapter_defs(config)

    if not template_path.exists():
        raise FileNotFoundError(f"模版文件不存在: {template_path}")

    with open(template_path, 'r', encoding='utf-8') as f:
        full_text = f.read()
        lines = full_text.split('\n')

    # 找到每章的起止行
    chapter_ranges = []
    for cdef in chapter_defs:
        start_line = None
        for i, line in enumerate(lines):
            if line.startswith(cdef["pattern"]):
                start_line = i
                break
        if start_line is not None:
            chapter_ranges.append((cdef, start_line))

    # 按行号排序
    chapter_ranges.sort(key=lambda x: x[1])

    # 提取每章内容
    chunks = []
    for idx, (cdef, start) in enumerate(chapter_ranges):
        if idx + 1 < len(chapter_ranges):
            end = chapter_ranges[idx + 1][1]
        else:
            end = len(lines)

        content = '\n'.join(lines[start:end]).strip()

        chunk = FrameworkChunk(
            id=cdef["id"],
            chapter=cdef["chapter"],
            title=cdef["title"],
            content=content,
            dependencies=cdef["dependencies"],
            focus=cdef["focus"],
            data_needed=cdef["data_needed"],
            output_type=cdef["output_type"],
            line_count=end - start,
            char_count=len(content),
        )
        chunks.append(chunk)

    return chunks


def save_chunks(chunks: List[FrameworkChunk], config: Optional["StrategyConfig"] = None) -> Path:
    """保存解析后的章节到文件"""
    chunks_dir = _resolve_chunks_dir(config)
    chunks_dir.mkdir(parents=True, exist_ok=True)

    for chunk in chunks:
        content_path = chunks_dir / f"{chunk.id}.md"
        content_path.write_text(chunk.content, encoding='utf-8')

        meta_path = chunks_dir / f"{chunk.id}.meta"
        meta = (
            f"chapter: {chunk.chapter}\n"
            f"title: {chunk.title}\n"
            f"focus: {chunk.focus}\n"
            f"dependencies: {','.join(chunk.dependencies)}\n"
            f"data_needed: {','.join(chunk.data_needed)}\n"
            f"output_type: {chunk.output_type}\n"
            f"line_count: {chunk.line_count}\n"
            f"char_count: {chunk.char_count}\n"
        )
        meta_path.write_text(meta, encoding='utf-8')

    # 保存索引
    index_path = chunks_dir / "index.md"
    index_lines = ["# Framework Chunks Index\n"]
    for chunk in chunks:
        index_lines.append(
            f"- **{chunk.id}** (Ch{chunk.chapter}): {chunk.title} "
            f"[{chunk.line_count} lines, {chunk.char_count} chars]\n"
            f"  - 依赖: {', '.join(chunk.dependencies) or '无'}\n"
            f"  - 焦点: {chunk.focus}\n"
        )
    index_path.write_text('\n'.join(index_lines), encoding='utf-8')

    return chunks_dir


def load_chunk(chunk_id: str, config: Optional["StrategyConfig"] = None) -> Optional[FrameworkChunk]:
    """加载单个章节"""
    chunks_dir = _resolve_chunks_dir(config)
    content_path = chunks_dir / f"{chunk_id}.md"
    meta_path = chunks_dir / f"{chunk_id}.meta"

    if not content_path.exists():
        return None

    content = content_path.read_text(encoding='utf-8')

    meta = {}
    if meta_path.exists():
        for line in meta_path.read_text(encoding='utf-8').split('\n'):
            if ':' in line:
                key, val = line.split(':', 1)
                meta[key.strip()] = val.strip()

    return FrameworkChunk(
        id=chunk_id,
        chapter=int(meta.get('chapter', 0)),
        title=meta.get('title', ''),
        content=content,
        dependencies=meta.get('dependencies', '').split(',') if meta.get('dependencies') else [],
        focus=meta.get('focus', ''),
        data_needed=meta.get('data_needed', '').split(',') if meta.get('data_needed') else [],
        output_type=meta.get('output_type', ''),
        line_count=int(meta.get('line_count', 0)),
        char_count=int(meta.get('char_count', 0)),
    )


def load_all_chunks(config: Optional["StrategyConfig"] = None) -> List[FrameworkChunk]:
    """加载所有章节，按章节号排序"""
    chapter_defs = _resolve_chapter_defs(config)
    chunks = []
    for cdef in chapter_defs:
        chunk = load_chunk(cdef["id"], config=config)
        if chunk:
            chunks.append(chunk)
    return chunks


def get_chapter_defs(config: Optional["StrategyConfig"] = None) -> List[dict]:
    """获取章节定义"""
    return _resolve_chapter_defs(config)


# ==================== CLI ====================

def main():
    import sys
    config = None
    if len(sys.argv) >= 2 and sys.argv[1].endswith('.yaml'):
        from src.engine.config import StrategyConfig
        config = StrategyConfig.from_yaml(sys.argv[1])
        print(f"使用策略: {config.name}")
    else:
        print("解析 investTemplate V5.5.6...")

    chunks = parse_template(config=config)

    print(f"\n解析完成, 共 {len(chunks)} 章:")
    for chunk in chunks:
        print(f"  Ch{chunk.chapter}: {chunk.title} ({chunk.line_count} 行, {chunk.char_count} 字符)")
        print(f"    依赖: {', '.join(chunk.dependencies) or '无'}")
        print(f"    焦点: {chunk.focus}")

    out_dir = save_chunks(chunks, config=config)
    print(f"\n已保存到: {out_dir}")


if __name__ == '__main__':
    main()
