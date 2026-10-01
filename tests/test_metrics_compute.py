"""P4 integration: the code in src/metrics/compute.py run on the warehouse fixture (tests/fixtures/warehouse, verbatim
subsets of real P2 outputs; see tests/test_warehouse.py)."""
import shutil
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from src.metrics import compute
from src.warehouse.build import build

FIX = Path(__file__).parent / "fixtures" / "warehouse"


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    d = tmp_path_factory.mktemp("m")
    shutil.copytree(FIX, d / "in")
    build(d / "wh.duckdb", d / "in" / "interim", d / "in" / "reference", window=(date(2026, 1, 1), date(2026, 12, 31)))
    c = duckdb.connect(str(d / "wh.duckdb"), read_only=True)
    yield c
    c.close()


def test_active_share_equals_formula_on_the_mart(con):
    a = compute.active_share_monthly(con)
    assert set(zip(a.fund_id, a.month)) == {("kotak_mahindra_lc", "2026-07"), ("icici_prudential_lc", "2026-07"),
                                            ("dsp_lc", "2026-03")}
    w = con.execute("SELECT * FROM marts.fund_month_weights").df()
    assert not w.non_ordinary.any()                          # nothing to drop in the fixture: plain formula applies
    for r in a.itertuples():
        g = w[(w.fund_id == r.fund_id) & (pd.to_datetime(w.month).dt.strftime("%Y-%m") == r.month)]
        assert r.active_share_main == pytest.approx(0.5 * (g.w_fund_main - g.w_bench).abs().sum(), abs=1e-12)
        assert r.active_share_equity_only == pytest.approx(0.5 * (g.w_fund_equity_only - g.w_bench).abs().sum(), abs=1e-12)
        assert 0 < r.active_share_main < 1 and r.dropped_main == 0
    k = a.set_index("fund_id").loc["kotak_mahindra_lc"]
    assert k.active_share_main != pytest.approx(k.active_share_equity_only, abs=1e-6)   # futures change the answer


def test_rolling_windows_refuse_partial_history(con):
    rr = compute.returns_rolling(con)
    assert len(rr) > 0 and (rr.status == "insufficient_history").all()   # fixture holds ~8 returns
    assert "tracking_error" not in rr.columns or rr.tracking_error.isna().all()


def test_turnover_needs_consecutive_months(con):
    t = compute.turnover_monthly(con)
    assert t.empty                                          # fixture months (Mar, Jul) are not consecutive
