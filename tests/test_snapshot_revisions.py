import pandas as pd

from src.data.snapshot import _filter_by_announcement_date


def test_snapshot_uses_only_the_latest_revision_known_at_cutoff():
    statements = pd.DataFrame(
        [
            {
                "ts_code": "600000.SH",
                "end_date": "2023-12-31",
                "report_type": "1",
                "f_ann_date": "2024-03-20",
                "ann_date": "2024-03-20",
                "revenue": 100.0,
            },
            {
                "ts_code": "600000.SH",
                "end_date": "2023-12-31",
                "report_type": "1",
                "f_ann_date": "2024-03-20",
                "ann_date": "2024-05-10",
                "revenue": 110.0,
            },
        ]
    )

    before_revision = _filter_by_announcement_date(
        statements,
        "2024-04-30",
        pd.DataFrame(),
    )
    after_revision = _filter_by_announcement_date(
        statements,
        "2024-05-31",
        pd.DataFrame(),
    )

    assert before_revision["revenue"].tolist() == [100.0]
    assert after_revision["revenue"].tolist() == [110.0]
