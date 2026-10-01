"""P5 integration on the warehouse fixture (verbatim subsets of real P2 outputs; see tests/test_warehouse.py)."""
import shutil
from datetime import date
from pathlib import Path

import duckdb
import pytest

from src.analysis import run
from src.metrics import compute
from src.warehouse.build import build

FIX = Path(__file__).parent / "fixtures" / "warehouse"


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    d = tmp_path_factory.mktemp("a")
    shutil.copytree(FIX, d / "in")
    build(d / "wh.duckdb", d / "in" / "interim", d / "in" / "reference", window=(date(2026, 1, 1), date(2026, 12, 31)))
    c = duckdb.connect(str(d / "wh.duckdb"), read_only=True)
    yield c
    c.close()


def test_decomposition_adds_up_to_p4_active_share(con):
    dec = run.monthly_decomposition(con).set_index(["fund_id", "month"])
    asm = compute.active_share_monthly(con).set_index(["fund_id", "month"])
    assert set(dec.index) == set(asm.index)
    for k, r in dec.iterrows():
        assert r.active_share == pytest.approx(asm.loc[k, "active_share_main"], abs=1e-12)
        assert r.within_part + r.out_part == pytest.approx(r.active_share, abs=1e-12)
        assert r.active_share >= r.out_of_index_weight - 1e-12


def test_passive_floors(con):
    p = run.passive_reference(con)
    assert sorted(p.month) == ["2026-03", "2026-07"]                       # both fixture months have the Nifty 50 ETF
    assert (p.index_plus_sleeve_as.round(12) == 0.2).all()                  # 80% index + 20% outside = 0.20 exactly
    assert p.nifty50_etf_as.between(0.05, 0.40).all()                      # a passive sub-index: low but not zero
