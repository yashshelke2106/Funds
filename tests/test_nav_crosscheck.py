"""Rule tests for cross-source NAV checks (hand-built inputs, D-008)."""
from datetime import date

import pandas as pd

from src.quality.nav_crosscheck import direct_vs_regular, nav_vs_amfi


def test_nav_mismatch_and_missing_are_failures():
    nav = pd.DataFrame({"scheme_code": [1, 2], "nav_date": [date(2026, 9, 24)] * 2, "nav": [100.00004, 50.0]})
    amfi = pd.DataFrame({"scheme_code": [1, 2, 3], "nav_date": [date(2026, 9, 24)] * 3, "nav": [100.0, 50.01, 7.0]})
    got = {(r["check"], r["scheme_code"]) for r in nav_vs_amfi(nav, amfi, {1, 2, 3}, "latest")}
    assert got == {("mfapi_vs_amfi_latest", 2), ("mfapi_missing_on_latest", 3)}   # 1 is within rounding


def test_direct_below_regular_fails():
    sm = pd.DataFrame({"fund_id": ["ok", "swapped"], "direct_code": [1, 3], "regular_code": [2, 4]})
    d = [date(2025, 1, 1), date(2026, 1, 1)]
    nav = pd.DataFrame({"scheme_code": [1, 1, 2, 2, 3, 3, 4, 4], "nav_date": d * 4,
                        "nav": [10, 11.1, 10, 11.0, 10, 11.0, 10, 11.1]})
    issues, summ = direct_vs_regular(nav, sm, start=date(2025, 1, 1), end=date(2026, 12, 31))
    assert [i["fund_id"] for i in issues] == ["swapped"]
    assert len(summ) == 2
