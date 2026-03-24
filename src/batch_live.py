"""
批量实时分析（模拟盘用）

混合数据源：Tushare（核心财务）+ AKShare（实时补充）
自动策略路由：银行 → bank_analysis，其他 → v6_enhanced
增量跳过 + 并发控制 + 汇总输出

用法:
    python -m src.batch_live stocks.txt [--concurrency 3] [--cutoff 2026-06-30]
    python -m src.batch_live stocks.txt --strategy v6_enhanced  # 强制指定策略
"""
import asyncio
import csv
import json
import logging
import time
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# 银行行业关键词
BANK_INDUSTRIES = {'银行'}

# 默认策略映射
STRATEGY_MAP = {
    'bank': 'strategies/bank_analysis/strategy.yaml',
    'default': 'strategies/v6_enhanced/strategy.yaml',
}


def load_stock_list(path: str) -> List[str]:
    """从文件加载股票列表（支持 txt/csv，每行一个代码或第一列为代码）"""
    stocks = []
    p = Path(path)
    with open(p, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # CSV 格式取第一列
            code = line.split(',')[0].strip()
            # 确保有后缀
            if code and '.' in code:
                stocks.append(code)
            elif code and code.isdigit():
                # 自动补后缀
                if code.startswith('6'):
                    stocks.append(f"{code}.SH")
                else:
                    stocks.append(f"{code}.SZ")
    return stocks


def detect_industry(ts_code: str) -> str:
    """从本地数据检测行业"""
    try:
        from src.data import api
        stock_list = api.get_stock_list()
        row = stock_list[stock_list['ts_code'] == ts_code]
        if not row.empty:
            return row.iloc[0].get('industry', '')
    except Exception:
        pass
    return ''


def route_strategy(ts_code: str, force_strategy: Optional[str] = None) -> str:
    """根据行业路由到对应策略"""
    if force_strategy:
        return f"strategies/{force_strategy}/strategy.yaml"

    industry = detect_industry(ts_code)
    if industry in BANK_INDUSTRIES:
        return STRATEGY_MAP['bank']
    return STRATEGY_MAP['default']


def create_hybrid_snapshot(ts_code: str, cutoff_date: str):
    """
    混合数据源创建 snapshot：
    - Tushare：核心财务数据（快速、稳定）
    - AKShare：实时补充数据（新闻、资金流）
    """
    from src.data.snapshot import StockSnapshot, create_snapshot
    from src.data import api

    # 1. 用 Tushare 创建基础 snapshot
    snapshot = create_snapshot(ts_code, cutoff_date)

    # 2. 用 AKShare 补充实时数据
    try:
        from src.data.crawler.provider import CrawlerProvider
        crawler = CrawlerProvider()

        # 新闻
        if snapshot.news.empty:
            try:
                code = ts_code.split('.')[0]
                news = crawler.fetch_news(ts_code, limit=15)
                if not news.empty:
                    snapshot.news = news
                    if 'news' not in snapshot.data_sources:
                        snapshot.data_sources.append('news')
                    logger.debug(f"  补充新闻: {len(news)} 条")
            except Exception as e:
                logger.debug(f"  新闻获取失败: {e}")

        # 资金流
        if snapshot.fund_flow.empty:
            try:
                fund_flow = crawler.fetch_fund_flow(ts_code, days=30)
                if not fund_flow.empty:
                    snapshot.fund_flow = fund_flow
                    if 'fund_flow' not in snapshot.data_sources:
                        snapshot.data_sources.append('fund_flow')
                    logger.debug(f"  补充资金流: {len(fund_flow)} 天")
            except Exception as e:
                logger.debug(f"  资金流获取失败: {e}")

        # 大盘指数
        if snapshot.index_daily.empty:
            try:
                index_daily = crawler.fetch_index_daily('sh000300', days=60)
                if not index_daily.empty:
                    snapshot.index_daily = index_daily
                    if 'index_daily' not in snapshot.data_sources:
                        snapshot.data_sources.append('index_daily')
                    logger.debug(f"  补充大盘指数: {len(index_daily)} 天")
            except Exception as e:
                logger.debug(f"  大盘指数获取失败: {e}")

    except ImportError:
        logger.warning("AKShare 未安装，跳过实时数据补充")
    except Exception as e:
        logger.warning(f"实时数据补充失败: {e}")

    return snapshot


async def analyze_single(
    ts_code: str,
    cutoff_date: str,
    force_strategy: Optional[str] = None,
    crawl_delay: float = 2.0,
) -> dict:
    """分析单只股票，返回结果摘要"""
    from src.engine.config import StrategyConfig
    from src.agent.runtime import run_blind_analysis

    # 路由策略
    strategy_path = route_strategy(ts_code, force_strategy)
    config = StrategyConfig.from_yaml(strategy_path)
    strategy_name = Path(strategy_path).parent.name

    # 检查是否已有报告（增量跳过）
    live_dir = Path(f"strategies/{strategy_name}/live")
    report_dir = live_dir / f"{ts_code}_{cutoff_date}"
    report_file = report_dir / f"{ts_code}_{cutoff_date}_structured.json"
    if report_file.exists():
        # 已有报告，读取摘要
        try:
            data = json.loads(report_file.read_text(encoding='utf-8'))
            syn = data.get('synthesis', {})
            return {
                'ts_code': ts_code,
                'strategy': strategy_name,
                'score': syn.get('综合评分', ''),
                'recommendation': syn.get('最终建议', ''),
                'logic': syn.get('核心逻辑', syn.get('一句话买入逻辑（强制）', '')),
                'status': 'skipped',
                'elapsed': 0,
            }
        except Exception:
            pass

    # 创建混合 snapshot
    start = time.time()
    try:
        snapshot = create_hybrid_snapshot(ts_code, cutoff_date)
    except Exception as e:
        return {
            'ts_code': ts_code,
            'strategy': strategy_name,
            'score': '',
            'recommendation': '',
            'logic': '',
            'status': f'data_error: {str(e)[:80]}',
            'elapsed': round(time.time() - start, 1),
        }

    # 爬虫间隔（避免反爬）
    await asyncio.sleep(crawl_delay)

    # 运行 Agent 分析（非盲测）
    output_dir = live_dir
    try:
        result = await run_blind_analysis(
            ts_code=ts_code,
            cutoff_date=cutoff_date,
            config=config,
            blind_mode=False,
            output_dir=output_dir,
        )
        syn = result.get('synthesis', {})
        elapsed = round(time.time() - start, 1)
        return {
            'ts_code': ts_code,
            'strategy': strategy_name,
            'score': syn.get('综合评分', ''),
            'recommendation': syn.get('最终建议', ''),
            'logic': syn.get('核心逻辑', syn.get('一句话买入逻辑（强制）', '')),
            'status': 'success',
            'elapsed': elapsed,
        }
    except Exception as e:
        elapsed = round(time.time() - start, 1)
        logger.error(f"分析失败 {ts_code}: {e}")
        return {
            'ts_code': ts_code,
            'strategy': strategy_name,
            'score': '',
            'recommendation': '',
            'logic': '',
            'status': f'error: {str(e)[:80]}',
            'elapsed': elapsed,
        }


async def batch_analyze(
    stocks: List[str],
    cutoff_date: str,
    concurrency: int = 3,
    force_strategy: Optional[str] = None,
    crawl_delay: float = 2.0,
):
    """批量分析"""
    total = len(stocks)
    completed = 0
    results = []
    semaphore = asyncio.Semaphore(concurrency)

    print(f"\n{'='*60}")
    print(f"批量实时分析")
    print(f"  截面日期: {cutoff_date}")
    print(f"  股票数量: {total}")
    print(f"  并发数: {concurrency}")
    print(f"  爬虫间隔: {crawl_delay}s")
    if force_strategy:
        print(f"  强制策略: {force_strategy}")
    else:
        print(f"  策略路由: 自动（银行→bank_analysis, 其他→v6_enhanced）")
    print(f"{'='*60}\n")

    start_time = time.time()

    async def _run(ts_code):
        nonlocal completed
        async with semaphore:
            result = await analyze_single(ts_code, cutoff_date, force_strategy, crawl_delay)
            completed += 1
            status = result['status']
            score = result.get('score', '')
            rec = result.get('recommendation', '')
            elapsed = result.get('elapsed', 0)

            if status == 'skipped':
                icon = '⏭'
                detail = f"{score}分 | {rec} | 已有报告"
            elif status == 'success':
                icon = '✓'
                detail = f"{score}分 | {rec} | {elapsed}s"
            else:
                icon = '✗'
                detail = status

            pct = int(completed / total * 100)
            total_elapsed = time.time() - start_time
            if completed > 0:
                eta_min = (total_elapsed / completed * (total - completed)) / 60
                eta_str = f"ETA {eta_min:.0f}min"
            else:
                eta_str = ""

            print(f"  {icon} [{completed}/{total} {pct}%] {ts_code} ({result['strategy']}) | {detail} | {eta_str}")
            results.append(result)

    # 逐只运行（semaphore 控制并发）
    tasks = [_run(ts_code) for ts_code in stocks]
    await asyncio.gather(*tasks)

    # 汇总
    total_elapsed = time.time() - start_time
    success = sum(1 for r in results if r['status'] == 'success')
    skipped = sum(1 for r in results if r['status'] == 'skipped')
    failed = sum(1 for r in results if r['status'] not in ('success', 'skipped'))

    print(f"\n{'='*60}")
    print(f"批量分析完成")
    print(f"  成功: {success}, 跳过: {skipped}, 失败: {failed}")
    print(f"  总耗时: {total_elapsed/60:.1f} 分钟")
    print(f"{'='*60}")

    # 保存汇总
    summary_file = f"batch_live_summary_{cutoff_date.replace('-', '')}.csv"
    results_sorted = sorted(results, key=lambda r: r.get('score', 0) or 0, reverse=True)

    with open(summary_file, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['ts_code', 'strategy', 'score', 'recommendation', 'logic', 'status', 'elapsed'])
        writer.writeheader()
        writer.writerows(results_sorted)

    print(f"\n汇总: {summary_file}")

    # 打印 Top 15
    buy_list = [r for r in results_sorted if r.get('recommendation') == '买入']
    if buy_list:
        print(f"\n建议买入 ({len(buy_list)} 只):")
        for r in buy_list[:15]:
            print(f"  {r['ts_code']:12s} {r['score']:>3}分  {r.get('logic', '')[:50]}")

    return results


def main():
    """CLI 入口"""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description='批量实时分析（模拟盘）')
    parser.add_argument('stock_list', help='股票列表文件（txt/csv，每行一个代码）')
    parser.add_argument('--cutoff', default=datetime.now().strftime('%Y-%m-%d'), help='截面日期（默认今天）')
    parser.add_argument('--concurrency', type=int, default=3, help='并发数（默认3）')
    parser.add_argument('--strategy', default=None, help='强制指定策略（默认自动路由）')
    parser.add_argument('--delay', type=float, default=2.0, help='爬虫间隔秒数（默认2）')
    args = parser.parse_args()

    stocks = load_stock_list(args.stock_list)
    if not stocks:
        print(f"错误: 从 {args.stock_list} 未读取到股票代码")
        sys.exit(1)

    print(f"读取 {len(stocks)} 只股票: {stocks[:5]}{'...' if len(stocks) > 5 else ''}")

    asyncio.run(batch_analyze(
        stocks=stocks,
        cutoff_date=args.cutoff,
        concurrency=args.concurrency,
        force_strategy=args.strategy,
        crawl_delay=args.delay,
    ))


if __name__ == '__main__':
    main()
