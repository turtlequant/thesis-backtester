"""
量化因子注册表

发现、加载、执行受控 Polars DSL 与旧版 Python 量化因子。
因子扩展 DataFrame 的可用列，供过滤器和评分引用。

两类因子:
    1. 截面因子 (cross_section): compute(df: DataFrame) -> Series
       输入全市场截面数据, 输出同 index 的 Series。
       按交易日存储, 每日增量计算。

    2. 时序因子 (timeseries): compute(ts_code: str, api_module) -> float|None
       输入单股票代码 + api 模块, 读取历史财报/行情, 输出单一数值。
       每只股票跑一次, 结果是 ts_code → value 的静态属性。

解析优先级:
    1. workspace/strategies/<name>/factors/  (策略私有, 同名覆盖)
    2. workspace/factors/                     (全局共享)

META 约定:
    {
        'id': 'profit_growth_5y',
        'name': '5年利润增速(%)',
        'type': 'timeseries',          # 'cross_section'(默认) 或 'timeseries'
        'data_needed': ['income'],
        'description': '近5年归母净利润CAGR',
    }
"""
import importlib.util
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

from src.data.settings import FACTORS_ROOT

logger = logging.getLogger(__name__)

# 因子类型常量
FACTOR_CROSS_SECTION = 'cross_section'
FACTOR_TIMESERIES = 'timeseries'


@dataclass
class Factor:
    """一个量化因子"""
    id: str
    name: str
    description: str
    data_needed: List[str]
    compute_fn: Optional[Callable]  # 旧版 Python 因子执行函数
    factor_type: str = FACTOR_CROSS_SECTION
    source_path: Optional[Path] = None
    category: str = "其他"
    tags: List[str] = field(default_factory=list)
    engine: str = "python"
    dsl_expression: str = ""
    input_columns: Dict[str, str] = field(default_factory=dict)
    optional_input_columns: List[str] = field(default_factory=list)
    output_dtype: str = "float64"
    unit: str = ""
    direction: str = "neutral"
    point_in_time_safe: bool = False
    execution_mode: str = "row"


