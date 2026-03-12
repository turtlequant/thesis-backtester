"""
策略配置加载器

从 YAML 文件加载投资策略的完整配置，包括：
- 筛选条件（龟级阈值、基础过滤）
- 分析框架（章节定义、版本信息）
- 盲测参数（评分提取、阈值）
- 回测参数（前向收益周期）

用法:
    config = StrategyConfig.from_yaml("strategies/v556_value/strategy.yaml")
    config.get_screening_config()
    config.get_chapter_defs()
"""
import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Any, Optional

import yaml

from src.data.settings import PROJECT_ROOT


@dataclass
class StrategyConfig:
    """投资策略配置"""
    name: str
    version: str
    yaml_path: Path
    raw: dict

    @classmethod
    def from_yaml(cls, path) -> "StrategyConfig":
        """从 YAML 文件加载策略配置"""
        path = Path(path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path

        if not path.exists():
            raise FileNotFoundError(f"策略配置文件不存在: {path}")

        with open(path, 'r', encoding='utf-8') as f:
            raw = yaml.safe_load(f)

        return cls(
            name=raw.get('name', ''),
            version=raw.get('version', ''),
            yaml_path=path,
            raw=raw,
        )

    @property
    def strategy_dir(self) -> Path:
        """策略目录（YAML 所在目录）"""
        return self.yaml_path.parent

    def get_template_path(self) -> Path:
        """获取投资模版文件路径"""
        rel = self.raw.get('template_path', 'template.md')
        p = self.strategy_dir / rel
        return p.resolve()

    def get_chunks_dir(self) -> Path:
        """获取解析后章节文件目录"""
        rel = self.raw.get('chunks_dir', 'chunks')
        return self.strategy_dir / rel

    def get_backtest_dir(self) -> Path:
        """获取回测数据目录（样本、prompt、报告、验证结果）"""
        rel = self.raw.get('backtest_dir', 'backtest')
        return self.strategy_dir / rel

    def get_chapter_defs(self) -> List[dict]:
        """获取章节定义列表"""
        framework = self.raw.get('framework', {})
        return framework.get('chapters', [])

    def get_version_string(self) -> str:
        """获取框架版本字符串（用于 prompt 注入）"""
        framework = self.raw.get('framework', {})
        return framework.get('version_string', self.name)

    def get_analyst_role(self) -> str:
        """获取分析师角色描述"""
        framework = self.raw.get('framework', {})
        return framework.get('analyst_role', '严谨的投资分析师')

    def get_synthesis_fields(self) -> List[str]:
        """获取综合研判输出字段列表"""
        framework = self.raw.get('framework', {})
        return framework.get('synthesis_fields', [])

    def get_screening_config(self) -> dict:
        """获取筛选配置"""
        return self.raw.get('screening', {})

    def get_tiers(self) -> List[dict]:
        """获取龟级/评级层定义"""
        screening = self.get_screening_config()
        return screening.get('tiers', [])

    def get_scoring_weights(self) -> dict:
        """获取评分权重"""
        screening = self.get_screening_config()
        return screening.get('scoring_weights', {'pe': 0.3, 'pb': 0.3, 'dv': 0.4})

    def get_scoring_ranges(self) -> dict:
        """获取评分满分/零分区间"""
        screening = self.get_screening_config()
        return screening.get('scoring_ranges', {
            'pe_full': 6, 'pe_zero': 15,
            'pb_full': 0.5, 'pb_zero': 1.5,
            'dv_zero': 2, 'dv_full': 8,
        })

    def get_default_tier_label(self) -> str:
        """不达标时的标签"""
        screening = self.get_screening_config()
        return screening.get('default_tier_label', '不达标')

    def get_blind_test_config(self) -> dict:
        """获取盲测配置"""
        return self.raw.get('blind_test', {})

    def get_score_patterns(self) -> List[str]:
        """获取评分提取正则列表"""
        bt = self.get_blind_test_config()
        return bt.get('score_patterns', [
            r'综合评分[：:]\s*\**(\d+)/100\**',
            r'综合评分[：:]\s*\**(\d+)\**\s*/\s*100',
            r'\*\*(\d+)/100\*\*',
            r'(\d+)/100',
        ])

    def get_recommendation_config(self) -> dict:
        """获取建议提取配置"""
        bt = self.get_blind_test_config()
        return bt.get('recommendation', {})

    def get_thresholds(self) -> dict:
        """获取判断阈值"""
        bt = self.get_blind_test_config()
        return bt.get('thresholds', {
            'buy_score_min': 60,
            'avoid_score_max': 50,
            'false_positive_return': -10,
            'false_negative_return': 10,
        })

    def get_backtest_config(self) -> dict:
        """获取回测配置"""
        return self.raw.get('backtest', {})

    def get_forward_periods(self) -> List[dict]:
        """获取前向收益周期列表"""
        bt = self.get_backtest_config()
        return bt.get('forward_periods', [
            {'months': 1, 'label': '1个月'},
            {'months': 3, 'label': '3个月'},
            {'months': 6, 'label': '6个月'},
            {'months': 12, 'label': '12个月'},
        ])

    def get_schema_map(self) -> Dict[str, type]:
        """动态加载输出 schema 模块，返回 chapter_id -> schema_class 映射"""
        module_path = self.raw.get('output_schema_module')
        if not module_path:
            return {}

        mod = importlib.import_module(module_path)

        schema_map = {}
        for ch_def in self.get_chapter_defs():
            ch_id = ch_def['id']
            # 约定: ch01_data_verify -> Ch01Output
            ch_num = ch_def.get('chapter', 0)
            class_name = f"Ch{ch_num:02d}Output"
            cls = getattr(mod, class_name, None)
            if cls is not None:
                schema_map[ch_id] = cls

        return schema_map

    def get_report_config(self) -> dict:
        """获取报告配置"""
        bt = self.get_blind_test_config()
        return {
            'title': bt.get('report_title', '盲测AI分析验证报告'),
            'cross_section_label': bt.get('cross_section_label', '截面'),
        }

    def get_database_config(self) -> dict:
        """获取数据库配置"""
        return self.raw.get('database', {})

    def get_framework_version_tag(self) -> str:
        """获取存入数据库的框架版本标签"""
        db = self.get_database_config()
        return db.get('framework_version_tag', self.version)


# ==================== 默认策略 ====================

_DEFAULT_CONFIG: Optional[StrategyConfig] = None


def get_default_config() -> StrategyConfig:
    """获取默认策略配置（V5.5.6）"""
    global _DEFAULT_CONFIG
    if _DEFAULT_CONFIG is None:
        default_yaml = PROJECT_ROOT / "strategies" / "v556_value" / "strategy.yaml"
        if default_yaml.exists():
            _DEFAULT_CONFIG = StrategyConfig.from_yaml(default_yaml)
        else:
            raise FileNotFoundError(
                f"默认策略配置不存在: {default_yaml}\n"
                "请确保 strategies/v556_value/strategy.yaml 已创建"
            )
    return _DEFAULT_CONFIG
