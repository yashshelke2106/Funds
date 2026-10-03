"""P6 export: pure transforms with hand-worked examples, and the validator's ability to fail.
Small invented inputs (formula checks, not data; nothing here enters the pipeline)."""
import pandas as pd
import pytest

from src.export.powerbi import ExportError, KEYS, date_dim, fund_label, growth_of_100, validate, variants_long


def test_growth_of_100_hand_example():
    # window (Jan-1, Jan-4]: returns on Jan-2 +10%, Jan-3 -10%, Jan-4 +5% ; Jan-1 itself is outside (start excluded)
    d = pd.DataFrame({"fund_id": "f", "plan": "direct",
                      "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"]),
                      "fund_ret": [0.50, 0.10, -0.10, 0.05, 0.20], "bench_ret": [0.0, 0.02, 0.0, 0.0, 0.0]})
    g = growth_of_100(d, "2026-01-01", "2026-01-04").set_index("date")
    assert pd.isna(g.loc["2026-01-01", "fund_growth_100"]) and pd.isna(g.loc["2026-01-05", "fund_growth_100"])
    assert g.loc["2026-01-02", "fund_growth_100"] == pytest.approx(110.0)
    assert g.loc["2026-01-03", "fund_growth_100"] == pytest.approx(99.0)          # 110 x 0.9
    assert g.loc["2026-01-04", "fund_growth_100"] == pytest.approx(103.95)        # 99 x 1.05
    assert g.loc["2026-01-04", "bench_growth_100"] == pytest.approx(102.0)


def test_growth_of_100_keeps_plans_apart():
    d = pd.DataFrame({"fund_id": "f", "plan": ["direct", "regular"], "date": pd.to_datetime(["2026-01-02"] * 2),
                      "fund_ret": [0.10, 0.05], "bench_ret": [0.0, 0.0]})
    g = growth_of_100(d, "2026-01-01", "2026-01-31").set_index("plan")
    assert g.loc["direct", "fund_growth_100"] == pytest.approx(110) and g.loc["regular", "fund_growth_100"] == pytest.approx(105)


def test_indian_fiscal_year():
    d = date_dim("2025-03-31", "2025-04-01").set_index("date")
    assert d.loc["2025-03-31", "fiscal_year"] == "FY25" and d.loc["2025-04-01", "fiscal_year"] == "FY26"
    assert d.loc["2025-03-31", "is_month_end"] and not d.loc["2025-04-01", "is_month_end"]


def test_fund_label():
    assert fund_label("BAJAJ FINSERV LARGE CAP FUND") == "Bajaj Finserv Large Cap Fund"
    assert fund_label("BARODA BNP PARIBAS LARGE CAP FUND") == "Baroda BNP Paribas Large Cap Fund"   # acronym kept
    assert fund_label("ICICI Prudential Large Cap Fund (erstwhile Bluechip Fund)") == "ICICI Prudential Large Cap Fund"
    assert fund_label("HDFC NIFTY 100 Index Fund") == "HDFC NIFTY 100 Index Fund"     # mixed case: untouched


def test_variants_long():
    c = pd.DataFrame({"fund_id": ["a"], "class_main": ["closet"],
                      "class__0.40__main__regular_excess_24m": ["closet"],
                      "class__0.50__equity_only__regular_excess_12m": ["closet_underperforming"]})
    v = variants_long(c).sort_values("threshold").reset_index(drop=True)
    assert v.threshold.tolist() == [0.40, 0.50] and v.active_share_version.tolist() == ["main", "equity_only"]
    assert v.agrees_with_main.tolist() == [True, False]


def _tables():
    t = {k: pd.DataFrame({c: [] for c in cols}) for k, cols in KEYS.items()}
    t["dim_fund"] = pd.DataFrame({"fund_id": ["a"], "class_main": ["closet"]})
    t["dim_class"] = pd.DataFrame({"class_main": ["closet"]})
    t["dim_plan"] = pd.DataFrame({"plan": ["direct", "regular"]})
    t["dim_date"] = pd.DataFrame({"date": pd.to_datetime(["2026-01-01"])})
    t["fact_daily"] = pd.DataFrame({"fund_id": ["a"], "plan": ["direct"], "date": pd.to_datetime(["2026-01-01"])})
    for k in ("fact_fund_month",):
        t[k] = pd.DataFrame({"fund_id": [], "month_start": pd.to_datetime([])})
    for k, c in (("fact_rolling", "month_end"), ("fact_ter_daily", "date"), ("passive_floor", "month_start")):
        t[k][c] = pd.to_datetime(t[k][c])
    return t


def test_validate_passes_and_catches_each_failure():
    validate(_tables())
    t = _tables(); t["fact_daily"] = pd.concat([t["fact_daily"]] * 2)
    with pytest.raises(ExportError, match="duplicate"):
        validate(t)
    t = _tables(); t["fact_daily"].loc[0, "fund_id"] = "zzz"
    with pytest.raises(ExportError, match="not in dim_fund"):
        validate(t)
    t = _tables(); t["fact_daily"].loc[0, "date"] = pd.Timestamp("2030-01-01")
    with pytest.raises(ExportError, match="not in dim_date"):
        validate(t)
    t = _tables(); t["fact_daily"].loc[0, "plan"] = "institutional"
    with pytest.raises(ExportError, match="not in dim_plan"):
        validate(t)
    t = _tables(); t["dim_fund"].loc[0, "class_main"] = "mystery"
    with pytest.raises(ExportError, match="not in dim_class"):
        validate(t)
