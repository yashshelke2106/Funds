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


# ---------------------------------------------------------------- Nippon India: mislabelled .xls extension
def _nippon(name):
    f = FX / "nippon_india" / name
    fr, me, _ = parse_file(f, "nippon_india", IDX)
    return pd.concat(fr, ignore_index=True), pd.DataFrame(me).set_index("month")


def test_nippon_xlsx_disguised_as_xls():
    # real bytes are a zip (openpyxl path); the '.xls' extension alone would make
    # openpyxl refuse the file outright (see read_grid's file-like-object workaround)
    h, m = _nippon("NIMF-MONTHLY-PORTFOLIO-31-Aug-26.xls")
    assert list(m.index) == ["2026-08"] and m.loc["2026-08", "as_of"] == date(2026, 8, 31)
    assert m.loc["2026-08", "nav_lakh"] == pytest.approx(5413366.0189123)
    r = h[h["isin"] == "INE040A01034"].iloc[0]
    assert r.market_value_lakh == pytest.approx(468512.4) and r.weight_reported == pytest.approx(0.0865)
    assert abs(m.loc["2026-08", "equity_mv_sum_lakh"] - 5396154.65) < 0.01
    assert h[h.section == "derivative"].empty        # file states derivative exposure is Nil


def test_nippon_real_legacy_biff_xls():
    # genuine old-format .xls (2/12 months) -- exercises the xlrd branch of read_grid,
    # not just the "extension lies" branch above
    h, m = _nippon("NIMF-MONTHLY-PORTFOLIO-31-Mar-26.xls")
    assert list(m.index) == ["2026-03"] and m.loc["2026-03", "as_of"] == date(2026, 3, 31)
    assert m.loc["2026-03", "nav_lakh"] == pytest.approx(4652052.6, rel=1e-6)
    assert abs(m.loc["2026-03", "equity_mv_sum_lakh"] - 4455077.61) < 0.01


# ---------------------------------------------------------------- Mirae Asset: futures table headed 'Underlying'
def test_mirae_future_read_from_its_own_columns_not_main_table_positions():
    # D-035: the SEBI derivatives table heads its name column 'Underlying'. Before the fix the
    # walker kept the main table's column positions and recorded price (1207.3) as quantity and
    # margin (1191.25) as market value. Expected values are read from row 156 and note (6).
    fr, me, _ = parse_file(FX / "mirae_asset" / "miiof_aug2026.xlsx", "mirae_asset", IDX)
    h, m = pd.concat(fr, ignore_index=True), pd.DataFrame(me).set_index("month")
    assert list(m.index) == ["2026-08"] and m.loc["2026-08", "nav_lakh"] == pytest.approx(3816622.94)
    assert abs(m.loc["2026-08", "equity_mv_sum_lakh"] - 3791024.42) < 0.01
    d = h[h.section == "derivative"]
    assert len(d) == 1
    f = d.iloc[0]
    assert f.instrument_name == "Lodha Developers Ltd." and f.derivative_kind == "stock_future"
    assert f.quantity == 388125 and f.market_value_lakh == pytest.approx(4685.833125)   # note (6): Rs 4,685.83 lacs
    r = h[h["isin"] == "INE090A01021"].iloc[0]
    assert r.market_value_lakh == pytest.approx(342338.15) and r.weight_reported == pytest.approx(0.08969661277055)


def test_unmapped_derivative_subtable_with_numbers_stops_the_parser():
    # an options table ('Underlying','Call / put','Number of contracts',...) is not mapped;
    # a numeric row there must stop the pipeline, never be read with another table's columns
    from src.ingest.portfolio_common import ParserConfig, parse_sheet
    grid = [["Portfolio Statement as on August 31, 2026"],
            ["Name of the Instrument", "ISIN", "Quantity", "Market Value (Rs. in Lakhs)", "% to NAV"],
            ["Equity & Equity related"],
            ["ICICI Bank Ltd.", "INE090A01021", 100, 10.0, 0.5],
            ["GRAND TOTAL", None, None, 20.0, 1.0],
            ["Derivatives disclosure Table"],
            ["Underlying", "Call / put", "Number of contracts", "Option Price when purchased", "Current Price"],
            ["Nifty", "Put", 40, 12.5, 11.0]]
    with pytest.raises(PortfolioFormatError, match="unmapped derivatives"):
        parse_sheet(grid, ParserConfig(amc_slug="t", pct_unit="fraction"), "t")


