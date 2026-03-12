"""
Parquet 本地存储

目录约定:
    tushare/basic/          单文件，全量覆盖
    tushare/daily/{sub}/    按月分区，如 2024-01.parquet
    financial/{sub}/        按报告期分区，如 2024-06.parquet
"""
from pathlib import Path
from typing import List, Optional
import pandas as pd
from .settings import TUSHARE_DATA_DIR, FINANCIAL_DATA_DIR, PARQUET_COMPRESSION


# ==================== 路径工具 ====================

def get_path(category: str, sub: str, partition: str, base_dir: Path = None) -> Path:
    """
    获取文件路径

    Args:
        category: 'basic' / 'daily' / 'financial'
        sub: 子目录，如 'raw', 'indicator', 'balancesheet'
        partition: 分区名，如 'stock_list', '2024-01'
        base_dir: 基础目录，默认 TUSHARE_DATA_DIR
    """
    if base_dir is None:
        base_dir = TUSHARE_DATA_DIR
    if sub:
        return base_dir / category / sub / f"{partition}.parquet"
    else:
        return base_dir / category / f"{partition}.parquet"


def get_financial_path(sub: str, partition: str) -> Path:
    """获取财报数据文件路径"""
    return FINANCIAL_DATA_DIR / sub / f"{partition}.parquet"


def get_month(date: str) -> str:
    """日期转月份分区: '2024-01-02' -> '2024-01'"""
    return date[:7]


def get_months_between(start_date: str, end_date: str) -> List[str]:
    """
    获取日期范围内的月份列表

    '2024-01-15', '2024-03-20' -> ['2024-01', '2024-02', '2024-03']
    """
    months = pd.date_range(start_date, end_date, freq='MS').strftime('%Y-%m').tolist()
    start_month = start_date[:7]
    end_month = end_date[:7]
    if start_month not in months:
        months.append(start_month)
    if end_month not in months:
        months.append(end_month)
    return sorted(set(months))


# ==================== 保存 ====================

def save(
    df: pd.DataFrame,
    category: str,
    sub: str,
    partition: str,
    mode: str = 'overwrite',
    merge_on: List[str] = None,
    base_dir: Path = None,
) -> bool:
    """
    保存数据

    Args:
        mode: 'overwrite' 直接覆盖, 'merge' 合并去重（需指定 merge_on）
    """
    if base_dir is None:
        base_dir = TUSHARE_DATA_DIR
    path = get_path(category, sub, partition, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if mode == 'merge' and merge_on and path.exists():
            existing = pd.read_parquet(path)
            df = pd.concat([existing, df], ignore_index=True)
            df = df.drop_duplicates(subset=merge_on, keep='last')
            df = df.sort_values(merge_on).reset_index(drop=True)

        df.to_parquet(path, compression=PARQUET_COMPRESSION, index=False)
        return True

    except Exception as e:
        print(f"保存失败 {path}: {e}")
        return False


def save_financial(
    df: pd.DataFrame,
    sub: str,
    partition: str,
    mode: str = 'overwrite',
    merge_on: List[str] = None,
) -> bool:
    """保存财报数据"""
    path = get_financial_path(sub, partition)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if mode == 'merge' and merge_on and path.exists():
            existing = pd.read_parquet(path)
            df = pd.concat([existing, df], ignore_index=True)
            df = df.drop_duplicates(subset=merge_on, keep='last')
            df = df.sort_values(merge_on).reset_index(drop=True)

        df.to_parquet(path, compression=PARQUET_COMPRESSION, index=False)
        return True

    except Exception as e:
        print(f"保存失败 {path}: {e}")
        return False


# ==================== 加载 ====================

def load(
    category: str,
    sub: str,
    partitions: List[str],
    columns: List[str] = None,
    base_dir: Path = None,
) -> pd.DataFrame:
    """加载数据（支持多分区）"""
    if base_dir is None:
        base_dir = TUSHARE_DATA_DIR
    dfs = []
    for p in partitions:
        path = get_path(category, sub, p, base_dir)
        if path.exists():
            dfs.append(pd.read_parquet(path, columns=columns))

    if not dfs:
        return pd.DataFrame()

    return pd.concat(dfs, ignore_index=True)


def load_one(category: str, sub: str, partition: str, columns: List[str] = None,
             base_dir: Path = None) -> pd.DataFrame:
    """加载单个分区"""
    return load(category, sub, [partition], columns, base_dir)


def load_financial(
    sub: str,
    partitions: List[str] = None,
    columns: List[str] = None,
) -> pd.DataFrame:
    """
    加载财报数据

    Args:
        sub: 'balancesheet' / 'income' / 'cashflow'
        partitions: 分区列表，None 则加载所有
    """
    if partitions is None:
        partitions = list_financial_partitions(sub)

    dfs = []
    for p in partitions:
        path = get_financial_path(sub, p)
        if path.exists():
            dfs.append(pd.read_parquet(path, columns=columns))

    if not dfs:
        return pd.DataFrame()

    return pd.concat(dfs, ignore_index=True)


# ==================== 查询工具 ====================

def list_partitions(category: str, sub: str, base_dir: Path = None) -> List[str]:
    """列出所有分区"""
    if base_dir is None:
        base_dir = TUSHARE_DATA_DIR
    if sub:
        dir_path = base_dir / category / sub
    else:
        dir_path = base_dir / category

    if not dir_path.exists():
        return []

    return sorted([f.stem for f in dir_path.glob("*.parquet")])


def list_financial_partitions(sub: str) -> List[str]:
    """列出财报数据的所有分区"""
    dir_path = FINANCIAL_DATA_DIR / sub
    if not dir_path.exists():
        return []
    return sorted([f.stem for f in dir_path.glob("*.parquet")])


def exists(category: str, sub: str, partition: str, base_dir: Path = None) -> bool:
    """检查分区是否存在"""
    if base_dir is None:
        base_dir = TUSHARE_DATA_DIR
    return get_path(category, sub, partition, base_dir).exists()


def get_latest_partition(category: str, sub: str, base_dir: Path = None) -> Optional[str]:
    """获取最新分区"""
    partitions = list_partitions(category, sub, base_dir)
    return partitions[-1] if partitions else None


def get_latest_date(category: str, sub: str) -> Optional[str]:
    """获取最新数据日期"""
    latest = get_latest_partition(category, sub)
    if not latest:
        return None

    df = load_one(category, sub, latest, columns=['trade_date'])
    if df.empty:
        return None

    return df['trade_date'].max()


# ==================== 删除 ====================

def delete(category: str, sub: str, partition: str, base_dir: Path = None) -> bool:
    """删除分区"""
    if base_dir is None:
        base_dir = TUSHARE_DATA_DIR
    path = get_path(category, sub, partition, base_dir)
    if path.exists():
        path.unlink()
        return True
    return False
