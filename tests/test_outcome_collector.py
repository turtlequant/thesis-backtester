import pandas as pd
import pytest

from src.backtest import outcome_collector
from src.backtest.quality_scorer import score_recommendation_quality
from src.data import api


def test_get_daily_pushes_code_list_and_dates_into_storage(monkeypatch):
    captured = {}

    def fake_load(category, sub, partitions, columns=None, filters=None):
        captured.update(
            category=category,
            sub=sub,
            partitions=partitions,
            columns=columns,
            filters=filters,
        )
        return pd.DataFrame(
            [
                {'ts_code': '000001.SZ', 'trade_date': '2024-01-02', 'close': 10.0},
                {'ts_code': '600000.SH', 'trade_date': '2024-01-03', 'close': 11.0},
            ]
        )

    monkeypatch.setattr(api.storage, 'load', fake_load)
    result = api.get_daily(
        '2024-01-01',
        '2024-01-31',
        ts_code=['000001.SZ', '600000.SH'],
    )

    assert len(result) == 2
    assert captured['category'] == 'daily'
    assert captured['sub'] == 'raw'
    assert ('trade_date', '>=', '2024-01-01') in captured['filters']
    assert ('trade_date', '<=', '2024-01-31') in captured['filters']
    assert (
        'ts_code',
        'in',
        ['000001.SZ', '600000.SH'],
    ) in captured['filters']


def test_get_daily_adjusted_supports_batch_and_keeps_raw_prices(monkeypatch):
    calls = []

    def fake_load(category, sub, partitions, columns=None, filters=None):
        calls.append((sub, filters))
        if sub == 'raw':
            return pd.DataFrame(
                [
                    {'ts_code': '000001.SZ', 'trade_date': '2024-01-31', 'close': 10.0},
                    {'ts_code': '000001.SZ', 'trade_date': '2024-02-29', 'close': 5.5},
                    {'ts_code': '600000.SH', 'trade_date': '2024-01-31', 'close': 20.0},
                ]
            )
        return pd.DataFrame(
            [
                {'ts_code': '000001.SZ', 'trade_date': '2024-01-31', 'adj_factor': 1.0},
                {'ts_code': '000001.SZ', 'trade_date': '2024-02-29', 'adj_factor': 2.0},
                {'ts_code': '600000.SH', 'trade_date': '2024-01-31', 'adj_factor': 1.0},
            ]
        )

    monkeypatch.setattr(api.storage, 'load', fake_load)
    result = api.get_daily_adjusted(
        '2024-01-01',
        '2024-02-29',
        ts_code=['000001.SZ', '600000.SH'],
        adjust='hfq',
        columns=['ts_code', 'trade_date', 'close'],
        keep_raw_prices=True,
    )

    stock = result[result['ts_code'] == '000001.SZ'].reset_index(drop=True)
    assert stock['close'].tolist() == pytest.approx([10.0, 11.0])
    assert stock['raw_close'].tolist() == pytest.approx([10.0, 5.5])
    assert all(('ts_code', 'in', ['000001.SZ', '600000.SH']) in filters for _, filters in calls)


def test_get_daily_adjusted_never_falls_back_to_raw(monkeypatch):
    def fake_load(category, sub, partitions, columns=None, filters=None):
        if sub == 'raw':
            return pd.DataFrame(
                [{'ts_code': '000001.SZ', 'trade_date': '2024-01-31', 'close': 10.0}]
            )
        return pd.DataFrame()

    monkeypatch.setattr(api.storage, 'load', fake_load)

    with pytest.raises(RuntimeError, match='不能退回不复权行情'):
        api.get_daily_adjusted('2024-01-01', '2024-01-31', ts_code='000001.SZ')