# ---------------------------------------------------------------- D-036: futures vs the file's stated exposure
def test_axis_aug_2026_future_taken_from_notes_when_main_table_has_none():
    # user decision D-036: main table has no derivatives block; note (5) states Rs 26592.87 lakh and
    # disclosure table B lists one position (NIFTY September 2026 Future, Long, current price 24251.4)
    fr, me, _ = parse_file(FX / "axis" / "Monthly_Portfolio_Axis_Large_Cap_Fund_31_August_2026_92e670845f.xlsx", "axis", IDX)
    h, m = pd.concat(fr, ignore_index=True), pd.DataFrame(me).set_index("month")
    assert list(m.index) == ["2026-08"] and m.loc["2026-08", "nav_lakh"] == pytest.approx(3137566.09)
    assert abs(m.loc["2026-08", "equity_mv_sum_lakh"] - 3010992.4798) < 0.01
    d = h[h.section == "derivative"]
    assert len(d) == 1
    f = d.iloc[0]
    assert f.instrument_name == "NIFTY September 2026 Future" and f.derivative_kind == "index_future"
    assert f.market_value_lakh == pytest.approx(26592.87)
    assert f.quantity / 65 == pytest.approx(1687, abs=1e-3)          # whole NIFTY lots of 65
    assert f.section_label.startswith("derivatives (notes table")
    assert m.loc["2026-08", "stated_derivative_exposure_lakh"] == pytest.approx(26592.87)


@pytest.mark.parametrize("sentence,expected", [   # verbatim note (5)/(6) sentences from the files
    ("(5) Total outstanding exposure in derivative instruments As on Aug 31, 2026 is Rs. 26592.87 Lakhs. For details please refer to Derivative disclosure table.", 26592.87),
    ("(5) Total outstanding exposure in derivative instruments as on 30 April 2026 are Long position Rs. 24853.83 Lacs. For details on derivative positions", 24853.83),
    ("(6)  Total outstanding exposure in derivative instruments as on August 31 2026.  is Rs 4,685.83 lacs and their percentage to net asset value is 0.12%.", 4685.83),
    ("(5) Total outstanding exposure in derivative instruments As on Aug 31, 2026 is Nil. Disclosure for derivative transactions", None),
])
def test_stated_derivative_exposure_note_wordings(sentence, expected):
    from src.ingest.portfolio_common import stated_derivative_exposure
    got = stated_derivative_exposure([[None, sentence]])
    assert got == (None if expected is None else pytest.approx(expected))


def _grid_with_notes(note, extra):
    return ([["Portfolio Statement as on August 31, 2026"],
             ["Name of the Instrument", "ISIN", "Quantity", "Market Value (Rs. in Lakhs)", "% to NAV"],
             ["Equity & Equity related"],
             ["ICICI Bank Ltd.", "INE090A01021", 100, 10.0, 0.5],
             ["GRAND TOTAL", None, None, 20.0, 1.0],
             [note],
             ["Derivatives disclosure Table"]] + extra)


def test_squared_off_contract_summary_is_not_read_as_a_position():
    # Nippon Apr-2026 layout: counts / notional / P&L of contracts closed during the month
    from src.ingest.portfolio_common import ParserConfig, parse_sheet
    grid = _grid_with_notes("(5) Total outstanding exposure in derivative instruments is Nil.", [
        ["Total Number of contract where future were bought", "Total Number of contract where future were sold",
         "Gross Notional Value of contracts where futures were bought ( In Rs.)", "Net Profit/Loss value"],
        [1430, 0, 598598000, 12073761.7]])
    ps = parse_sheet(grid, ParserConfig(amc_slug="t", pct_unit="fraction"), "t")
    assert not any(r["section"] == "derivative" for r in ps.rows)


def test_futures_not_matching_stated_exposure_stop_the_parser():
    from src.ingest.portfolio_common import DerivativeExposureMismatch, ParserConfig, parse_sheet
    grid = _grid_with_notes("(5) Total outstanding exposure in derivative instruments is Rs. 500.00 Lakhs.", [])
    with pytest.raises(DerivativeExposureMismatch, match="stated derivative exposure"):
        parse_sheet(grid, ParserConfig(amc_slug="t", pct_unit="fraction"), "t")


