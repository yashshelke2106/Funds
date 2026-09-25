"""TER parser tests on REAL AMFI exports (unedited copies, D-008) plus hand-built rule cases."""
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.ingest.ter import (TerFormatError, combine, coverage, detect_format, fill_daily, map_codes,
                            parse_ter_file)

FX = Path(__file__).parent / "fixtures" / "ter"
SM = pd.DataFrame({"fund_id": ["hdfc_lc", "bandhan_n100"],
                   "scheme_name": ["HDFC Large Cap Fund", "BANDHAN NIFTY 100 INDEX FUND"]})


def test_new_format_hdfc_aug_2026():
    df = parse_ter_file(FX / "hdfc_lc_2026-08_new.xlsx")
    assert set(df.format) == {"new"} and df.nsdl_code.nunique() == 1
    r = df[(df.plan == "regular") & (df.ter_date == date(2026, 8, 1))].iloc[0]
    assert (r.base, r.brokerage, r.txn, r.levies, r.total) == (1.29, 0.0, 0.01, 0.26, 1.56)
    assert df[df.plan == "regular"].ter_date.nunique() == 31


def test_old_format_hdfc_mar_2026_and_gap_fill():
    df = parse_ter_file(FX / "hdfc_lc_2026-03_old.xlsx")
    assert set(df.format) == {"old"}
    r = df[(df.plan == "direct") & (df.ter_date == date(2026, 3, 1))].iloc[0]
    assert (r.base, r.addl_c, r.levies, r.total) == (0.82, 0.05, 0.14, 1.01)
    assert date(2026, 3, 21) not in set(df.ter_date)                     # the real 1-day gap
    t = df.assign(fund_id="hdfc_lc")
    d = fill_daily(t)
    x = d[(d.plan == "regular") & (d.ter_date == date(2026, 3, 21))].iloc[0]
    prev = df[(df.plan == "regular") & (df.ter_date == date(2026, 3, 20))].total.iloc[0]
    assert bool(x.filled) and x.total == prev                                # carried from 20-Mar, not invented


def test_footer_dropped_and_codes_whitespace_free():
    df = parse_ter_file(FX / "bandhan_other_index_2026-08_new.xlsx")
    assert df.category.eq("Other Scheme - Index Funds").all()
    assert not df.nsdl_code.str.contains(r"\s").any()                      # 'BNDN/O/E /EIN/..' normalised


def test_mapping_picks_nifty100_not_lookalikes():
    df = combine([parse_ter_file(FX / "bandhan_other_index_2026-08_new.xlsx"),
                  parse_ter_file(FX / "hdfc_lc_2026-08_new.xlsx")])
    m = map_codes(df, SM).set_index("fund_id")
    assert m.loc["bandhan_n100", "nsdl_code"] == "BNDN/O/O/EIN/21/12/0049"
    assert "Low Volatility" not in m.loc["bandhan_n100", "names"]
    b = df[(df.nsdl_code == "BNDN/O/O/EIN/21/12/0049") & (df.ter_date == date(2026, 8, 1))].set_index("plan")
    assert b.loc["regular", "total"] == 0.66 and b.loc["direct", "total"] == 0.16


def test_conflicting_duplicate_stops():
    a = pd.DataFrame({"nsdl_code": ["X"], "plan": ["regular"], "ter_date": [date(2026, 8, 1)], "total": [1.5],
                      "source_file": ["a"]})
    with pytest.raises(TerFormatError, match="conflicting"):
        combine([a, a.assign(total=1.6, source_file="b")])


def test_long_gap_not_filled_and_coverage_counts():
    days = [date(2026, 8, d) for d in (1, 2, 3, 8, 9)]                      # 4-day hole (4..7)
    t = pd.DataFrame({"fund_id": "f", "plan": "regular", "ter_date": days, "total": 1.0})
    d = fill_daily(t)
    assert date(2026, 8, 5) not in set(d.ter_date)
    cov = coverage(d, ["f"], start=date(2026, 8, 1), end=date(2026, 8, 31))
    r = cov[cov.plan == "regular"].iloc[0]
    assert (r.observed, r.filled, r.status) == (5, 0, "partial")


def test_unknown_layout_rejected():
    with pytest.raises(TerFormatError):
        detect_format(["NSDL Scheme Code", "Scheme Name", "Scheme Type", "Scheme Category", "TER Date", "Foo"])