class FactorRegistry:
    """量化因子注册表"""

    def __init__(self, strategy_dir: Path = None):
        self._factors: Dict[str, Factor] = {}
        self._load_dir(FACTORS_ROOT)
        if strategy_dir:
            self._load_dir(strategy_dir / "factors")

    def _load_dir(self, directory: Path):
        if not directory.is_dir():
            return
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith('_'):
                continue
            self._load_file(path)
        self._load_dsl_dir(directory)

    def _load_dsl_dir(self, directory: Path):
        """Load declarative definitions after Python so DSL becomes canonical."""
        try:
            from src.engine.factor_catalog import load_dsl_definitions

            definitions, errors = load_dsl_definitions(directory)
            for error in errors:
                logger.warning("加载 DSL 因子失败 %s: %s", error["path"], error["error"])
            for definition in definitions:
                if not definition.enabled:
                    continue
                factor_type = (
                    FACTOR_CROSS_SECTION
                    if definition.factor_type == FACTOR_CROSS_SECTION
                    else FACTOR_TIMESERIES
                )
                self._factors[definition.id] = Factor(
                    id=definition.id,
                    name=definition.name,
                    description=definition.description,
                    data_needed=list(definition.inputs.values()),
                    compute_fn=None,
                    factor_type=factor_type,
                    source_path=definition.source_path,
                    category=definition.category,
                    tags=list(definition.tags),
                    engine="polars",
                    dsl_expression=definition.expression,
                    input_columns=dict(definition.input_columns),
                    optional_input_columns=[
                        definition.input_columns[alias]
                        for alias in definition.optional_inputs
                    ],
                    output_dtype=definition.output_dtype,
                    unit=definition.unit,
                    direction=definition.direction,
                    point_in_time_safe=definition.point_in_time_safe,
                    execution_mode=definition.execution_mode,
                )
        except Exception as exc:
            logger.warning("加载 DSL 因子目录 %s 失败: %s", directory, exc)

    def _load_file(self, path: Path):
        try:
            spec = importlib.util.spec_from_file_location(f"factor_{path.stem}", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            meta = getattr(mod, 'META', None)
            compute_fn = getattr(mod, 'compute', None)
            if meta is None or compute_fn is None:
                logger.debug(f"跳过 {path}: 缺少 META 或 compute")
                return

            factor = Factor(
                id=meta.get('id', path.stem),
                name=meta.get('name', path.stem),
                description=meta.get('description', ''),
                data_needed=meta.get('data_needed', []),
                compute_fn=compute_fn,
                factor_type=meta.get('type', FACTOR_CROSS_SECTION),
                source_path=path,
                engine="python",
            )
            self._factors[factor.id] = factor

        except Exception as e:
            logger.warning(f"加载因子 {path} 失败: {e}")

    def get(self, factor_id: str) -> Optional[Factor]:
        return self._factors.get(factor_id)

    def list_all(self) -> List[Factor]:
        return list(self._factors.values())

    def list_cross_section(self) -> List[Factor]:
        """列出所有截面因子"""
        return [f for f in self._factors.values() if f.factor_type == FACTOR_CROSS_SECTION]

    def list_timeseries(self) -> List[Factor]:
        """列出所有时序因子"""
        return [f for f in self._factors.values() if f.factor_type == FACTOR_TIMESERIES]

    def compute_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算所有截面因子, 将结果列追加到 df (不覆盖已有列)"""
        df = df.copy()
        dsl_factors = [
            factor
            for factor in self._factors.values()
            if factor.factor_type == FACTOR_CROSS_SECTION
            and factor.engine == "polars"
            and factor.execution_mode == "row"
            and factor.id not in df.columns
        ]
        if dsl_factors:
            try:
                from src.engine.factor_dsl import execute_factor_batch

                outputs, errors = execute_factor_batch(df, dsl_factors)
                for factor_id, series in outputs.items():
                    df[factor_id] = series
                for factor_id, error in errors.items():
                    logger.debug("因子 %s 计算跳过: %s", factor_id, error)
            except Exception as exc:
                logger.warning("Polars 因子批量计算失败: %s", exc)

        for factor in self._factors.values():
            if factor.factor_type != FACTOR_CROSS_SECTION:
                continue
            if factor.id not in df.columns and factor.compute_fn is not None:
                try:
                    df[factor.id] = factor.compute_fn(df)
                except Exception as e:
                    logger.debug(f"因子 {factor.id} 计算失败: {e}")
        return df

    def compute_selected(self, df: pd.DataFrame, factor_ids: List[str]) -> pd.DataFrame:
        """只计算指定截面因子"""
        df = df.copy()
        selected = [self._factors[fid] for fid in factor_ids if fid in self._factors]
        dsl_factors = [
            factor
            for factor in selected
            if factor.factor_type == FACTOR_CROSS_SECTION
            and factor.engine == "polars"
            and factor.execution_mode == "row"
            and factor.id not in df.columns
        ]
        if dsl_factors:
            try:
                from src.engine.factor_dsl import execute_factor_batch

                outputs, errors = execute_factor_batch(df, dsl_factors)
                for factor_id, series in outputs.items():
                    df[factor_id] = series
                for factor_id, error in errors.items():
                    logger.debug("因子 %s 计算跳过: %s", factor_id, error)
            except Exception as exc:
                logger.warning("Polars 因子批量计算失败: %s", exc)

        for fid in factor_ids:
            factor = self._factors.get(fid)
            if (
                factor
                and factor.factor_type == FACTOR_CROSS_SECTION
                and fid not in df.columns
                and factor.compute_fn is not None
            ):
                try:
                    df[fid] = factor.compute_fn(df)
                except Exception as e:
                    logger.debug(f"因子 {fid} 计算失败: {e}")
        return df

    def compute_timeseries_one(self, factor: Factor, ts_code: str) -> Optional[float]:
        """计算单只股票的时序因子"""
        if factor.factor_type != FACTOR_TIMESERIES or factor.compute_fn is None:
            return None
        try:
            from src.data import api
            return factor.compute_fn(ts_code, api)
        except Exception as e:
            logger.debug(f"时序因子 {factor.id} ({ts_code}) 计算失败: {e}")
            return None