# ---------------------------------------------------------------- D-037: '(d) Government Securities' after equity
def test_enumerated_government_securities_block_ends_the_equity_section():
    # ABSL May-2026 layout: equity Total, then '(d) Government Securities' with a GoI bond
    from src.ingest.portfolio_common import ParserConfig, parse_sheet
    grid = [["Portfolio Statement as on May 31, 2026"],
            ["Name of the Instrument / Issuer", "ISIN", "Industry^ / Rating", "Quantity", "Market value (Rs. in Lakhs)", "% to AUM"],
            ["Equity & Equity related"],
            ["(a) Listed / awaiting listing on Stock Exchange"],
            ["ICICI Bank Ltd.", "INE090A01021", "Banks", 100, 90.0, 0.9],
            ["Sub Total", None, None, None, 90.0, 0.9],
            ["Total", None, None, None, 90.0, 0.9],
            ["(d) Government Securities"],
            ["Government of India (20/06/2027)", "IN0020220037", "Sovereign", 3500000, 10.0, 0.1],
            ["Sub Total", None, None, None, 10.0, 0.1],
            ["Total", None, None, None, 10.0, 0.1],
            ["GRAND TOTAL", None, None, None, 100.0, 1.0]]
    ps = parse_sheet(grid, ParserConfig(amc_slug="t", pct_unit="fraction"), "t")
    sec = {r["isin"]: r["section"] for r in ps.rows}
    assert sec == {"INE090A01021": "equity", "IN0020220037": "non_equity"}
    assert ps.reported_equity_total_lakh == pytest.approx(90.0)


def test_govt_security_in_equity_fails_but_partly_paid_equity_does_not(parsed):
    h, meta, _ = parsed
    eq = h[(h.section == "equity") & h["isin"].notna()]
    g = eq.iloc[[0]].copy(); g["isin"] = "IN0020220037"                 # GoI bond, mis-filed as equity
    pp = eq.iloc[[1]].copy(); pp["isin"] = "IN9397D01014"               # Bharti Airtel partly paid: real equity
    issues, _ = check_holdings(pd.concat([h, g, pp], ignore_index=True), meta.reset_index())
    hit = issues[issues.check == "govt_security_in_equity"]
    assert list(hit["isin"]) == ["IN0020220037"] and set(hit.severity) == {"fail"}


def test_canara_robeco_percent_units_and_debt_block_not_equity():
    f = next((FX / "canara_robeco").glob("*September-2025.xlsx"))
    fr, me, _ = parse_file(f, "canara_robeco", IDX)
    h, m = pd.concat(fr, ignore_index=True), pd.DataFrame(me).set_index("month")
    assert list(m.index) == ["2025-09"] and m.loc["2025-09", "nav_lakh"] == pytest.approx(1651466.63)
    assert abs(m.loc["2025-09", "equity_mv_sum_lakh"] - 1602373.76) < 0.01
    r = h[h["isin"] == "INE040A01034"].iloc[0]
    assert r.market_value_lakh == pytest.approx(155987.89) and r.weight_reported == pytest.approx(0.0945)   # file: 9.45
    assert h.loc[h["isin"] == "INE494B04019", "section"].iloc[0] == "non_equity"        # under 'Debt Instruments'


# ---------------------------------------------------------------- D-039: UTI, all schemes stacked in one sheet
def test_uti_block_split_scheme_total_nav_and_futures_with_isin():
    f = next((FX / "uti").glob("2025-10__*.xlsx"))
    fr, me, log = parse_file(f, "uti", IDX)
    assert len(me) == 1 and me[0]["source_sheet"].endswith("#SCHEME CODE017STARTS")
    assert sum("no study scheme" in x for x in log) == 84                 # the other UTI schemes, ignored
    h, m = pd.concat(fr, ignore_index=True), pd.DataFrame(me).set_index("month")
    assert list(m.index) == ["2025-10"] and m.loc["2025-10", "as_of"] == date(2025, 10, 31)   # 'AS OF 31/10/2025'
    assert m.loc["2025-10", "nav_lakh"] == pytest.approx(1324132.74)      # 'TOTAL : UTI - Large Cap Fund' = note (c) NAV at end
    assert abs(m.loc["2025-10", "equity_mv_sum_lakh"] - 1273402.07) < 0.01   # 'TOTAL:  EQUITY AND EQUITY RELATED'
    assert h.loc[h["isin"] == "IN0020240183", "section"].iloc[0] == "non_equity"   # GoI bond under money market
    h, _ = map_derivative_underlyings(h)
    d = h[h.section == "derivative"].set_index("instrument_name")
    assert list(d.index) == ["RELIANCE INDUSTRIES LTD.-25-Nov-2025", "AVENUE SUPERMARTS LTD.-25-Nov-2025"]
    assert d.loc["RELIANCE INDUSTRIES LTD.-25-Nov-2025", "market_value_lakh"] == pytest.approx(7435.12)
    assert d.loc["RELIANCE INDUSTRIES LTD.-25-Nov-2025", "underlying_isin"] == "INE002A01018"   # from the row's own ISIN
    r = h[h["isin"] == "INE090A01021"].iloc[0]
    assert not r.instrument_name.startswith("EQ - ")


