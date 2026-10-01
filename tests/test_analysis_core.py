"""Hand-worked examples for src/analysis/core.py (invented numbers chosen to check on paper; not data)."""
import pytest

from src.analysis.core import OUT_KEY, beta_alpha, classify, decompose, passive_construct_as, stable_band
from src.metrics.core import MetricInputError


def test_decompose_hand_example():
    # bench A .6, B .4 ; fund A .5, B .3, X .2 (X outside the index)
    # within = .5(|.5-.6| + |.3-.4|) = .10 ; out part = .5 * .2 = .10 ; AS = .20 ; out-of-index weight .20
    d = decompose({"A": .5, "B": .3, "X": .2}, {"A": .6, "B": .4})
    assert d["active_share"] == pytest.approx(.20) and d["within_part"] == pytest.approx(.10)
    assert d["out_part"] == pytest.approx(.10) and d["out_of_index_weight"] == pytest.approx(.20)
    assert d["active_share"] == pytest.approx(d["within_part"] + d["out_part"])
    assert d["active_share"] >= d["out_of_index_weight"] - 1e-15


def test_passive_construct_hand_example():
    # bench (Nifty 100 stand-in): A .5, B .3, C .2 ; index fund (Nifty 50 stand-in): A .625, B .375 (no C)
    # construct = .8 x index fund + .2 outside: A .5, B .3, OUT .2
    # AS = .5(|.5-.5| + |.3-.3| + |0-.2| + |.2-0|) = .20
    b = {"A": .5, "B": .3, "C": .2}
    assert passive_construct_as({"A": .625, "B": .375}, b) == pytest.approx(.20)
    # 100% in the benchmark itself, nothing outside -> 0
    assert passive_construct_as(b, b, in_share=1.0) == 0.0
    # 80% benchmark + 20% outside -> .5(.2 + .2) = .20: the sleeve alone buys 20% active share
    assert passive_construct_as(b, b) == pytest.approx(.20)
    with pytest.raises(MetricInputError):
        passive_construct_as(b, {**b, OUT_KEY: 0.0})


def test_beta_alpha_hand_example():
    # fund = 0.9 x bench + 0.0001 every day -> beta 0.9, daily alpha 0.0001, annual 0.0252
    b = [0.01, -0.02, 0.015, -0.005, 0.0, 0.02, -0.01, 0.005, -0.015, 0.01] * 3
    f = [0.9 * x + 0.0001 for x in b]
    r = beta_alpha(f, b)
    assert r["beta"] == pytest.approx(0.9, abs=1e-12) and r["alpha_ann"] == pytest.approx(0.0252, abs=1e-12)


def test_classify_rules():
    assert classify(0.70, -0.05, 0.40) == "truly_active"
    assert classify(0.30, 0.02, 0.40) == "closet"
    assert classify(0.30, -0.01, 0.40) == "closet_underperforming"
    assert classify(float("nan"), 0.0, 0.40) == "not_classified"


def test_sub_index_plus_sleeve_collapses_to_the_sleeve():
    """Why '80% Nifty 50 ETF + 20% outside' can't anchor the threshold (D-057): if 0.8 x every sub-index weight is
    below its benchmark weight, the within-index part equals the shortfall (0.2) and AS = 0.5 x (0.2 + 0.2) = 0.20,
    whatever the sub-index. Bench A .45 B .35 C .20; sub-index A .5625 B .4375 (0.8x: .45/.35, both <= bench)."""
    b = {"A": .45, "B": .35, "C": .20}
    assert passive_construct_as({"A": .5625, "B": .4375}, b) == pytest.approx(.20)
    # counter-example: once 0.8 x a weight exceeds its benchmark weight, AS rises above 0.20.
    # A .6, B .4 -> .48/.32: .5(|.48-.45| + |.32-.35| + |0-.20| + .20) = .5(.03 + .03 + .20 + .20) = .23
    assert passive_construct_as({"A": .6, "B": .4}, b) == pytest.approx(.23)


def test_stable_band():
    assert stable_band([0.29, 0.37, 0.43, 0.73], 0.40) == (0.37, 0.43)
    lo, hi = stable_band([0.5, 0.6], 0.40)
    assert lo != lo and hi == 0.5          # nothing below -> nan
