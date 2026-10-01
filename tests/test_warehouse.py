"""Warehouse (P3, D-054) tests.

Fixtures in tests/fixtures/warehouse/ are verbatim row subsets of the real P2 outputs (no value altered):
holdings for Kotak and ICICI (Jul-2026: long and short stock futures, NIFTY and Bank Nifty index futures, a
no-ISIN row), DSP (Mar-2026: an option), the benchmark proxy and both reference ETFs for those months; NAV,
TRI and TER for 27-Jan..06-Feb-2026, which holds a TRI day with no NAV (01-Feb Budget session) and a NAV day
off the TRI calendar (Sat 31-Jan). Expected values are computed independently in pandas from the same rows.
Each SQL test file has a mutation test proving it fails when its rule is broken: the input copy is altered
in a temp dir, never the committed fixture.
"""
import shutil
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from src.quality.holdings_checks import INDEX_FUTURE_REFERENCE, index_future_key
from src.warehouse.build import WarehouseTestError, build

FIX = Path(__file__).parent / "fixtures" / "warehouse"
WINDOW = (date(2026, 1, 1), date(2026, 12, 31))


def _copy(tmp_path):
    d = tmp_path / "in"
    shutil.copytree(FIX, d)
    return d


def _build(tmp_path, inp=None):
    inp = inp or _copy(tmp_path)
    db = tmp_path / "wh.duckdb"
    counts = build(db, inp / "interim", inp / "reference", window=WINDOW)
    return counts, duckdb.connect(str(db), read_only=True)


@pytest.fixture(scope="module")
def wh(tmp_path_factory):
    counts, con = _build(tmp_path_factory.mktemp("wh"))
    yield counts, con
    con.close()


def q(con, sql):
    return con.execute(sql).df()


def test_builds_and_every_sql_test_passes(wh):
    counts, _ = wh
    assert counts["tests"] == 8
    assert counts["marts.fund_month"] == 9 and counts["marts.fund"] == 4


def test_w_main_matches_independent_pandas(wh):
    _, con = wh
    h = pd.read_parquet(FIX / "interim" / "holdings.parquet")
    eq = h[h.section == "equity"].copy(); eq["k"] = eq["isin"].fillna("NOISIN:" + eq["name_key"])
    sf = h[h.derivative_kind == "stock_future"].copy(); sf["k"] = sf["underlying_isin"]
    ref = h[h.fund_id.isin(INDEX_FUTURE_REFERENCE.values()) & (h.section == "equity") & h["isin"].notna()].copy()
    ref["w"] = ref.weight_nav / ref.groupby(["fund_id", "month"]).weight_nav.transform("sum")
    ix = h[h.derivative_kind == "index_future"].copy()
    ix["ref"] = ix.instrument_name.map(lambda n: INDEX_FUTURE_REFERENCE[index_future_key(n)])
    ixl = ix.merge(ref[["fund_id", "month", "isin", "w"]].rename(columns={"fund_id": "ref", "isin": "k"}), on=["ref", "month"])
    ixl["weight_nav"] = ixl.weight_nav * ixl.w
    cols = ["fund_id", "month", "k", "weight_nav"]
    t = pd.concat([eq[cols], sf[cols], ixl[cols]]).groupby(["fund_id", "month", "k"]).weight_nav.sum().reset_index()
    t["w"] = t.weight_nav / t.groupby(["fund_id", "month"]).weight_nav.transform("sum")
    s = q(con, "SELECT fund_id, strftime(month, '%Y-%m') AS month, sec_key AS k, w_main FROM intermediate.fund_weights")
    j = t.merge(s, on=["fund_id", "month", "k"], how="outer", indicator=True)
    assert (j._merge == "both").all()
    assert (j.w - j.w_main).abs().max() < 1e-12
    assert len(ix) >= 2 and set(ix.ref) == set(INDEX_FUTURE_REFERENCE.values())   # both index kinds exercised


