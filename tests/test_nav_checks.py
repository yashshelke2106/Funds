"""Rule tests for NAV quality checks (hand-built inputs; see DECISIONS D-008)."""
from datetime import date

import pandas as pd

from src.quality.nav_checks import check_nav


def _nav(rows):
    return pd.DataFrame(rows, columns=["scheme_code", "nav_date", "nav"])


def test_clean_series_has_no_issues():
    # Mon 2026-08-03 .. Fri 2026-08-07, moves < 10%
    df = _nav([(1, date(2026, 8, d), 100 + d) for d in range(3, 8)])
    assert check_nav(df).empty


def test_weekend_is_not_a_gap():
    df = _nav([(1, date(2026, 8, 7), 100.0), (1, date(2026, 8, 10), 101.0)])  # Fri -> Mon
    assert check_nav(df).empty


def test_gap_of_exactly_5_weekdays_passes_6_flags():
    # Fri 7 Aug -> Mon 17 Aug: weekdays strictly between = 10..14 = 5  -> pass
    ok = _nav([(1, date(2026, 8, 7), 100.0), (1, date(2026, 8, 17), 100.0)])
    assert check_nav(ok).empty
    # Fri 7 Aug -> Tue 18 Aug: 10..14 + 17 = 6 -> flag
    bad = _nav([(1, date(2026, 8, 7), 100.0), (1, date(2026, 8, 18), 100.0)])
    out = check_nav(bad)
    assert out["check"].tolist() == ["gap_gt_5_weekdays"]
    assert out["value"].iloc[0] == 6
    assert out["severity"].iloc[0] == "flag"


def test_non_positive_nav_fails():
    df = _nav([(1, date(2026, 8, 3), 100.0), (1, date(2026, 8, 4), 0.0)])
    out = check_nav(df)
    assert "non_positive_nav" in out["check"].tolist()
    assert (out.loc[out.check == "non_positive_nav", "severity"] == "fail").all()


def test_duplicate_date_fails():
    df = _nav([(1, date(2026, 8, 3), 100.0), (1, date(2026, 8, 3), 100.0)])
    out = check_nav(df)
    assert (out["check"] == "duplicate_date").sum() == 2
    assert (out["severity"] == "fail").all()


def test_large_move_threshold_is_strict():
    # +10% exactly passes; +10.5% flags; -12% flags
    df = _nav([(1, date(2026, 8, 3), 100.0), (1, date(2026, 8, 4), 110.0),
               (2, date(2026, 8, 3), 100.0), (2, date(2026, 8, 4), 110.5),
               (3, date(2026, 8, 3), 100.0), (3, date(2026, 8, 4), 88.0)])
    out = check_nav(df)
    assert sorted(out.loc[out.check == "abs_daily_move_gt_10pct", "scheme_code"]) == [2, 3]


def test_schemes_are_checked_independently():
    # scheme 2 starts much later than scheme 1 ends: must not create a cross-scheme gap
    df = _nav([(1, date(2026, 1, 5), 100.0), (2, date(2026, 8, 3), 50.0)])
    assert check_nav(df).empty
