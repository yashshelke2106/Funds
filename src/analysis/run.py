"""P5: threshold, classification, survivorship, robustness (DECISIONS D-057). Reads the warehouse and data/metrics/;
writes data/analysis/. Classifies only funds with holdings (17); the rest are listed as not classifiable.

Main specification
  active share   12-month mean of w_main (D-020), D-055 exclusions (via compute.iter_weights)
  threshold      0.40 (decided by the user, D-057): the natural break in the 17 funds' distribution (0.369 | 0.433);
                 sensitivity 0.50 / 0.60; the stable band (highest below, lowest above) is reported
  underperforming  regular-plan annualised excess vs Nifty 100 TRI over the 24 months to Aug-2026 < 0 (the plan an
                   investor on a distributor platform holds)
Robustness: thresholds 0.40 / 0.50 / 0.60; equity-only active share; direct plan; regular-plan beta-adjusted alpha
(removes the cash effect); 12-month window aligned with the holdings months; share of negative rolling 12m windows.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from src import config
from src.analysis import core as acore
from src.metrics import compute
from src.metrics import core as mcore

OUT = config.DATA / "analysis"
DB = config.DATA / "warehouse.duckdb"
METRICS = config.DATA / "metrics"
REF50 = "ref_nifty50_motilal"
THRESHOLD_MAIN = 0.40          # D-057, decided by the user
SENSITIVITY = (0.40, 0.50, 0.60)


def monthly_decomposition(con) -> pd.DataFrame:
    rows = []
    for f, m, wm, we, wb, *_ in compute.iter_weights(con):
        d = acore.decompose(wm, wb)
        rows.append(dict(fund_id=f, month=m.strftime("%Y-%m"), **d))
    return pd.DataFrame(rows)


def passive_reference(con) -> pd.DataFrame:
    """Per month: the Nifty 50 ETF's active share vs the Nifty 100 proxy, and the SEBI construct's."""
    bench = {}
    for f, m, wm, we, wb, *_ in compute.iter_weights(con):
        bench.setdefault(m, wb)                      # the benchmark is the same for every fund in a month
    r = con.execute(f"SELECT month, sec_key, w_equity_only FROM intermediate.fund_weights "
                    f"WHERE fund_id = '{REF50}' AND w_equity_only <> 0").df()
    rows = []
    for m, g in r.groupby("month"):
        m = pd.Timestamp(m)
        if m not in bench:
            continue
        w50, _ = mcore.renormalise(dict(zip(g.sec_key, g.w_equity_only)))
        rows.append(dict(month=m.strftime("%Y-%m"),
                         nifty50_etf_as=acore.passive_construct_as(w50, bench[m], in_share=1.0),
                         index_plus_sleeve_as=acore.passive_construct_as(bench[m], bench[m], in_share=0.8)))
    return pd.DataFrame(rows)


def beta_alpha_24m(con, end=config.WINDOW_END) -> pd.DataFrame:
    d = con.execute("SELECT fund_id, plan, date, fund_ret, bench_ret FROM marts.fund_daily").df()
    d["date"] = pd.to_datetime(d.date)
    end = pd.Timestamp(end); start = end - pd.DateOffset(months=24)
    rows = []
    for (f, p), g in d[(d.date > start) & (d.date <= end)].groupby(["fund_id", "plan"]):
        first = d[(d.fund_id == f) & (d.plan == p)].date.min()
        if first > start + pd.Timedelta(days=7) or len(g) < 400:
            continue
        rows.append(dict(fund_id=f, plan=p, **acore.beta_alpha(g.fund_ret, g.bench_ret)))
    return pd.DataFrame(rows)


def run(db: Path = DB, metrics_dir: Path = METRICS, out: Path = OUT) -> dict[str, pd.DataFrame]:
    con = duckdb.connect(str(db), read_only=True)
    try:
        dec = monthly_decomposition(con)
        pref = passive_reference(con)
        ba = beta_alpha_24m(con)
        u = con.execute("SELECT fund_id, role, amc, scheme_name, eligible, report_group FROM staging.universe").df()
    finally:
        con.close()
    fs = pd.read_csv(metrics_dir / "fund_summary.csv")
    rr = pd.read_csv(metrics_dir / "returns_rolling.csv")
    asm = pd.read_csv(metrics_dir / "active_share_monthly.csv")
    fd = pd.read_csv(metrics_dir / "fee_drag.csv")
    t_main = THRESHOLD_MAIN

    end = str(config.WINDOW_END)
    ok = rr[(rr.status == "ok") & (rr.month_end == end)]
    piv = ok.pivot_table(index="fund_id", columns=["plan", "window"], values="excess_ann")
    piv.columns = [f"excess_{p}_{w}" for p, w in piv.columns]
    neg12 = (rr[(rr.status == "ok") & (rr.window == "12m") & (rr.plan == "regular")]
             .groupby("fund_id").excess_ann.agg(neg_share_12m_regular=lambda s: float((s < 0).mean()),
                                                n_12m_windows="size"))
    # 'majority of rolling 12m windows lost' expressed as a signed number so classify() can use it
    neg12["rolling12_majority_signal"] = 0.5 - neg12.neg_share_12m_regular
    bpiv = ba.pivot_table(index="fund_id", columns="plan", values=["beta", "alpha_ann"])
    bpiv.columns = [f"{v}_{p}_24m" for v, p in bpiv.columns]
    d12 = dec.groupby("fund_id").agg(within_part_mean=("within_part", "mean"), out_part_mean=("out_part", "mean"),
                                     out_of_index_weight_mean=("out_of_index_weight", "mean")).reset_index()

    c = (fs[["fund_id", "report_group", "active_share_main_mean", "active_share_equity_only_mean", "tracking_error_24m",
             "turnover_main_mean", "gap_pp_regular_vs_bandhan", "rs_per_lakh_regular_vs_bandhan",
             "annual_cost_rs_crore_at_q4fy26_aaum"]]
         .merge(d12, on="fund_id", how="left").merge(piv, left_on="fund_id", right_index=True, how="left")
         .merge(neg12, left_on="fund_id", right_index=True, how="left")
         .merge(bpiv, left_on="fund_id", right_index=True, how="left")
         .merge(fd[["fund_id", "gap_pp_regular_vs_cheapest", "gap_pp_regular_vs_average", "gap_pp_direct_vs_bandhan",
                    "gap_pp_regular_vs_bandhan_ex_costs"]], on="fund_id", how="left"))
    c["threshold_main"] = t_main
    lo, hi = acore.stable_band(c.active_share_main_mean, t_main)
    c["stable_band_low"], c["stable_band_high"] = lo, hi
    c["class_main"] = [acore.classify(a, e, t_main) for a, e in zip(c.active_share_main_mean, c.excess_regular_24m)]

    # robustness: every (threshold, active-share version, underperformance measure) combination
    variants = {"regular_excess_24m": "excess_regular_24m", "direct_excess_24m": "excess_direct_24m",
                "regular_alpha_24m": "alpha_ann_regular_24m", "regular_excess_12m": "excess_regular_12m",
                "rolling12_majority": "rolling12_majority_signal"}
    sens = []
    for tname, t in [(f"{x:.2f}", x) for x in SENSITIVITY]:
        for asv in ("active_share_main_mean", "active_share_equity_only_mean"):
            for uname, ucol in variants.items():
                cls = [acore.classify(a, e, t) for a, e in zip(c[asv], c[ucol])]
                col = f"class__{tname}__{asv.replace('active_share_', '').replace('_mean', '')}__{uname}"
                c[col] = cls
                k = pd.Series(cls)
                sens.append(dict(threshold=tname, threshold_value=t, active_share=asv, underperformance=uname,
                                 truly_active=int((k == "truly_active").sum()), closet=int((k == "closet").sum()),
                                 closet_underperforming=int((k == "closet_underperforming").sum()),
                                 not_classified=int((k == "not_classified").sum())))
    sens = pd.DataFrame(sens)
    cls_cols = [x for x in c.columns if x.startswith("class__")]
    held = c.active_share_main_mean.notna()
    # how many of the robustness variants give the SAME label as the main specification (not the most common label:
    # the 0.50/0.60 thresholds alone would otherwise outvote the main result for funds just above 0.40)
    c["main_label_agreement"] = [int((c.loc[i, cls_cols] == c.loc[i, "class_main"]).sum()) for i in c.index]
    c["n_variants"] = len(cls_cols)
    at_main = [x for x in cls_cols if x.startswith("class__0.40__")]
    c["agreement_at_main_threshold"] = [int((c.loc[i, at_main] == c.loc[i, "class_main"]).sum()) for i in c.index]
    c["n_variants_at_main_threshold"] = len(at_main)
    c.loc[~held, ["main_label_agreement", "agreement_at_main_threshold"]] = 0

    surv = pd.read_csv(config.REFERENCE / "scheme_events.csv").groupby("event").size().reset_index(name="scheme_codes")

    # one row per class: the figures the memo quotes, computed here rather than by hand
    summ = (c[held].groupby("class_main")
            .agg(funds=("fund_id", "size"), fund_ids=("fund_id", lambda x: ", ".join(sorted(x))),
                 active_share_min=("active_share_main_mean", "min"), active_share_max=("active_share_main_mean", "max"),
                 fee_gap_pp_min=("gap_pp_regular_vs_bandhan", "min"), fee_gap_pp_max=("gap_pp_regular_vs_bandhan", "max"),
                 fee_gap_pp_mean=("gap_pp_regular_vs_bandhan", "mean"),
                 rs_per_lakh_2y_mean=("rs_per_lakh_regular_vs_bandhan", "mean"),
                 annual_fee_gap_rs_crore_at_q4fy26_aaum=("annual_cost_rs_crore_at_q4fy26_aaum", "sum"),
                 regular_excess_24m_min=("excess_regular_24m", "min"), regular_excess_24m_max=("excess_regular_24m", "max"),
                 regular_excess_12m_negative=("excess_regular_12m", lambda x: int((x < 0).sum())))
            .reset_index())

    out.mkdir(parents=True, exist_ok=True)
    res = dict(monthly_decomposition=dec, passive_reference=pref, beta_alpha_24m=ba, fund_classification=c,
               threshold_sensitivity=sens, survivorship=surv, class_summary=summ)
    for k, v in res.items():
        v.to_csv(out / f"{k}.csv", index=False)
    return res
