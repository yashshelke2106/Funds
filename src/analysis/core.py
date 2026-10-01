"""P5 analysis definitions (pure functions; tested in tests/test_analysis_core.py). DECISIONS D-057.

Active share splits exactly into two parts. With I = benchmark holdings, O = everything else:
    AS = 0.5 * sum_I |w_f - w_b|  +  0.5 * sum_O |w_f|
and, because sum_I (w_b - w_f) = sum_O w_f, AS >= out-of-index weight. SEBI requires >= 80% in large caps, so up
to ~20% can sit outside the index: a passive SEBI-compliant portfolio (80% index + 20% outside) has AS = 0.20, and
a Nifty 50 ETF scores ~0.16-0.19 vs the Nifty 100. The regulation therefore sets a FLOOR near 0.20, not a ceiling.
A construct of 80% Nifty 50 ETF + 20% outside is NOT a useful anchor: every Nifty 50 stock is then under its Nifty
100 weight, so its AS is exactly 0.20 again (shown in tests). The closet threshold is a user decision (D-057):
0.40, the natural break in the funds' own distribution, with 0.50 / 0.60 as sensitivity.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

import numpy as np

from src.metrics.core import MetricInputError, active_share

OUT_KEY = "__OUT_OF_INDEX__"


def decompose(w_fund: Mapping[str, float], w_bench: Mapping[str, float]) -> dict[str, float]:
    """Active share = within-index part + out-of-index part; also the out-of-index weight itself."""
    a = active_share(w_fund, w_bench)
    out_keys = [k for k in w_fund if w_bench.get(k, 0.0) == 0.0]
    within = 0.5 * math.fsum(abs(w_fund.get(k, 0.0) - v) for k, v in w_bench.items())
    out_part = 0.5 * math.fsum(abs(w_fund[k]) for k in out_keys)
    return dict(active_share=a, within_part=within, out_part=out_part,
                out_of_index_weight=math.fsum(w_fund[k] for k in out_keys))


def passive_construct_as(w_index_fund: Mapping[str, float], w_bench: Mapping[str, float],
                         in_share: float = 0.80) -> float:
    """Active share vs the benchmark of: in_share x a passive index portfolio + (1 - in_share) outside the
    benchmark entirely. With the Nifty 50 ETF and in_share = 0.8 this is the SEBI-compliant no-stock-picking ceiling."""
    if not 0 < in_share <= 1:
        raise MetricInputError("in_share must be in (0, 1]")
    p = {k: in_share * v for k, v in w_index_fund.items()}
    if in_share < 1:
        if OUT_KEY in w_bench:
            raise MetricInputError("benchmark uses the reserved out-of-index key")
        p[OUT_KEY] = 1 - in_share
    return active_share(p, w_bench)


def beta_alpha(fund_ret: Iterable[float], bench_ret: Iterable[float], periods: int = 252) -> dict[str, float]:
    """OLS of fund on benchmark returns: beta = cov/var; alpha per period = mean(f) - beta * mean(b),
    annualised arithmetically (x periods). Removes the mechanical effect of cash (beta < 1) in a falling market."""
    f = np.asarray(list(fund_ret), dtype=float); b = np.asarray(list(bench_ret), dtype=float)
    if len(f) != len(b) or len(f) < 20 or not (np.isfinite(f).all() and np.isfinite(b).all()):
        raise MetricInputError("beta_alpha needs >= 20 aligned finite returns")
    vb = np.var(b, ddof=1)
    if vb == 0:
        raise MetricInputError("benchmark returns have zero variance")
    beta = float(np.cov(f, b, ddof=1)[0, 1] / vb)
    alpha = float(f.mean() - beta * b.mean())
    return dict(beta=beta, alpha_ann=alpha * periods)


def classify(active_share_value: float, excess: float, threshold: float) -> str:
    """'truly_active' if AS >= threshold; else 'closet_underperforming' if excess < 0, else 'closet'."""
    if not np.isfinite(active_share_value):
        return "not_classified"
    if active_share_value >= threshold:
        return "truly_active"
    return "closet_underperforming" if excess < 0 else "closet"


def stable_band(values, threshold: float) -> tuple[float, float]:
    """(highest value below the threshold, lowest value at or above it): any threshold strictly inside this band
    gives the same classification."""
    v = sorted(float(x) for x in values if np.isfinite(x))
    below = [x for x in v if x < threshold]; above = [x for x in v if x >= threshold]
    return (below[-1] if below else float("nan"), above[0] if above else float("nan"))
