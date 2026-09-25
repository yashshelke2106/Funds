"""Eligibility rule tests (hand-built NAV spans; D-008)."""
from datetime import date

import pandas as pd

from src.ingest.nav import eligibility

SM = pd.DataFrame([
    dict(fund_id="old_lc", role="active", amc="A", scheme_name="Old",
         direct_code=1, direct_isin="INF1", regular_code=2, regular_isin="INF2"),
    dict(fund_id="young_lc", role="active", amc="B", scheme_name="Young",
         direct_code=3, direct_isin="INF3", regular_code=4, regular_isin="INF4"),
])


def _nav(code, first, last):
    return pd.DataFrame({"scheme_code": [code, code], "nav_date": [first, last], "nav": [10.0, 11.0]})


def _metas(isins):
    return {c: {"isin_growth": i, "scheme_category": "Equity Scheme - Large Cap Fund"} for c, i in isins.items()}


def test_old_fund_eligible_young_fund_excluded():
    nav = pd.concat([
        _nav(1, date(2013, 1, 2), date(2026, 9, 24)), _nav(2, date(2013, 1, 2), date(2026, 9, 24)),
        _nav(3, date(2025, 3, 1), date(2026, 9, 24)), _nav(4, date(2025, 3, 1), date(2026, 9, 24)),
    ])
    u = eligibility(SM, nav, _metas({1: "INF1", 2: "INF2", 3: "INF3", 4: "INF4"})).set_index("fund_id")
    assert bool(u.loc["old_lc", "eligible"]) and bool(u.loc["old_lc", "covers_rolling_lookback"])
    assert not bool(u.loc["young_lc", "eligible"])
    assert u.loc["young_lc", "exclusion_reason"] == "nav_history_shorter_than_window"
    assert u.loc["old_lc", "report_group"] == "main"
    assert u.loc["young_lc", "report_group"] == "excluded"


def test_isin_mismatch_excludes():
    nav = pd.concat([_nav(c, date(2013, 1, 2), date(2026, 9, 24)) for c in (1, 2)])
    u = eligibility(SM.iloc[:1], nav, _metas({1: "INF1", 2: "WRONG"})).set_index("fund_id")
    assert not bool(u.loc["old_lc", "eligible"])
    assert "isin_mismatch" in u.loc["old_lc", "exclusion_reason"]


def test_window_start_boundary_inclusive():
    # first NAV exactly on WINDOW_START (2024-09-01) qualifies for the holdings window,
    # but not for the 12m rolling lookback (needs <= 2023-09-01)
    nav = pd.concat([_nav(c, date(2024, 9, 1), date(2026, 8, 31)) for c in (1, 2)])
    u = eligibility(SM.iloc[:1], nav, _metas({1: "INF1", 2: "INF2"})).set_index("fund_id")
    assert bool(u.loc["old_lc", "covers_holdings_window"])
    assert not bool(u.loc["old_lc", "covers_rolling_lookback"])
    assert u.loc["old_lc", "report_group"] == "partial_history"   # the Bajaj Finserv case


def test_checklist_covers_12_holdings_months():
    from src.ingest.checklist import months
    m = months()
    assert len(m) == 12 and m[0] == "2025-09" and m[-1] == "2026-08"
