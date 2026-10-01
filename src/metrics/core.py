"""Metric definitions (P4). Pure functions on numbers; no I/O. Each is unit-tested against a hand-worked example
(tests/test_metrics_core.py). Definitions follow the project brief exactly unless DECISIONS says otherwise.

  active share   0.5 * sum |w_fund_i - w_bench_i| over the union of holdings, both weight sets summing to 1
  turnover       0.5 * sum |w_t,i - w_t-1,i| over the union, after mapping old ISINs to new (D-026)
  tracking error stdev(daily excess returns, ddof=1) * sqrt(252)
  period return  prod(1 + r) - 1; annualised = (1 + R)^(1 / years) - 1 for windows longer than a year
  info ratio     annualised excess return / tracking error
  fee drag       daily TER gap (percentage points) accrued at 1/365 per calendar day
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

import numpy as np

TRADING_DAYS = 252
SUM_TOL = 1e-9


class MetricInputError(ValueError):
    pass


def _check_sum(w: Mapping[str, float], what: str) -> None:
    s = math.fsum(w.values())
    if abs(s - 1) > SUM_TOL:
        raise MetricInputError(f"{what} weights sum to {s!r}, expected 1")


def active_share(w_fund: Mapping[str, float], w_bench: Mapping[str, float]) -> float:
    """0.5 * sum |w_f - w_b| over the union of keys. Both weight sets must already sum to 1."""
    _check_sum(w_fund, "fund"); _check_sum(w_bench, "benchmark")
    keys = set(w_fund) | set(w_bench)
    return 0.5 * math.fsum(abs(w_fund.get(k, 0.0) - w_bench.get(k, 0.0)) for k in keys)


def renormalise(w: Mapping[str, float], drop: Iterable[str] = ()) -> tuple[dict[str, float], float]:
    """Drop keys, rescale the rest to sum to 1. Returns (weights, dropped share of the original total)."""
    drop = set(drop)
    total = math.fsum(w.values())
    kept = {k: v for k, v in w.items() if k not in drop}
    s = math.fsum(kept.values())
    if total == 0 or s == 0:
        raise MetricInputError("nothing left to renormalise")
    return {k: v / s for k, v in kept.items()}, 1 - s / total


def turnover(w_prev: Mapping[str, float], w_curr: Mapping[str, float],
             isin_map: Mapping[str, str] | None = None) -> float:
    """0.5 * sum |w_t - w_t-1| over the union, with old ISINs mapped to new first (D-026). Includes price drift
    as well as trading: a proxy, as the brief says."""
    m = isin_map or {}
    def remap(w):
        out: dict[str, float] = {}
        for k, v in w.items():
            out[m.get(k, k)] = out.get(m.get(k, k), 0.0) + v
        return out
    a, b = remap(w_prev), remap(w_curr)
    _check_sum(a, "previous"); _check_sum(b, "current")
    return 0.5 * math.fsum(abs(b.get(k, 0.0) - a.get(k, 0.0)) for k in set(a) | set(b))


def tracking_error(excess: Iterable[float], min_obs: int = 20) -> float:
    """Annualised: sample standard deviation (ddof=1) of daily excess returns x sqrt(252)."""
    x = np.asarray(list(excess), dtype=float)
    if len(x) < min_obs or not np.isfinite(x).all():
        raise MetricInputError(f"tracking error needs >= {min_obs} finite observations, got {len(x)}")
    return float(np.std(x, ddof=1) * math.sqrt(TRADING_DAYS))


def period_return(rets: Iterable[float]) -> float:
    """Compounded: prod(1 + r) - 1."""
    r = np.asarray(list(rets), dtype=float)
    if len(r) == 0 or not np.isfinite(r).all():
        raise MetricInputError("period return needs finite returns")
    return float(np.prod(1 + r) - 1)


def annualise(total: float, years: float) -> float:
    """(1 + R)^(1/years) - 1. One year (or less) is returned unchanged: no annualising up of short windows."""
    if years <= 0:
        raise MetricInputError("years must be positive")
    if years <= 1:
        return total
    return (1 + total) ** (1 / years) - 1


def information_ratio(ann_excess: float, te: float) -> float:
    if te <= 0:
        raise MetricInputError("tracking error must be positive")
    return ann_excess / te


def fee_drag_per_lakh(daily_gap_pp: Iterable[float], principal: float = 100_000.0) -> float:
    """Rupees on `principal` over the days given: each calendar day accrues gap% / 100 / 365 (simple, not
    compounded on growth, so it is a floor on the true cost)."""
    g = np.asarray(list(daily_gap_pp), dtype=float)
    if not np.isfinite(g).all():
        raise MetricInputError("fee gaps must be finite")
    return float(g.sum() / 100 / 365 * principal)
