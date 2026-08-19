"""
策略配置加载器

从 YAML 文件加载投资策略的完整配置。
支持新格式（meta/paths/screening.filters 声明式）和旧格式的向后兼容。

用法:
    config = StrategyConfig.from_yaml("workspace/strategies/v6_value/strategy.yaml")
    config.get_filters()
    config.get_chapter_defs()
"""
import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from src.data.settings import PROJECT_ROOT, STRATEGIES_ROOT, WORKSPACE_ROOT
from src.engine.framework_validation import normalize_synthesis_fields


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
            project_candidate = PROJECT_ROOT / path
            path = project_candidate if project_candidate.exists() else WORKSPACE_ROOT / path

        if not path.exists():
            raise FileNotFoundError(f"策略配置文件不存在: {path}")

        with open(path, 'r', encoding='utf-8') as f:
            raw = yaml.safe_load(f)

        # 兼容新格式 (meta.name) 和旧格式 (name)
        meta = raw.get('meta', {})
        name = meta.get('name', '') or raw.get('name', '')
        version = meta.get('version', '') or raw.get('version', '')

        return cls(name=name, version=version, yaml_path=path, raw=raw)

    def save(self):
        """保存配置回 YAML 文件"""
        with open(self.yaml_path, 'w', encoding='utf-8') as f:
            yaml.dump(self.raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    @property
    def strategy_dir(self) -> Path:
        """策略目录（YAML 所在目录）"""
        return self.yaml_path.parent

    # ==================== 路径 ====================

    def _paths(self) -> dict:
        return self.raw.get('paths', {})

    def get_template_path(self) -> Path:
        """获取投资模版文件路径"""
        rel = self._paths().get('template') or self.raw.get('template_path', 'template.md')
        return (self.strategy_dir / rel).resolve()

    def get_chunks_dir(self) -> Path:
        """获取解析后章节文件目录"""
        rel = self._paths().get('chunks_dir') or self.raw.get('chunks_dir', 'chunks')
        return self.strategy_dir / rel

    def get_chapters_path(self) -> Path:
        """获取 chapters.yaml 路径"""
        rel = self._paths().get('chapters', 'chapters.yaml')
        return self.strategy_dir / rel

    def get_backtest_dir(self) -> Path:
        """获取回测数据目录"""
        rel = self._paths().get('backtest_dir') or self.raw.get('backtest_dir', 'backtest')
        return self.strategy_dir / rel

    def get_output_schema_module(self) -> str:
        """获取输出 schema 模块路径"""
        return self._paths().get('output_schema') or self.raw.get('output_schema_module', '')

    def get_operators_dir(self) -> Optional[str]:
        """获取算子版本目录（如 'operators/v1'），None 使用默认"""
        framework = self.raw.get('framework', {})
        return framework.get('operators_dir', None)

    # ==================== 分析框架 ====================

    def get_chapter_defs(self) -> List[dict]:
        """获取章节定义列表 — 优先从独立 chapters.yaml 加载"""
        # 1. 尝试独立文件
        chapters_path = self.get_chapters_path()
        if chapters_path.exists():
            with open(chapters_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            if data and 'chapters' in data:
                return data['chapters']

        # 2. 回退到内联定义
        framework = self.raw.get('framework', {})
        return framework.get('chapters', [])

    def get_operator_registry(self):
        """获取算子注册表 (延迟导入避免循环依赖)"""
        from .operators import OperatorRegistry
        return OperatorRegistry(
            strategy_dir=self.strategy_dir,
            operators_dir=self.get_operators_dir(),
        )

    def get_chapter_focus(self, chapter_def: dict) -> str:
        """获取章节的分析重点 — 优先从算子组合, 回退到 focus 字段"""
        operators = chapter_def.get('operators', [])
        if operators:
            registry = self.get_operator_registry()
            return registry.compose_content(operators)
        return chapter_def.get('focus', '')

    def get_chapter_data_needed(self, chapter_def: dict) -> List[str]:
        """获取章节所需数据 — 优先从算子推导, 回退到 data_needed 字段"""
        operators = chapter_def.get('operators', [])
        if operators:
            registry = self.get_operator_registry()
            return registry.compose_data_needed(operators)
        return chapter_def.get('data_needed', [])

    def get_version_string(self) -> str:
        framework = self.raw.get('framework', {})
        return framework.get('version_string', self.name)

    def get_analyst_role(self) -> str:
        framework = self.raw.get('framework', {})
        return framework.get('analyst_role', '投资分析师')

    def get_synthesis_fields(self) -> List[Dict[str, Any]]:
        framework = self.raw.get('framework', {})
        return normalize_synthesis_fields(framework.get('synthesis_fields', []))

    def get_synthesis_config(self) -> dict:
        """获取综合研判配置（thinking_steps, scoring_rubric, decision_thresholds）"""
        framework = self.raw.get('framework', {})
        return framework.get('synthesis', {})

    def get_thinking_steps(self) -> List[dict]:
        """获取综合研判的思考步骤"""
        return self.get_synthesis_config().get('thinking_steps', [])

    def get_scoring_rubric(self) -> List[dict]:
        """获取评分锚点"""
        return self.get_synthesis_config().get('scoring_rubric', [])

    def get_decision_thresholds(self) -> dict:
        """获取决策边界阈值"""
        return self.get_synthesis_config().get('decision_thresholds', {})

    # ==================== 声明式筛选 ====================

    def get_screening_config(self) -> dict:
        return self.raw.get('screening', {})

    def get_exclude_rules(self) -> List[dict]:
        """获取排除规则"""
        return self.get_screening_config().get('exclude', [])

    def get_industry_cap(self) -> int:
        """获取单行业入选上限，0 表示不限"""
        return self.get_screening_config().get('industry_cap', 0)

    def get_agent_batch_config(self) -> dict:
        """获取 agent 批量分析配置 {ratio, max}"""
        return self.get_screening_config().get('agent_batch', {'ratio': 0.2, 'max': 20})

    def get_agent_batch_size(self, total_candidates: int) -> int:
        """根据候选总数计算 agent 分析数量"""
        cfg = self.get_agent_batch_config()
        ratio = cfg.get('ratio', 0.2)
        max_n = cfg.get('max', 20)
        n = max(1, int(total_candidates * ratio))
        return min(n, max_n)

    def get_filters(self) -> List[dict]:
        """获取声明式过滤条件"""
        sc = self.get_screening_config()
        filters = sc.get('filters', [])
        if filters:
            return filters
        # 旧格式兼容: 从 min_market_cap/max_pe/min_pe 转换
        legacy = []
        if 'max_pe' in sc or 'min_pe' in sc:
            f = {'field': 'pe_ttm'}
            if 'min_pe' in sc:
                f['min'] = sc['min_pe'] or 0.01
            if 'max_pe' in sc:
                f['max'] = sc['max_pe']
            legacy.append(f)
        if 'min_market_cap' in sc:
            legacy.append({'field': 'total_mv', 'min': sc['min_market_cap'] * 10000})
        return legacy

    def get_scoring_factors(self) -> List[dict]:
        """获取评分因子"""
        sc = self.get_screening_config()
        scoring = sc.get('scoring', {})
        factors = scoring.get('factors', [])
        if factors:
            return factors
        # 旧格式兼容
        weights = sc.get('scoring_weights', {})
        ranges = sc.get('scoring_ranges', {})
        if weights and ranges:
            return [
                {'field': 'pe_ttm', 'weight': weights.get('pe', 0.3), 'lower_better': True,
                 'full': ranges.get('pe_full', 6), 'zero': ranges.get('pe_zero', 15)},
                {'field': 'pb', 'weight': weights.get('pb', 0.3), 'lower_better': True,
                 'full': ranges.get('pb_full', 0.5), 'zero': ranges.get('pb_zero', 1.5)},
                {'field': 'dv', 'weight': weights.get('dv', 0.4), 'lower_better': False,
                 'full': ranges.get('dv_full', 8), 'zero': ranges.get('dv_zero', 2)},
            ]
        return []

    def get_tiers(self) -> List[dict]:
        """获取分级定义"""
        sc = self.get_screening_config()
        scoring = sc.get('scoring', {})
        tiers = scoring.get('tiers', [])
        if tiers:
            return tiers
        # 旧格式兼容: tiers 在 screening 顶层
        return sc.get('tiers', [])

    def get_default_tier_label(self) -> str:
        sc = self.get_screening_config()
        scoring = sc.get('scoring', {})
        return scoring.get('default_tier', sc.get('default_tier_label', '不达标'))

    # 旧接口兼容 — 供尚未迁移的模块使用
    def get_scoring_weights(self) -> dict:
        factors = self.get_scoring_factors()
        return {f['field']: f['weight'] for f in factors} if factors else {}

    def get_scoring_ranges(self) -> dict:
        factors = self.get_scoring_factors()
        result = {}
        for f in factors:
            field = f['field']
            result[f'{field}_full'] = f.get('full', 0)
            result[f'{field}_zero'] = f.get('zero', 0)
        return result

    # ==================== 盲测配置 ====================

    def get_blind_test_config(self) -> dict:
        return self.raw.get('blind_test', {})

    def get_score_patterns(self) -> List[str]:
        bt = self.get_blind_test_config()
        return bt.get('score_patterns', [])

    def get_recommendation_config(self) -> dict:
        bt = self.get_blind_test_config()
        return bt.get('recommendation', {})

    def get_thresholds(self) -> dict:
        bt = self.get_blind_test_config()
        return bt.get('thresholds', {})

    # ==================== 回测配置 ====================

    def get_backtest_config(self) -> dict:
        return self.raw.get('backtest', {})

    def get_cross_section_interval(self) -> str:
        bt = self.get_backtest_config()
        return bt.get('cross_section_interval', '6m')

    def get_forward_periods(self) -> List[dict]:
        bt = self.get_backtest_config()
        return bt.get('forward_periods', [
            {'months': 1, 'label': '1个月'},
            {'months': 3, 'label': '3个月'},
            {'months': 6, 'label': '6个月'},
            {'months': 12, 'label': '12个月'},
        ])

    def get_backtest_start(self) -> str:
        return self.get_backtest_config().get('start_date', '2022-06-30')

    def get_backtest_end(self) -> str:
        return self.get_backtest_config().get('end_date', '2024-06-30')

    def get_backtest_top_n(self) -> int:
        return self.get_backtest_config().get('top_n', 50)

    def get_agent_concurrency(self) -> int:
        return self.get_backtest_config().get('agent_concurrency', 3)

    # ==================== Schema ====================

    def get_schema_map(self) -> Dict[str, type]:
        """动态加载输出 schema 模块"""
        module_path = self.get_output_schema_module()
        if not module_path:
            return {}

        mod = importlib.import_module(module_path)

        schema_map = {}
        for ch_def in self.get_chapter_defs():
            ch_id = ch_def['id']
            ch_num = ch_def.get('chapter', 0)
            class_name = f"Ch{ch_num:02d}Output"
            cls = getattr(mod, class_name, None)
            if cls is not None:
                schema_map[ch_id] = cls

        return schema_map

    # ==================== 报告/数据库 ====================

    def get_report_config(self) -> dict:
        bt = self.get_blind_test_config()
        return {
            'title': bt.get('report_title', '盲测AI分析验证报告'),
        }

    def get_database_config(self) -> dict:
        return self.raw.get('database', {})

    def get_framework_version_tag(self) -> str:
        db = self.get_database_config()
        return db.get('framework_version_tag', self.version)


# ==================== 默认策略 ====================

_DEFAULT_CONFIG: Optional[StrategyConfig] = None


def get_default_config() -> StrategyConfig:
    """获取默认策略配置"""
    global _DEFAULT_CONFIG
    if _DEFAULT_CONFIG is None:
        default_yaml = STRATEGIES_ROOT / "v6_value" / "strategy.yaml"
        if default_yaml.exists():
            _DEFAULT_CONFIG = StrategyConfig.from_yaml(default_yaml)
        else:
            raise FileNotFoundError(
                f"默认策略配置不存在: {default_yaml}\n"
                "请确保 workspace/strategies/v6_value/strategy.yaml 已创建"
            )
    return _DEFAULT_CONFIG