def test_collect_forward_outcomes_queries_each_dataset_once(monkeypatch):
    calls = {'daily': 0, 'dividends': 0}
    codes = ['000001.SZ', '600000.SH']
    dates = ['2024-01-31', '2024-03-01', '2024-04-30', '2024-07-29', '2025-01-25']

    def fake_get_daily_adjusted(
        start_date,
        end_date,
        ts_code=None,
        adjust='qfq',
        columns=None,
        keep_raw_prices=False,
    ):
        calls['daily'] += 1
        assert ts_code == codes
        assert adjust == 'hfq'
        assert columns == ['ts_code', 'trade_date', 'close']
        assert keep_raw_prices is True
        rows = []
        for code, prices in zip(codes, ([10, 11, 12, 13, 14], [20, 18, 22, 24, 30])):
            rows.extend(
                {
                    'ts_code': code,
                    'trade_date': date,
                    'close': price,
                    'raw_close': price,
                }
                for date, price in zip(dates, prices)
            )
        return pd.DataFrame(rows)

    def fake_get_dividends(ts_codes, columns=None):
        calls['dividends'] += 1
        assert ts_codes == codes
        return pd.DataFrame(
            [
                {
                    'ts_code': '000001.SZ',
                    'end_date': '2023-12-31',
                    'ex_date': '2024-06-01',
                    'cash_div_tax': '0.25',
                },
                {
                    'ts_code': '600000.SH',
                    'end_date': '2023-12-31',
                    'ex_date': '20240601',
                    'cash_div_tax': 0.5,
                },
            ]
        )

    monkeypatch.setattr(api, 'get_daily_adjusted', fake_get_daily_adjusted)
    monkeypatch.setattr(api, 'get_dividends', fake_get_dividends)

    results = outcome_collector.collect_forward_outcomes(codes, '2024-01-31')

    assert calls == {'daily': 1, 'dividends': 1}
    assert set(results) == set(codes)
    assert results['000001.SZ'].return_1m == pytest.approx(0.1)
    assert results['000001.SZ'].return_12m == pytest.approx(0.4)
    assert results['000001.SZ'].actual_dividends == pytest.approx(0.25)
    assert results['600000.SH'].return_1m == pytest.approx(-0.1)
    assert results['600000.SH'].actual_dividends == pytest.approx(0.5)


def test_collect_forward_outcomes_by_cutoff_uses_one_merged_market_query(monkeypatch):
    calls = {"windows": 0, "dividends": 0}

    def fake_windows(windows):
        calls["windows"] += 1
        assert len(windows) == 3
        return pd.DataFrame(columns=["ts_code", "trade_date", "close", "raw_close"])

    def fake_dividends(codes, columns=None):
        calls["dividends"] += 1
        assert codes == ["000001.SZ", "600000.SH"]
        return pd.DataFrame(columns=columns)

    monkeypatch.setattr(api, "get_daily_hfq_windows", fake_windows)
    monkeypatch.setattr(api, "get_dividends", fake_dividends)

    results = outcome_collector.collect_forward_outcomes_by_cutoff(
        {
            "2024-01-31": ["000001.SZ", "600000.SH"],
            "2024-07-31": ["000001.SZ"],
        }
    )

    assert calls == {"windows": 1, "dividends": 1}
    assert set(results) == {"2024-01-31", "2024-07-31"}
    assert set(results["2024-01-31"]) == {"000001.SZ", "600000.SH"}
    assert set(results["2024-07-31"]) == {"000001.SZ"}


def test_recommendation_quality_does_not_add_dividends_twice():
    score, details = score_recommendation_quality(
        {'recommendation': '买入'},
        {
            'return_6m': 0.04,
            'actual_dividends': 1.0,
            'cutoff_price': 10.0,
        },
    )

    assert score == 50
    assert details['total_return_6m'] == '4.0%'


def test_unelapsed_forward_horizons_remain_empty():
    daily = pd.DataFrame(
        {
            'ts_code': ['000001.SZ'] * 5,
            'trade_date': [
                '2026-07-31',
                '2026-08-17',
                '2026-08-31',
                '2026-10-30',
                '2027-01-27',
            ],
            'close': [100.0, 103.0, 110.0, 120.0, 130.0],
        }
    )

    outcome = outcome_collector._build_forward_outcome(
        '000001.SZ',
        '2026-07-31',
        daily,
        warn=False,
        as_of_date='2026-08-18',
    )

    assert outcome.return_1m is None
    assert outcome.return_3m is None
    assert outcome.return_6m is None
    assert outcome.return_12m is None
    assert outcome.max_drawdown_6m is None
    assert outcome.max_gain_6m is None
    assert outcome.volatility_6m is None


def test_only_elapsed_forward_horizons_are_calculated():
    daily = pd.DataFrame(
        {
            'ts_code': ['000001.SZ'] * 4,
            'trade_date': ['2024-01-31', '2024-03-01', '2024-04-30', '2024-05-03'],
            'close': [100.0, 110.0, 120.0, 121.0],
        }
    )

    outcome = outcome_collector._build_forward_outcome(
        '000001.SZ',
        '2024-01-31',
        daily,
        warn=False,
        as_of_date='2024-05-05',
    )

    assert outcome.return_1m == pytest.approx(0.1)
    assert outcome.return_3m == pytest.approx(0.2)
    assert outcome.return_6m is None
    assert outcome.return_12m is None


def test_forward_horizon_rejects_stale_trade_date():
    daily = pd.DataFrame(
        {
            'ts_code': ['000001.SZ', '000001.SZ'],
            'trade_date': ['2024-01-31', '2024-02-10'],
            'close': [100.0, 110.0],
        }
    )

    outcome = outcome_collector._build_forward_outcome(
        '000001.SZ',
        '2024-01-31',
        daily,
        warn=False,
        as_of_date='2024-03-05',
    )

    assert outcome.return_1m is None