def test_short_futures_net_against_held_stock(wh):
    """The fixture's 4 short stock futures are all on stocks the fund holds (ICICI: ONGC, Hero, Asian Paints;
    Kotak: Tech Mahindra). w_main = (equity + stock future + index look-through) / the fund-month total, so the
    short nets down. Tech Mahindra is a Nifty 50 stock, so Kotak's NIFTY future also adds look-through to it: all
    three components meet on one row."""
    _, con = wh
    d = q(con, "SELECT e.fund_id, e.month, e.sec_key, e.equity_w, e.stock_fut_w, e.index_fut_w, f.w_main, "
               "sum(e.equity_w + e.stock_fut_w + e.index_fut_w) OVER (PARTITION BY e.fund_id, e.month) AS tot "
               "FROM intermediate.fund_exposure e JOIN intermediate.fund_weights f USING (fund_id, month, sec_key)")
    shorts = d[(d.stock_fut_w < 0) & (d.equity_w > 0)]
    assert len(shorts) == 4
    assert ((shorts.equity_w + shorts.stock_fut_w + shorts.index_fut_w) / shorts.tot - shorts.w_main).abs().max() < 1e-15
    assert (shorts.loc[shorts.fund_id == 'kotak_mahindra_lc', 'index_fut_w'] > 0).all()


def test_option_kept_apart_and_no_isin_flagged(wh):
    _, con = wh
    o = q(con, "SELECT * FROM intermediate.fund_exposure WHERE is_option")
    assert len(o) == 1 and o.fund_id.iloc[0] == "dsp_lc" and o.option_w.iloc[0] > 0
    assert q(con, "SELECT count(*) AS n FROM intermediate.fund_weights WHERE sec_key LIKE 'OPTION:%'").n.iloc[0] == 0
    n = q(con, "SELECT * FROM marts.fund_month_weights WHERE no_isin")
    assert len(n) == 1 and n.fund_id.iloc[0] == "icici_prudential_lc"


def test_benchmark_aligned_on_the_union_of_securities(wh):
    _, con = wh
    d = q(con, "SELECT fund_id, month, count(*) AS n, sum(w_bench) AS b, sum(w_fund_main) AS f, "
               "count(*) FILTER (WHERE w_bench = 0) AS fund_only, count(*) FILTER (WHERE w_fund_main = 0 AND w_fund_equity_only = 0) AS bench_only "
               "FROM marts.fund_month_weights GROUP BY ALL")
    assert set(d.fund_id) == {"kotak_mahindra_lc", "icici_prudential_lc", "dsp_lc"}   # proxy and reference ETFs excluded
    assert ((d.b - 1).abs() < 1e-12).all() and ((d.f - 1).abs() < 1e-12).all()
    assert (d.bench_only > 0).all() and (d.fund_only >= 0).all()


def test_returns_follow_the_tri_calendar(wh):
    _, con = wh
    r = q(con, "SELECT * FROM marts.fund_daily WHERE fund_id = 'kotak_mahindra_lc' AND plan = 'direct' ORDER BY date")
    dates = [str(x)[:10] for x in r.date]
    assert "2026-01-31" not in dates                       # Saturday NAV: not a TRI day, dropped
    feb2 = r[r.date.astype(str).str[:10] == "2026-02-02"].iloc[0]
    assert str(feb2.prev_date)[:10] == "2026-01-30" and feb2.n_tri_days == 2   # spans the 01-Feb Budget session
    nav = pd.read_parquet(FIX / "interim" / "nav.parquet"); tri = pd.read_parquet(FIX / "interim" / "benchmark_tri.parquet")
    code = pd.read_csv(FIX / "reference" / "scheme_map.csv").set_index("fund_id").direct_code["kotak_mahindra_lc"]
    nv = nav[nav.scheme_code == code]
    nv = nv.set_index(nv.nav_date.astype(str)).nav
    tv = tri.set_index(tri.date.astype(str)).tri
    assert feb2.fund_ret == pytest.approx(nv["2026-02-02"] / nv["2026-01-30"] - 1, abs=1e-15)
    assert feb2.bench_ret == pytest.approx(tv["2026-02-02"] / tv["2026-01-30"] - 1, abs=1e-15)   # same span both sides


