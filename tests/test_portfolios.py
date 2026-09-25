"""Portfolio parser tests on the REAL Aug-2026 AMC files (unedited copies, D-008).
Every expected value below was read from the source file itself, not computed by the parser."""
import shutil
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src import config
from src.ingest.portfolio_common import PortfolioFormatError, isin_valid, to_number
from src.ingest.portfolios import map_derivative_underlyings, name_key, parse_file, scheme_index
from src.quality.holdings_checks import check_holdings

FX = Path(__file__).parent / "fixtures" / "portfolios"
IDX = scheme_index(pd.read_csv(config.REFERENCE / "scheme_map.csv"))


def _parse(slug):
    frames, metas, log = [], [], []
    for f in sorted((FX / slug).iterdir()):
        fr, me, lg = parse_file(f, slug, IDX)
        frames += fr; metas += me; log += lg
    return pd.concat(frames, ignore_index=True), pd.DataFrame(metas).set_index("fund_id"), log


@pytest.fixture(scope="module")
def parsed():
    out = {s: _parse(s) for s in ("bandhan", "hdfc", "icici_prudential", "sbi")}
    h = pd.concat([v[0] for v in out.values()], ignore_index=True)
    meta = pd.concat([v[1] for v in out.values()])
    h, _ = map_derivative_underlyings(h)
    return h, meta, {s: v[2] for s, v in out.items()}


# ---------------------------------------------------------------- helpers
@pytest.mark.parametrize("s,ok", [("INE090A01021", True), ("INE040A01034", True), ("IN0020250042", True),
                                  ("INE090A01022", False), ("INE090A0102", False), (None, False)])
def test_isin_check_digit(s, ok):
    assert isin_valid(s) is ok


@pytest.mark.parametrize("raw,val", [(" 32,850,000 ", 32850000.0), (" (7,208.31)", -7208.31), (0.0885, 0.0885),
                                     ("$", None), ("^", None), (" NIL ", None), ("Nil", None), (None, None)])
def test_to_number_real_cell_formats(raw, val):
    assert to_number(raw) == val


def test_name_key_strips_expiry_and_suffixes():
    assert name_key("Kotak Mahindra Bank Ltd. 29.09.2026") == name_key("Kotak Mahindra Bank Limited")
    assert name_key("Hero Motocorp Ltd. $$") == name_key("Hero MotoCorp Ltd.")


# ---------------------------------------------------------------- per-AMC facts from the files
def test_all_files_dated_31_aug_2026_and_lookahead_date(parsed):
    h, meta, _ = parsed
    assert set(meta["as_of"]) == {date(2026, 8, 31)}
    assert set(h["available_from"]) == {date(2026, 9, 11)}          # D-009


def test_equity_sums_reconcile_to_each_files_own_total(parsed):
    _, meta, _ = parsed
    gap = (meta["equity_mv_sum_lakh"] - meta["reported_equity_total_lakh"]).abs()
    assert (gap < 0.01).all(), gap.to_dict()


def test_bandhan(parsed):
    h, meta, _ = parsed
    assert meta.loc["bandhan_lc", "n_equity_rows"] == 69
    assert meta.loc["bandhan_n100", "n_equity_rows"] == 100
    assert meta.loc["bandhan_lc", "nav_lakh"] == pytest.approx(217999.3010262962)
    r = h[(h.fund_id == "bandhan_lc") & (h["isin"] == "INE090A01021")].iloc[0]
    assert r.market_value_lakh == pytest.approx(19283.91) and r.weight_reported == pytest.approx(0.0885)
    assert meta.loc["bandhan_n100", "equity_weight_raw"] == pytest.approx(26962.83 / 26562.851408509498)


def test_hdfc_percent_units_and_sponsor_marker(parsed):
    h, meta, _ = parsed
    hd = h[h.fund_id == "hdfc_lc"]
    r = hd[hd["isin"] == "INE090A01021"].iloc[0]
    assert r.weight_reported == pytest.approx(0.1005)               # file says 10.05 (percent)
    assert hd.loc[hd["isin"] == "INE040A01034", "instrument_name"].iloc[0] == "HDFC Bank Ltd."   # '£' stripped
    assert meta.loc["hdfc_lc", "n_equity_rows"] == 47
    gsec = hd[hd["isin"] == "IN0020250042"].iloc[0]
    assert gsec.section == "non_equity"


def test_icici_futures_signed_and_derivative_sheet_skipped(parsed):
    h, meta, logs = parsed
    ic = h[h.fund_id == "icici_prudential_lc"]
    d = ic[ic.section == "derivative"].set_index("instrument_name")
    assert len(d) == 7
    assert d.loc["Hero Motocorp Ltd.", "market_value_lakh"] == pytest.approx(-11298.32)
    assert d.loc["Hero Motocorp Ltd.", "underlying_isin"] == "INE158A01026"
    assert any("[Derivative]: skipped" in s for s in logs["icici_prudential"])
    assert meta.loc["icici_prudential_lc", "reported_equity_total_lakh"] == pytest.approx(7641440.37)
    # commercial paper and preference shares carry INE ISINs but are not equity
    assert ic.loc[ic["isin"] == "INE929O14FB3", "section"].iloc[0] == "non_equity"
    assert ic.loc[ic["isin"] == "INE494B04019", "section"].iloc[0] == "non_equity"


