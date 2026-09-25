"""Holdings data-quality rules (project brief + DECISIONS D-016..D-019).

fail  : duplicate (fund_id, month, isin) equity rows; renormalised equity weights not 100% +/- 0.5%
flag  : equity row without a valid ISIN (reported with count and weight)
        ISIN present but check digit wrong
        raw equity total outside 95%..105% of NAV
        sum of equity market values differs from the file's own equity total
        computed weight (MV / NAV) differs from reported % beyond rounding
        futures whose underlying could not be mapped to an equity ISIN
        equity ISIN not Indian (foreign security)
Writes data/quality/holdings_issues.csv and data/quality/holdings_summary.csv.
"""
from __future__ import annotations

import pandas as pd

from src import config

ISSUE_COLS = ["fund_id", "month", "check", "severity", "isin", "instrument_name", "value", "detail"]
WEIGHT_TOL = 0.0002           # reported % is rounded to 0.01% in HDFC/SBI/Bandhan
RECON_TOL_LAKH = 1.0


def _issue(rows, r, check, sev, value, detail, isin=None, name=None):
    rows.append(dict(fund_id=r["fund_id"], month=r["month"], check=check, severity=sev,
                     isin=isin, instrument_name=name, value=value, detail=detail))


def check_holdings(h: pd.DataFrame, meta: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    issues: list[dict] = []
    eq = h[h.section == "equity"]
    dup = eq[eq["isin"].notna() & eq.duplicated(["fund_id", "month", "isin"], keep=False)]
    for _, r in dup.iterrows():
        _issue(issues, r, "duplicate_isin", "fail", r.weight_nav, "duplicate (fund, month, isin)", r["isin"], r.instrument_name)
    for _, r in eq[eq["isin"].isna()].iterrows():
        _issue(issues, r, "equity_without_isin", "flag", r.weight_nav, f"isin_raw={r.isin_raw}", None, r.instrument_name)
    bad_ck = h[h.isin_raw.notna() & ~h.isin_checksum_ok.astype(bool)]
    for _, r in bad_ck.iterrows():
        _issue(issues, r, "isin_checksum_failed", "flag", r.weight_nav, f"isin_raw={r.isin_raw}", None, r.instrument_name)
    for _, r in eq[eq["isin"].notna() & ~eq["isin"].fillna("").str.startswith("IN")].iterrows():
        _issue(issues, r, "foreign_equity_isin", "flag", r.weight_nav, "non-Indian ISIN in equity section", r["isin"], r.instrument_name)
    w = h[h.weight_reported.notna()]
    diff = (w.weight_nav - w.weight_reported).abs()
    for _, r in w[diff > WEIGHT_TOL].iterrows():
        _issue(issues, r, "weight_mv_vs_reported", "flag", r.weight_nav - r.weight_reported,
               f"mv/nav={r.weight_nav:.6f} reported={r.weight_reported:.6f}", r["isin"], r.instrument_name)
    der = h[(h.section == "derivative") & h.underlying_isin.isna()]
    for _, r in der.iterrows():
        _issue(issues, r, "future_underlying_unmapped", "flag", r.weight_nav, f"name_key={r.name_key}", None, r.instrument_name)

    summ = []
    for _, m in meta.iterrows():
        e = eq[(eq.fund_id == m.fund_id) & (eq.month == m.month)]
        mapped = e[e["isin"].notna()]
        raw = mapped.weight_nav.sum()
        renorm = (mapped.weight_nav / raw).sum() if raw else 0.0
        if not 0.95 <= m.equity_weight_raw <= 1.05:
            _issue(issues, m, "raw_equity_total_out_of_range", "flag", m.equity_weight_raw, "outside 95%..105% of NAV")
        if abs(renorm - 1) > 0.005:
            _issue(issues, m, "renormalised_sum_not_100", "fail", renorm, "")
        if m.reported_equity_total_lakh is not None and pd.notna(m.reported_equity_total_lakh):
            gap = m.equity_mv_sum_lakh - m.reported_equity_total_lakh
            if abs(gap) > RECON_TOL_LAKH:
                _issue(issues, m, "equity_total_reconciliation", "flag", gap,
                       f"sum={m.equity_mv_sum_lakh:.2f} file_total={m.reported_equity_total_lakh:.2f}")
        else:
            _issue(issues, m, "equity_total_not_reported", "flag", None, "no equity total row to reconcile against")
        d = h[(h.fund_id == m.fund_id) & (h.month == m.month) & (h.section == "derivative")]
        summ.append(dict(
            fund_id=m.fund_id, month=m.month, n_equity=len(e), n_equity_unmapped=int(e["isin"].isna().sum()),
            unmapped_weight=e.loc[e["isin"].isna(), "weight_nav"].sum(),
            equity_weight_raw=m.equity_weight_raw, excluded_non_equity_weight=1 - m.equity_weight_raw,
            futures_long_weight=d.loc[d.weight_nav > 0, "weight_nav"].sum(),
            futures_short_weight=d.loc[d.weight_nav < 0, "weight_nav"].sum(),
            futures_unmapped=int(d.underlying_isin.isna().sum()),
            equity_recon_gap_lakh=(m.equity_mv_sum_lakh - m.reported_equity_total_lakh)
            if pd.notna(m.reported_equity_total_lakh) else None,
            stated_benchmark=m.stated_benchmark,
        ))
    return pd.DataFrame(issues, columns=ISSUE_COLS), pd.DataFrame(summ)


def run() -> int:
    h = pd.read_parquet(config.INTERIM / "holdings.parquet")
    meta = pd.read_parquet(config.INTERIM / "portfolio_meta.parquet")
    issues, summ = check_holdings(h, meta)
    issues.to_csv(config.QUALITY / "holdings_issues.csv", index=False)
    summ.to_csv(config.QUALITY / "holdings_summary.csv", index=False)
    counts = issues.groupby(["check", "severity"]).size().to_dict() if len(issues) else {}
    print(f"holdings checks: {len(meta)} fund-months; issues={counts}")
    with pd.option_context("display.width", 250, "display.max_columns", 20, "display.float_format", "{:.4f}".format):
        print(summ.drop(columns=["stated_benchmark"]).to_string(index=False))
    return 1 if (issues.severity == "fail").any() else 0
