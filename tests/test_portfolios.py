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
