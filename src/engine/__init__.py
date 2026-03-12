"""
引擎模块 - 策略无关的核心能力

提供 StrategyConfig 加载和 Launcher 入口。
"""
from .config import StrategyConfig, get_default_config

__all__ = ["StrategyConfig", "get_default_config"]
