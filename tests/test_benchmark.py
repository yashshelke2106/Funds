"""Benchmark TRI tests. Fixtures are verbatim excerpts of the niftyindices.com downloads (D-008);
overlap/alignment rule tests use small hand-built inputs."""
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.ingest.benchmark import (BenchmarkFormatError, aligned_daily_returns, check_coverage,
                                  combine, parse_tri_file)

FX = Path(__file__).parent / "fixtures"


def test_parse_real_tri_excerpt():
    df = parse_tri_file(FX / "nifty100_tri_excerpt.csv")
    s = df.set_index("date")["tri"]
    assert s[date(2024, 8, 30)] == pytest.approx(35650.62)
    assert s[date(2023, 9, 1)] == pytest.approx(26017.85)
    assert df["source_file"].eq("nifty100_tri_excerpt.csv").all()


def test_price_index_file_rejected():
    with pytest.raises(BenchmarkFormatError, match="PRICE index"):
        parse_tri_file(FX / "nifty100_pr_excerpt.csv")


def test_combine_sorts_and_dedups_identical_overlap():
    a = pd.DataFrame({"date": [date(2024, 9, 2), date(2024, 9, 3)], "tri": [100.0, 101.0], "source_file": "a"})
    b = pd.DataFrame({"date": [date(2024, 9, 3), date(2024, 9, 4)], "tri": [101.0, 102.0], "source_file": "b"})
    out = combine([b, a])
    assert out["date"].tolist() == [date(2024, 9, 2), date(2024, 9, 3), date(2024, 9, 4)]


def test_combine_conflicting_overlap_stops():
    a = pd.DataFrame({"date": [date(2024, 9, 3)], "tri": [101.0], "source_file": "a"})
    b = pd.DataFrame({"date": [date(2024, 9, 3)], "tri": [101.5], "source_file": "b"})
    with pytest.raises(BenchmarkFormatError, match="different TRI values"):
        combine([a, b])


def test_missing_chunk_detected():
    d = list(pd.bdate_range("2023-09-01", "2024-08-30").date) + list(pd.bdate_range("2025-09-01", "2026-08-31").date)
    tri = pd.DataFrame({"date": d, "tri": 100.0})
    with pytest.raises(BenchmarkFormatError, match="gap"):
        check_coverage(tri)


def test_alignment_drops_non_tri_nav_days_and_spans_missing_nav():
    # TRI trades Mon-Wed; fund has NAV Mon, Wed and a Sunday (non-trading) NAV; no NAV on Tue.
    tri = pd.DataFrame({"date": [date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)],
                        "tri": [100.0, 102.0, 103.02]})
    nav = pd.DataFrame({"nav_date": [date(2026, 8, 2), date(2026, 8, 3), date(2026, 8, 5)],
                        "nav": [9.0, 10.0, 10.2]})
    r = aligned_daily_returns(tri, nav)
    assert list(r.index.date) == [date(2026, 8, 5)]          # one 2-day return, Sunday NAV ignored
    assert r["fund_ret"].iloc[0] == pytest.approx(0.02)
    assert r["bench_ret"].iloc[0] == pytest.approx(0.0302)   # 100 -> 103.02 spans Tue, not forward-filled