def test_ter_joined_and_cost_robustness(wh):
    _, con = wh
    t = q(con, "SELECT * FROM intermediate.ter_daily WHERE format = 'new' LIMIT 50")
    raw = pd.read_parquet(FIX / "interim" / "ter_daily.parquet")
    raw = raw[raw.format == "new"].copy()
    raw["d"] = raw.ter_date.astype(str)
    raw = raw.set_index(["fund_id", "plan", "d"])
    for r in t.itertuples():
        x = raw.loc[(r.fund_id, r.plan, str(r.ter_date)[:10])]
        assert r.total_ex_costs == pytest.approx(x.total - (x.brokerage or 0) - (x.txn or 0), abs=1e-12)
    d = q(con, "SELECT count(*) FILTER (WHERE ter_total IS NULL) AS miss, count(*) AS n FROM marts.fund_daily")
    assert d.miss.iloc[0] == 0 and d.n.iloc[0] > 0


def test_look_ahead_dates(wh):
    _, con = wh
    m = q(con, "SELECT month, as_of, available_from FROM marts.fund_month")
    for r in m.itertuples():
        mo = pd.Timestamp(r.month)
        assert pd.Timestamp(r.available_from) == (mo + pd.DateOffset(months=1)).replace(day=11)


# ---- each SQL test can fail ------------------------------------------------------------------
def _mutate_parquet(inp, name, fn):
    p = inp / "interim" / f"{name}.parquet"
    fn(pd.read_parquet(p)).to_parquet(p, index=False)


def _expect(tmp_path, inp, pattern):
    with pytest.raises(WarehouseTestError, match=pattern):
        _build(tmp_path, inp)


def test_t04_missing_reference_month_is_caught(tmp_path):
    inp = _copy(tmp_path)
    _mutate_parquet(inp, "holdings", lambda h: h[~((h.fund_id == "ref_nifty50_motilal") & (h.month == "2026-07"))])
    _expect(tmp_path, inp, "t04_index_future_allocation")


def test_t01_duplicate_ter_row_is_caught(tmp_path):
    inp = _copy(tmp_path)
    _mutate_parquet(inp, "ter_daily", lambda t: pd.concat([t, t.iloc[:1]]))
    _expect(tmp_path, inp, "t01_unique_ter_daily")


def test_t02_zero_equity_fund_month_is_caught(tmp_path):
    inp = _copy(tmp_path)
    def zero(h):
        h = h.copy()
        h.loc[(h.fund_id == "kotak_mahindra_lc") & (h.section == "equity"), "weight_nav"] = 0.0
        return h
    _mutate_parquet(inp, "holdings", zero)
    _expect(tmp_path, inp, "t02_w_equity_only_sum")


def test_t03_meta_mismatch_is_caught(tmp_path):
    inp = _copy(tmp_path)
    def bump(m):
        m = m.copy(); m.loc[m.index[0], "equity_weight_raw"] += 0.001; return m
    _mutate_parquet(inp, "portfolio_meta", bump)
    _expect(tmp_path, inp, "t03_equity_vs_meta")


def test_t05_no_selected_proxy_is_caught(tmp_path):
    inp = _copy(tmp_path)
    p = inp / "reference" / "benchmark_proxy_selection.csv"
    b = pd.read_csv(p); b["selected_as_weight_proxy"] = False; b.to_csv(p, index=False)
    _expect(tmp_path, inp, "t05_one_proxy")


def test_t06_long_nav_gap_is_caught(tmp_path):
    inp = _copy(tmp_path)
    code = pd.read_csv(inp / "reference" / "scheme_map.csv").set_index("fund_id").direct_code["kotak_mahindra_lc"]
    gap = {"2026-01-28", "2026-01-29", "2026-01-30", "2026-02-02", "2026-02-03"}
    _mutate_parquet(inp, "nav", lambda n: n[~((n.scheme_code == code) & n.nav_date.astype(str).isin(gap))])
    _expect(tmp_path, inp, "t06_span_too_long")


def test_t07_wrong_disclosure_date_is_caught(tmp_path):
    inp = _copy(tmp_path)
    def early(h):
        h = h.copy(); h.loc[h.fund_id == "dsp_lc", "available_from"] = h.loc[h.fund_id == "dsp_lc", "as_of"]; return h
    _mutate_parquet(inp, "holdings", early)
    _expect(tmp_path, inp, "t07_available_from")
