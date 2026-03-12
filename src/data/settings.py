"""
全局配置
"""
import os
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_ROOT = PROJECT_ROOT / "data"

# 加载 .env 文件（如果存在）
_env_file = PROJECT_ROOT / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

# Tushare 配置
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")

# 数据目录
TUSHARE_DATA_DIR = DATA_ROOT / "tushare"
FINANCIAL_DATA_DIR = DATA_ROOT / "financial"
SNAPSHOT_DIR = DATA_ROOT / "snapshots"
ANALYSIS_DB_PATH = DATA_ROOT / "analysis_results" / "results.db"

# Parquet 压缩方式
PARQUET_COMPRESSION = "zstd"

# 日期格式
DATE_FORMAT = "%Y-%m-%d"
