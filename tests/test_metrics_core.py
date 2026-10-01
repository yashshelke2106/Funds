"""Hand-worked examples for every metric in src/metrics/core.py. Inputs are small invented numbers chosen so the
answer can be checked on paper (these are tests of formulas, not data; nothing here enters the pipeline)."""
import math

import pytest

from src.metrics.core import (MetricInputError, active_share, annualise, fee_drag_per_lakh, information_ratio,
                              period_return, renormalise, tracking_error, turnover)


def test_active_share_hand_example():
    # fund A 50, B 30, C 20 ; bench A 40, B 40, D 20
    # |diffs| = A .10, B .10, C .20, D .20 -> sum .60 -> AS = .30
    f = {"A": .5, "B": .3, "C": .2}
    b = {"A": .4, "B": .4, "D": .2}
    assert active_share(f, b) == pytest.approx(0.30, abs=1e-15)


def test_active_share_bounds():
    w = {"A": .6, "B": .4}
    assert active_share(w, w) == 0.0                                    # index fund vs itself
    assert active_share({"A": 1.0}, {"B": 1.0}) == pytest.approx(1.0)   # no overlap


def test_active_share_rejects_unnormalised():
    with pytest.raises(MetricInputError, match="sum to"):
        active_share({"A": .9}, {"A": 1.0})


def test_renormalise_hand_example():
    # A .5, B .3, P .2 (a preference share) -> drop P -> A .625, B .375 ; dropped 20%
    w, dropped = renormalise({"A": .5, "B": .3, "P": .2}, drop={"P"})
    assert w == pytest.approx({"A": .625, "B": .375})
    assert dropped == pytest.approx(.2)


def test_turnover_hand_example_and_isin_change():
    # month 1: A .6, OLD .4 ; month 2: A .5, NEW .3, C .2 ; OLD->NEW is the same company
    # mapped: A |.5-.6|=.1, NEW |.3-.4|=.1, C .2 -> .4/2 = .20
    prev, curr = {"A": .6, "OLD": .4}, {"A": .5, "NEW": .3, "C": .2}
    assert turnover(prev, curr, {"OLD": "NEW"}) == pytest.approx(0.20)
    # without the map the ISIN change looks like a full sale and purchase: .1 + .4 + .3 + .2 = 1.0 -> .50
    assert turnover(prev, curr) == pytest.approx(0.50)


def test_tracking_error_hand_example():
    # excess 20 days alternating +0.1% / -0.1%: mean 0, each deviation 0.001 ;
    # sample var = 20 * 0.001^2 / 19 ; TE = sqrt(20/19) * 0.001 * sqrt(252)
    x = [0.001, -0.001] * 10
    assert tracking_error(x) == pytest.approx(math.sqrt(20 / 19) * 0.001 * math.sqrt(252), rel=1e-12)
    with pytest.raises(MetricInputError):
        tracking_error(x[:5])


def test_period_return_and_annualise():
    # +10% then -10% -> 1.1 * 0.9 - 1 = -0.01
    assert period_return([0.10, -0.10]) == pytest.approx(-0.01)
    # 21% over 2 years -> 10% a year
    assert annualise(0.21, 2) == pytest.approx(0.10)
    assert annualise(0.05, 1) == 0.05 and annualise(0.05, 0.5) == 0.05   # never annualise up


def test_information_ratio():
    assert information_ratio(-0.02, 0.04) == pytest.approx(-0.5)
    with pytest.raises(MetricInputError):
        information_ratio(0.01, 0.0)


def test_fee_drag_per_lakh_hand_example():
    # gap 1.00 pp for 365 days on Rs 1 lakh = Rs 1,000 ; 0.73 pp for 100 days = 0.73/100/365*100 * 1e5 = Rs 200
    assert fee_drag_per_lakh([1.0] * 365) == pytest.approx(1000.0)
    assert fee_drag_per_lakh([0.73] * 100) == pytest.approx(200.0)
