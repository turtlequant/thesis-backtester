"""
每章结构化输出定义

动态加载当前策略的 output_schema。
保留此文件以维持向后兼容的导入路径。

实际定义位于各策略目录: strategies/<name>/output_schema.py
"""
import importlib
import logging

logger = logging.getLogger(__name__)

# 默认策略模块路径
_DEFAULT_SCHEMA_MODULE = "strategies.v556_value.output_schema"

_schema_classes = {}


def _load_schema_module(module_path: str = None):
    """动态加载 schema 模块"""
    global _schema_classes
    module_path = module_path or _DEFAULT_SCHEMA_MODULE
    try:
        mod = importlib.import_module(module_path)
        for name in [
            "Ch01Output", "Ch02Output", "Ch03Output", "Ch04Output", "Ch05Output",
            "Ch06Output", "Ch07Output", "Ch08Output", "Ch09Output", "Ch10Output",
            "SynthesisOutput",
        ]:
            if hasattr(mod, name):
                _schema_classes[name] = getattr(mod, name)
    except ImportError as e:
        logger.warning(f"无法加载 schema 模块 {module_path}: {e}")


def __getattr__(name):
    """延迟加载：首次访问 schema 类时才 import"""
    if not _schema_classes:
        _load_schema_module()
    if name in _schema_classes:
        return _schema_classes[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