def test_sbi_csv_cp1252_brackets_and_long_future(parsed):
    h, meta, _ = parsed
    sb = h[h.fund_id == "sbi_lc"]
    assert meta.loc["sbi_lc", "nav_lakh"] == pytest.approx(5513984.78)
    r = sb[sb["isin"] == "INE090A01021"].iloc[0]
    assert r.quantity == 32850000 and r.weight_reported == pytest.approx(0.0866)
    f = sb[sb.section == "derivative"].iloc[0]
    assert f.market_value_lakh == pytest.approx(41821.50) and f.underlying_isin == "INE237A01036"
    assert meta.loc["sbi_lc", "stated_benchmark"] == "bse 100 tri"


def test_filename_month_must_match_content(tmp_path):
    src = next((FX / "bandhan").glob("*Large Cap*"))
    d = tmp_path / "bandhan"; d.mkdir()
    bad = d / f"2026-07__{src.name}"
    shutil.copy(src, bad)
    with pytest.raises(PortfolioFormatError, match="file-name month"):
        parse_file(bad, "bandhan", IDX)


# ---------------------------------------------------------------- quality rules fire
def test_quality_clean_on_real_files(parsed):
    h, meta, _ = parsed
    issues, summ = check_holdings(h, meta.reset_index())
    assert issues.empty, issues.to_dict("records")
    assert len(summ) == 5


def test_quality_rules_fire_on_corrupted_copies(parsed):
    h, meta, _ = parsed
    h2 = h.copy()
    i = h2.index[(h2.fund_id == "hdfc_lc") & (h2.section == "equity")][0]
    h2.loc[i, "isin"] = None                                           # unmapped equity row
    h2 = pd.concat([h2, h2[(h2.fund_id == "sbi_lc") & (h2["isin"] == "INE090A01021")]])   # duplicate
    m2 = meta.reset_index().copy()
    m2.loc[m2.fund_id == "bandhan_lc", "equity_weight_raw"] = 0.90    # out of range
    issues, _ = check_holdings(h2, m2)
    got = set(zip(issues.check, issues.severity))
    assert ("equity_without_isin", "flag") in got
    assert ("duplicate_isin", "fail") in got
    assert ("raw_equity_total_out_of_range", "flag") in got


# ---------------------------------------------------------------- Motilal: two layouts inside the window
def _motilal(name):
    f = FX / "motilal_oswal" / name
    fr, me, _ = parse_file(f, "motilal_oswal", IDX)
    return pd.concat(fr, ignore_index=True), pd.DataFrame(me).set_index("month")


def test_motilal_old_layout_fraction_units_and_index_future():
    h, m = _motilal("IN_MF_MOTILAL_FACTSHEET_31.03.2026_Final.xlsx")    # filename says FACTSHEET
    assert list(m.index) == ["2026-03"] and m.loc["2026-03", "as_of"] == date(2026, 3, 31)
    r = h[h["isin"] == "INE040A01034"].iloc[0]
    assert r.market_value_lakh == pytest.approx(27067.35)
    assert r.weight_reported == pytest.approx(0.09436815556832857)         # fraction in this layout
    f = h[h.section == "derivative"].iloc[0]
    assert f.derivative_kind == "index_future" and f.instrument_name == "NIFTY April 2026 Future"
    assert f.market_value_lakh == pytest.approx(9795.76)
    assert m.loc["2026-03", "nav_lakh"] == pytest.approx(286827.16)       # GRAND TOTAL after derivatives
    assert abs(m.loc["2026-03", "equity_mv_sum_lakh"] - 275439.72) < 0.01


def test_motilal_new_layout_percent_units_and_isin_code_header():
    h, m = _motilal("Motilal Portfolio 30 April 2026 - Final.xlsx")      # header says 'ISIN Code'
    assert list(m.index) == ["2026-04"]
    eq = h[h.section == "equity"]
    assert eq["isin"].notna().all() and len(eq) == 50
    r = eq[eq["isin"] == "INE040A01034"].iloc[0]
    assert r.weight_reported == pytest.approx(0.0925)                      # file shows 9.25 (percent)


def test_isin_change_detected_for_corporate_action():
    from src.ingest.portfolios import detect_isin_changes
    h = pd.DataFrame({
        "section": "equity", "name_key": "kotak mahindra bank",
        "isin": ["INE237A01028", "INE237A01036"], "month": ["2025-12", "2026-01"]})
    c = detect_isin_changes(h).iloc[0]
    assert (c.old_isin, c.new_isin, bool(c.accepted)) == ("INE237A01028", "INE237A01036", True)


@pytest.mark.parametrize("totals,header,expected", [
    ([("subtotal", 217828.01), ("total", 217828.01)], None, 217828.01),          # Bandhan
    ([("sub total", 3935747.92), ("total", 3935747.92)], None, 3935747.92),      # HDFC
    ([("total", 5399422.11)], None, 5399422.11),                                 # SBI
    ([("total", 6171.89), ("total", 28.62)], None, 6200.51),                     # Motilal Oct-2025 listed + unlisted
    ([], 7641440.37, 7641440.37),                                                # ICICI header row
])
def test_resolve_equity_total(totals, header, expected):
    from src.ingest.portfolio_common import resolve_equity_total
    assert resolve_equity_total(totals, header) == pytest.approx(expected)
