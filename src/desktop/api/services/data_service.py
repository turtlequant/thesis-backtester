"""
Data service — wraps CrawlerProvider for the desktop API.

Handles live snapshot creation, validation, and daily caching.
"""
import logging
import time
import dataclasses
from pathlib import Path
from typing import Tuple, List, Optional

import pandas as pd

from src.data.crawler import CrawlerProvider
from src.data.live_snapshot import create_live_snapshot, validate_live_snapshot
from src.data.snapshot import StockSnapshot

logger = logging.getLogger(__name__)

# Shared provider instance (reused across requests)
_provider: Optional[CrawlerProvider] = None


def get_provider() -> CrawlerProvider:
    """Get or create the shared CrawlerProvider instance."""
    global _provider
    if _provider is None:
        _provider = CrawlerProvider()
    return _provider


def _get_cache_dir(ts_code: str) -> Path:
    """Get the public cache directory for a stock + today's date."""
    from src.data.settings import PROJECT_ROOT
    today = time.strftime("%Y-%m-%d")
    return PROJECT_ROOT / "data" / "live_cache" / f"{ts_code}_{today}"


def _find_cached_raw_data(ts_code: str, strategy_path: str = None) -> Optional[Path]:
    """
    Check if today's cached data already exists for this stock.

    Looks in the public cache directory: data/live_cache/<ts_code>_<date>/
    """
    cache_dir = _get_cache_dir(ts_code)
    if _is_valid_cache(cache_dir):
        return cache_dir
    return None


def _is_valid_cache(raw_dir: Path) -> bool:
    """Check if raw_data directory has enough CSV files to be useful."""
    if not raw_dir.exists():
        return False
    csv_files = list(raw_dir.glob("*.csv"))
    # At least 3 CSV files (balancesheet, income, price_history)
    return len(csv_files) >= 3


def _load_snapshot_from_cache(ts_code: str, raw_dir: Path) -> StockSnapshot:
    """Reconstruct a StockSnapshot from cached CSV files."""
    logger.info(f"Loading cached data from {raw_dir}")

    snapshot = StockSnapshot(
        ts_code=ts_code,
        stock_name="",
        cutoff_date=time.strftime("%Y-%m-%d"),
        generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )

    # Load each CSV back into the snapshot
    for field in dataclasses.fields(snapshot):
        csv_path = raw_dir / f"{field.name}.csv"
        if csv_path.exists() and 'DataFrame' in str(field.type):
            try:
                df = pd.read_csv(csv_path)
                setattr(snapshot, field.name, df)
            except Exception as e:
                logger.warning(f"Failed to load cached {field.name}: {e}")

    # Restore basic info from individual_info if available
    info_path = raw_dir / "individual_info.csv"
    if info_path.exists():
        try:
            info = pd.read_csv(info_path)
            if not info.empty:
                info_dict = dict(zip(info.iloc[:, 0], info.iloc[:, 1]))
                snapshot.stock_name = info_dict.get("股票简称", "")
                snapshot.industry = info_dict.get("行业", "")
        except Exception:
            pass

    snapshot.data_sources = [f.stem for f in raw_dir.glob("*.csv")]
    return snapshot


def create_snapshot_for_analysis(
    ts_code: str,
    strategy_path: str = None,
) -> Tuple[StockSnapshot, bool, List[str], List[str]]:
    """
    Create a live snapshot and validate it.

    Uses daily cache if available (same stock + same day = reuse data).

    Returns:
        (snapshot, is_valid, errors, warnings)
    """
    # Check cache first
    cached_dir = _find_cached_raw_data(ts_code, strategy_path)
    if cached_dir:
        logger.info(f"Using cached data for {ts_code} from {cached_dir}")
        snapshot = _load_snapshot_from_cache(ts_code, cached_dir)
        is_valid, errors, warnings = validate_live_snapshot(snapshot)
        warnings.insert(0, f"使用今日缓存数据（来源：{cached_dir.parent.name}）")
        return snapshot, is_valid, errors, warnings

    # No cache, fetch fresh
    provider = get_provider()
    snapshot = create_live_snapshot(ts_code, provider=provider)
    is_valid, errors, warnings = validate_live_snapshot(snapshot)

    # Auto-save to cache immediately after fetching
    try:
        cache_dir = _get_cache_dir(ts_code)
        cache_dir.mkdir(parents=True, exist_ok=True)
        for field in dataclasses.fields(snapshot):
            val = getattr(snapshot, field.name)
            if hasattr(val, 'to_csv') and len(val) > 0:
                val.to_csv(cache_dir / f"{field.name}.csv", index=False)
        logger.info(f"Auto-cached raw data to {cache_dir}")
    except Exception as e:
        logger.warning(f"Failed to auto-cache raw data: {e}")

    return snapshot, is_valid, errors, warnings


def validate_stock_code(ts_code: str) -> Tuple[bool, str]:
    """
    Validate stock code format.

    Expected format: 6-digit code + .SH or .SZ
    Examples: 601288.SH, 000001.SZ
    """
    if not ts_code:
        return False, "Stock code cannot be empty"

    parts = ts_code.split(".")
    if len(parts) != 2:
        return False, f"Invalid format: '{ts_code}'. Expected: 601288.SH or 000001.SZ"

    code, market = parts
    if len(code) != 6 or not code.isdigit():
        return False, f"Invalid code part: '{code}'. Must be 6 digits"

    if market not in ("SH", "SZ"):
        return False, f"Invalid market: '{market}'. Must be SH or SZ"

    return True, ""