def test_uti_demerger_placeholder_codes_mapped_to_real_isins():
    f = next((FX / "uti").glob("2026-04__*.xlsx"))
    fr, me, log = parse_file(f, "uti", IDX)
    h = pd.concat(fr, ignore_index=True)
    ph = h[h["isin_raw"].fillna("").str.startswith("DU")].set_index("isin_raw")["isin"].to_dict()
    assert ph == {"DU1205A01025": "INE1CDF01017", "DU2205A01025": "INE694L01019",
                  "DU3205A01025": "INE704J01044", "DU4205A01025": "INE1CLE01013"}
    assert sum("placeholder" in x for x in log) == 4


def test_units_checked_on_holdings_when_nav_row_has_no_percent():
    from src.ingest.portfolio_common import ParsedSheet, ParserConfig, check_units
    rows = [dict(pct_reported_raw=p, market_value_lakh=mv) for p, mv in
            [(9.27, 113002.93), (8.64, 105295.5), (5.02, 61233.34), (4.83, 58850.4), (3.96, 48225.19)]]
    ps = ParsedSheet("t", date(2026, 8, 31), 1218910.37, None, None, None, rows)
    assert check_units(ps, ParserConfig(amc_slug="t", pct_unit="percent")) == 100.0
    with pytest.raises(PortfolioFormatError, match="holdings imply"):
        check_units(ps, ParserConfig(amc_slug="t", pct_unit="fraction"))


# ---------------------------------------------------------------- D-040: Kotak
def test_kotak_names_from_column_c_futures_in_main_table_and_cnx_indices():
    fr, me, _ = parse_file(FX / "kotak_mahindra" / "K30 (11).xlsx", "kotak_mahindra", IDX)
    h, m = pd.concat(fr, ignore_index=True), pd.DataFrame(me).set_index("month")
    assert list(m.index) == ["2026-08"] and m.loc["2026-08", "nav_lakh"] == pytest.approx(1093711.04)
    assert abs(m.loc["2026-08", "equity_mv_sum_lakh"] - (1046553.66 + 709.55)) < 0.01   # two equity 'Total' blocks
    assert (h.instrument_name.str.strip() != "").all()
    r = h[h["isin"] == "INE090A01021"].iloc[0]
    assert r.instrument_name == "ICICI BANK LTD." and r.weight_reported == pytest.approx(0.0822)
    h, _ = map_derivative_underlyings(h)
    d = h[h.section == "derivative"].set_index("instrument_name")
    assert d.loc["CNX BANK INDEX-SEP2026", "derivative_kind"] == "index_future"
    assert d.loc["CNX NIFTY-SEP2026", "derivative_kind"] == "index_future"
    assert d.loc["CNX BANK INDEX-SEP2026", "market_value_lakh"] == pytest.approx(12503.6352)
    assert d.loc["Tech Mahindra Ltd.-SEP2026", "underlying_isin"] == "INE669C01036"
    assert h.loc[h["isin"] == "INF174K01NE8", "section"].iloc[0] == "non_equity"       # Kotak Liquid fund units


# ---------------------------------------------------------------- D-041: DSP, options are not futures
def test_dsp_index_put_classified_as_option_not_index_future():
    f = next((FX / "dsp").glob("2026-03__*.xlsx"))
    fr, me, log = parse_file(f, "dsp", IDX)
    assert len(me) == 1 and me[0]["source_sheet"] == "Large Cap"
    h, m = pd.concat(fr, ignore_index=True), pd.DataFrame(me).set_index("month")
    assert m.loc["2026-03", "nav_lakh"] == pytest.approx(661960.21)
    assert abs(m.loc["2026-03", "equity_mv_sum_lakh"] - 596639.62) < 0.01
    d = h[h.section == "derivative"].iloc[0]
    assert d.instrument_name == "NIFTY 22000 Put Apr26" and d.derivative_kind == "option"
    assert d.market_value_lakh == pytest.approx(1084.2)
    assert m.loc["2026-03", "index_future_weight"] == 0          # the put adds no index-future exposure


@pytest.mark.parametrize("name,key", [("NTPC Limited Mar26", "ntpc"), ("Tech Mahindra Ltd.-SEP2026", "tech mahindra")])
def test_name_key_strips_compact_month_expiries(name, key):
    assert name_key(name) == key


def test_franklin_net_assets_row_foreign_equity_and_business_day_month_end():
    fr, me, _ = parse_file(FX / "franklin_templeton" / "Monthly-Portfolio-ISIN-27-Feb-2026.xlsx", "franklin_templeton", IDX)
    assert len(me) == 1 and me[0]["source_sheet"] == "FILCF"
    h, m = pd.concat(fr, ignore_index=True), pd.DataFrame(me).set_index("month")
    assert list(m.index) == ["2026-02"] and m.loc["2026-02", "as_of"] == date(2026, 2, 27)
    assert m.loc["2026-02", "nav_lakh"] == pytest.approx(758018.5772128)          # 'Net Assets' row
    assert abs(m.loc["2026-02", "equity_mv_sum_lakh"] - (726807.0930734003 + 13584.63108)) < 0.01
    cog = h[h["isin"] == "US1924461023"].iloc[0]
    assert cog.section == "equity" and cog.weight_reported == pytest.approx(0.0179212376693327)
    assert h.loc[h["isin"] == "IN002025X414", "section"].iloc[0] == "non_equity"       # T-bill


def test_sundaram_mkt_value_header_enumerated_sections_and_unspaced_date():
    # header 'Mkt Value Rs. in Lacs' / '% of Net Asset'; 'A) Equity & Equity Related';
    # date 'for the month ended 30 September2025' (no space before the year)
    fr, me, _ = parse_file(FX / "sundaram" / "monthlyportfolio_101025105519.xlsx", "sundaram", IDX)
    assert len(me) == 1 and me[0]["source_sheet"] == "SUNBCF"
    h, m = pd.concat(fr, ignore_index=True), pd.DataFrame(me).set_index("month")
    assert list(m.index) == ["2025-09"] and m.loc["2025-09", "as_of"] == date(2025, 9, 30)
    assert m.loc["2025-09", "nav_lakh"] == pytest.approx(327953.308815953)
    assert abs(m.loc["2025-09", "equity_mv_sum_lakh"] - 301628.590549) < 0.01
    r = h[h["isin"] == "INE040A01034"].iloc[0]
    assert r.market_value_lakh == pytest.approx(30243.68298) and r.weight_reported == pytest.approx(0.09221948)


def test_quant_futures_book_in_main_table_and_bank_nifty_short():
    fr, me, _ = parse_file(FX / "quant" / "quant_Large_Cap_Fund_Feb_2026.xlsx", "quant", IDX)
    h, m = pd.concat(fr, ignore_index=True), pd.DataFrame(me).set_index("month")
    assert list(m.index) == ["2026-02"] and m.loc["2026-02", "as_of"] == date(2026, 2, 27)
    assert m.loc["2026-02", "nav_lakh"] == pytest.approx(302309.67)
    assert abs(m.loc["2026-02", "equity_mv_sum_lakh"] - 232781.65) < 0.05       # file rounds its own total
    d = h[h.section == "derivative"].set_index("instrument_name")
    hdfc_life = d.loc["HDFC Life Insurance Co Ltd"]
    assert hdfc_life.derivative_kind == "stock_future" and hdfc_life.market_value_lakh == pytest.approx(21756.96)
    bn = d.loc["NSE BANK NIFTY"]
    assert bn.derivative_kind == "index_future" and bn.market_value_lakh == pytest.approx(-45712.29)   # short
    assert d.loc["Eternal Limited", "market_value_lakh"] < 0
    issues, _ = check_holdings(h.assign(underlying_isin=None), pd.DataFrame(me))
    assert not ((issues.check == "isin_checksum_failed") & issues.instrument_name.isin(d.index)).any()   # contract codes not flagged


@pytest.mark.parametrize("name,key", [       # names as printed in the files (D-044)
    ("NIFTY September 2026 Future", "nifty"), ("CNX NIFTY-SEP2026", "nifty"), ("NIFTY 30 Jun 2026", "nifty"),
    ("NSE BANK NIFTY", "banknifty"), ("Bank Nifty Index July 2026 Future", "banknifty"),
    ("CNX BANK INDEX-SEP2026", "banknifty"), ("FINNIFTY Jan 2026", None), ("NIFTY NEXT 50", None)])
def test_index_future_key(name, key):
    from src.quality.holdings_checks import index_future_key
    assert index_future_key(name) == key


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


def test_name_key_strips_month_name_expiry():
    assert name_key("Amber Enterprises India Limited October 2025 Future") == "amber enterprises india"
    assert name_key("NIFTY April 2026 Future") == "nifty"
