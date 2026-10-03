"""Named figures for the written deliverables, read from the pipeline's own output files (D-059).

Every number in the memo, README, interview notes and resume bullets is a placeholder filled from here, so the
documents cannot quote a figure the pipeline did not produce and cannot go stale after a rebuild.
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from src import config
from src.export.powerbi import fund_label

ANALYSIS = config.DATA / "analysis"
METRICS = config.DATA / "metrics"
MINUS = "−"
CLOSET, UNDER, ACTIVE, NOT_CLASSIFIED = "closet", "closet_underperforming", "truly_active", "not_classified"
CLASS_LABEL = {CLOSET: "Closet", UNDER: "Closet, underperforming", ACTIVE: "Truly active"}
TRADING_DAYS = 252


class ReportError(Exception):
    pass


def num(x: float, d: int = 2) -> str:
    """Fixed decimals with a real minus sign; a value that rounds to zero is never shown as negative."""
    s = f"{abs(x):.{d}f}"
    return (MINUS if x < 0 and float(s) != 0 else "") + s


def signed(x: float, d: int = 2) -> str:
    s = num(x, d)
    return s if s.startswith(MINUS) or float(s) == 0 else "+" + s


def pct(x: float, d: int = 2) -> str:
    """Fraction -> percent number, without the % sign: 0.0157 -> '1.57'."""
    return num(x * 100, d)


def spct(x: float, d: int = 2) -> str:
    return signed(x * 100, d)


def indian(x: float, d: int = 0) -> str:
    """Indian digit grouping: 123456.7 -> '1,23,457'."""
    s = f"{abs(x):.{d}f}"
    whole, _, frac = s.partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    out = ",".join(groups + [tail])
    return (MINUS if x < 0 and float(s) != 0 else "") + out + ("." + frac if frac else "")


def t_stat(info_ratio: float, n_obs: int) -> float:
    """t-statistic of the mean daily excess return. IR = annualised excess / annualised TE, so
    t = IR x sqrt(years). Approximate: the pipeline's excess is a difference of annualised compound returns."""
    return info_ratio * math.sqrt(n_obs / TRADING_DAYS)


def names(labels) -> str:
    labels = list(labels)
    if len(labels) <= 1:
        return "".join(labels)
    return ", ".join(labels[:-1]) + " and " + labels[-1]


def rank_phrase(rank: int, n: int) -> str:
    """1 -> 'the lowest of the 17'; 2 -> 'the 2nd lowest of the 17'."""
    if rank == 1:
        return f"the lowest of the {n}"
    suffix = "th" if 10 <= rank % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th")
    return f"the {rank}{suffix} lowest of the {n}"


def load(analysis: Path = ANALYSIS, metrics: Path = METRICS, reference: Path = config.REFERENCE) -> dict[str, pd.DataFrame]:
    files = {"cls": analysis / "fund_classification.csv", "summary": analysis / "class_summary.csv",
             "sens": analysis / "threshold_sensitivity.csv", "floor": analysis / "passive_reference.csv",
             "surv": analysis / "survivorship.csv", "funds": metrics / "fund_summary.csv",
             "rolling": metrics / "returns_rolling.csv", "universe": reference / "universe.csv",
             "proxy": reference / "benchmark_proxy_selection.csv"}
    missing = [str(p) for p in files.values() if not p.exists()]
    if missing:
        raise ReportError("report inputs missing (run the metrics and analysis steps first): " + ", ".join(missing))
    return {k: pd.read_csv(p) for k, p in files.items()}


def window_end_rows(rolling: pd.DataFrame, window: str = "24m") -> pd.DataFrame:
    r = rolling[(rolling.window == window) & (rolling.status == "ok")]
    return r[r.month_end == r.month_end.max()]


def fund_frame(f: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per eligible active fund: classification + regular-plan 24m statistics + display name."""
    reg = window_end_rows(f["rolling"])
    reg = reg[reg.plan == "regular"][["fund_id", "n_obs", "tracking_error", "info_ratio"]].rename(
        columns={"tracking_error": "te_regular_24m", "info_ratio": "ir_regular_24m", "n_obs": "n_obs_regular_24m"})
    d = f["cls"].merge(f["funds"][["fund_id", "scheme_name", "regular_aaum_lakh", "fund_ter_regular_mean"]], on="fund_id",
                       how="left", validate="one_to_one").merge(reg, on="fund_id", how="left", validate="one_to_one")
    d["label"] = d.scheme_name.map(fund_label).str.replace(" - ", " ", regex=False).str.replace(r"\s+Fund$", "", regex=True)
    d["t_regular_24m"] = [t_stat(ir, n) if pd.notna(ir) else float("nan") for ir, n in zip(d.ir_regular_24m, d.n_obs_regular_24m)]
    d["aaum_cr"] = d.regular_aaum_lakh / 100
    # fee above the index fund per unit of active share: what the actively managed part of the portfolio costs
    d["fee_per_active"] = d.gap_pp_regular_vs_bandhan / d.active_share_main_mean
    return d


def fund_table(d: pd.DataFrame) -> str:
    head = ("| Fund | Active share | Regular-plan fee above index fund (pp/yr) | Regular-plan excess vs TRI, 24m (%/yr) | t-stat "
            "| Same, latest 12m (%/yr) | Fee gap at Q4 FY26 AAUM (₹ cr/yr) | Class |\n|---|---:|---:|---:|---:|---:|---:|---|")
    rows = [f"| {r.label} | {num(r.active_share_main_mean)} | {num(r.gap_pp_regular_vs_bandhan)} | {spct(r.excess_regular_24m)} "
            f"| {signed(r.t_regular_24m)} | {spct(r.excess_regular_12m)} | {indian(r.annual_cost_rs_crore_at_q4fy26_aaum)} "
            f"| {CLASS_LABEL[r.class_main]} |"
            for r in d[d.class_main != NOT_CLASSIFIED].sort_values("active_share_main_mean").itertuples()]
    return "\n".join([head] + rows)


def sensitivity_table(sens: pd.DataFrame) -> str:
    label = {"regular_excess_24m": "Regular plan, 24m excess (main)", "direct_excess_24m": "Direct plan, 24m excess",
             "regular_alpha_24m": "Regular plan, 24m beta-adjusted alpha", "regular_excess_12m": "Regular plan, latest 12m excess",
             "rolling12_majority": "Majority of rolling 12m windows negative"}
    m = sens[sens.active_share == "active_share_main_mean"]
    out = ["| Threshold | Underperformance test | Truly active | Closet | Closet, underperforming |", "|---:|---|---:|---:|---:|"]
    for r in m.itertuples():
        out.append(f"| {r.threshold_value:.2f} | {label[r.underperformance]} | {r.truly_active} | {r.closet} | {r.closet_underperforming} |")
    return "\n".join(out)


def key_numbers(f: dict[str, pd.DataFrame]) -> dict[str, str]:
    d = fund_frame(f)
    cls, summ, sens, floor, surv = f["cls"], f["summary"].set_index("class_main"), f["sens"], f["floor"], f["surv"]
    known = d[d.class_main != NOT_CLASSIFIED]
    nc = d[d.class_main == NOT_CLASSIFIED]
    closet, under, active = (d[d.class_main == c] for c in (CLOSET, UNDER, ACTIVE))
    low = d[d.class_main.isin([CLOSET, UNDER])]
    if len(under) != 1:
        raise ReportError(f"the memo template is written for exactly one closet_underperforming fund; the pipeline now "
                          f"gives {len(under)} ({', '.join(under.fund_id)}). Rewrite reports/templates before rendering.")
    for c in (CLOSET, UNDER, ACTIVE):
        if int(summ.loc[c, "funds"]) != int((d.class_main == c).sum()):
            raise ReportError(f"class_summary.csv and fund_classification.csv disagree on the number of {c} funds")
    u = under.iloc[0]

    proxy = f["proxy"][f["proxy"].selected_as_weight_proxy.astype(str).str.lower() == "true"]
    if len(proxy) != 1:
        raise ReportError("expected exactly one benchmark-weight proxy in benchmark_proxy_selection.csv")
    idx_id = proxy.fund_id.iloc[0]
    end = window_end_rows(f["rolling"])
    idx = end[end.fund_id == idx_id].set_index("plan")
    idx_name = fund_label(f["universe"].set_index("fund_id").loc[idx_id, "scheme_name"]).replace("NIFTY", "Nifty")
    idx_xs_reg = float(idx.loc["regular", "excess_ann"])
    if idx_xs_reg >= 0:
        raise ReportError("the templates say the index fund's regular plan trailed the TRI; it no longer does. Rewrite them.")
    below_idx = known[known.excess_regular_24m < idx_xs_reg].sort_values("excess_regular_24m")
    sig = known[known.t_regular_24m.abs() >= 2]
    uni = f["universe"]
    eligible = uni[(uni.role == "active") & (uni.eligible.astype(str).str.lower() == "true")]

    def sens_row(thr: float, measure: str) -> str:
        r = sens[(sens.active_share == "active_share_main_mean") & (sens.threshold_value.round(2) == thr)
                 & (sens.underperformance == measure)].iloc[0]
        return f"{r.truly_active} truly active, {r.closet} closet, {r.closet_underperforming} closet and underperforming"

    surv_n = dict(zip(surv.event, surv.scheme_codes))
    counts = ["threshold_value", "underperformance", "truly_active", "closet", "closet_underperforming"]
    by_def = [g[counts].reset_index(drop=True) for _, g in sens.groupby("active_share", sort=True)]
    same_counts = all(x.equals(by_def[0]) for x in by_def[1:])
    v = {
        # scope
        "window_start": pd.Timestamp(config.WINDOW_START).strftime("%b-%Y"), "window_end": pd.Timestamp(config.WINDOW_END).strftime("%b-%Y"),
        "holdings_start": pd.Timestamp(config.HOLDINGS_START).strftime("%b-%Y"),
        "n_universe_active": str(int((uni.role == "active").sum())), "n_eligible": str(len(eligible)),
        "n_classified": str(len(known)), "n_not_classified": str(len(nc)),
        "n_closet": str(len(closet)), "n_under": str(len(under)), "n_low": str(len(low)), "n_active": str(len(active)),
        "classified_aaum_cr": indian(known.aaum_cr.sum()), "eligible_aaum_cr": indian(d.aaum_cr.sum()),
        "classified_aaum_share": pct(known.aaum_cr.sum() / d.aaum_cr.sum(), 1),
        "low_aaum_share": pct(low.aaum_cr.sum() / known.aaum_cr.sum(), 0), "active_aaum_share": pct(active.aaum_cr.sum() / known.aaum_cr.sum(), 0),
        "low_aaum_cr": indian(low.aaum_cr.sum()),
        # threshold and floors
        "threshold": num(float(cls.threshold_main.iloc[0])), "band_low": num(float(cls.stable_band_low.iloc[0]), 3),
        "band_high": num(float(cls.stable_band_high.iloc[0]), 3),
        "band_low_fund": d.loc[(d.active_share_main_mean - cls.stable_band_low.iloc[0]).abs().idxmin(), "label"],
        "band_high_fund": d.loc[(d.active_share_main_mean - cls.stable_band_high.iloc[0]).abs().idxmin(), "label"],
        "floor_n50": num(floor.nifty50_etf_as.mean()), "floor_n50_min": num(floor.nifty50_etf_as.min()),
        "floor_n50_max": num(floor.nifty50_etf_as.max()), "floor_sleeve": num(floor.index_plus_sleeve_as.mean()),
        "as_min": num(known.active_share_main_mean.min()), "as_min_fund": known.loc[known.active_share_main_mean.idxmin(), "label"],
        "as_max": num(known.active_share_main_mean.max()), "as_max_fund": known.loc[known.active_share_main_mean.idxmax(), "label"],
        "as_second_max": num(known.active_share_main_mean.nlargest(2).iloc[1]),
        "n_as_under_050": str(int((known.active_share_main_mean < 0.50).sum())), "n_as_under_060": str(int((known.active_share_main_mean < 0.60).sum())),
        # classes
        "closet_fee_min": num(summ.loc[CLOSET, "fee_gap_pp_min"]), "closet_fee_max": num(summ.loc[CLOSET, "fee_gap_pp_max"]),
        "closet_fee_mean": num(summ.loc[CLOSET, "fee_gap_pp_mean"]), "closet_rs_lakh": indian(summ.loc[CLOSET, "rs_per_lakh_2y_mean"]),
        "closet_cr": indian(summ.loc[CLOSET, "annual_fee_gap_rs_crore_at_q4fy26_aaum"]),
        "low_cr": indian(summ.loc[[CLOSET, UNDER], "annual_fee_gap_rs_crore_at_q4fy26_aaum"].sum()),
        "active_cr": indian(summ.loc[ACTIVE, "annual_fee_gap_rs_crore_at_q4fy26_aaum"]),
        "classified_cr": indian(summ.loc[[CLOSET, UNDER, ACTIVE], "annual_fee_gap_rs_crore_at_q4fy26_aaum"].sum()),
        "active_fee_mean": num(summ.loc[ACTIVE, "fee_gap_pp_mean"]),
        "low_fee_mean": num(low.gap_pp_regular_vs_bandhan.mean()), "low_fee_min": num(low.gap_pp_regular_vs_bandhan.min()),
        "low_fee_max": num(low.gap_pp_regular_vs_bandhan.max()), "low_rs_lakh": indian(low.rs_per_lakh_regular_vs_bandhan.mean()),
        "closet_xs_min": spct(summ.loc[CLOSET, "regular_excess_24m_min"]), "closet_xs_max": spct(summ.loc[CLOSET, "regular_excess_24m_max"]),
        "closet_xs_max_fund": closet.loc[closet.excess_regular_24m.idxmax(), "label"],
        "closet_neg12": str(int(summ.loc[CLOSET, "regular_excess_12m_negative"])),
        "low_neg12": str(int((low.excess_regular_12m < 0).sum())),
        "active_xs_min": spct(summ.loc[ACTIVE, "regular_excess_24m_min"]), "active_xs_max": spct(summ.loc[ACTIVE, "regular_excess_24m_max"]),
        "active_neg24": str(int((active.excess_regular_24m < 0).sum())), "active_neg24_funds": names(active[active.excess_regular_24m < 0].label),
        "active_neg12": str(int(summ.loc[ACTIVE, "regular_excess_12m_negative"])),
        "low_fee_per_active": num(low.fee_per_active.mean(), 1), "active_fee_per_active": num(active.fee_per_active.mean(), 1),
        "flag_fee_per_active": num(u.fee_per_active, 1),
        "low_alpha_pos": str(int((low.alpha_ann_regular_24m > 0).sum())),
        "low_median_xs": spct(low.excess_regular_24m.median()), "active_median_xs": spct(active.excess_regular_24m.median()),
        "n_beta_below_1": str(int((known.beta_regular_24m < 1).sum())),
        # the flagged fund
        "flag_fund": u.label, "flag_as": num(u.active_share_main_mean), "flag_overlap": pct(1 - u.active_share_main_mean, 0),
        "flag_xs_reg_24": spct(u.excess_regular_24m), "flag_xs_dir_24": spct(u.excess_direct_24m),
        "flag_alpha_reg": spct(u.alpha_ann_regular_24m), "flag_beta": num(u.beta_regular_24m),
        "flag_xs_reg_12": spct(u.excess_regular_12m), "flag_neg12_windows": str(int(round(u.neg_share_12m_regular * u.n_12m_windows))),
        "flag_n_windows": str(int(u.n_12m_windows)), "flag_fee_gap": num(u.gap_pp_regular_vs_bandhan), "flag_ter": num(u.fund_ter_regular_mean),
        "flag_rs_lakh": indian(u.rs_per_lakh_regular_vs_bandhan), "flag_cr": indian(u.annual_cost_rs_crore_at_q4fy26_aaum),
        "flag_aaum_cr": indian(u.aaum_cr), "flag_te": pct(u.te_regular_24m), "flag_t": signed(u.t_regular_24m),
        "flag_agree": str(int(u.main_label_agreement)), "n_variants": str(int(u.n_variants)),
        "flag_vs_index_fund": spct(u.excess_regular_24m - idx_xs_reg),
        "flag_rank_phrase": rank_phrase(int((known.excess_regular_24m < u.excess_regular_24m).sum()) + 1, len(known)),
        # index fund and benchmark
        "index_fund": idx_name, "index_ter_reg": num(float(d.fund_ter_regular_mean.sub(d.gap_pp_regular_vs_bandhan).median())),
        "index_xs_reg": spct(idx_xs_reg), "index_lag_reg": pct(-idx_xs_reg), "index_xs_dir": spct(float(idx.loc["direct", "excess_ann"])),
        "index_te_dir": pct(float(idx.loc["direct", "tracking_error"])), "bench_ret_24": spct(float(idx.loc["direct", "bench_return_ann"])),
        "n_below_index_fund": str(len(below_idx)), "below_index_fund_funds": names(below_idx.label),
        "n_obs": str(int(u.n_obs_regular_24m)),
        # significance
        "n_significant": str(len(sig)), "significant_funds": names(sig.label),
        "significant_t": names(signed(t) for t in sig.t_regular_24m),
        # robustness
        "sens_040_24m": sens_row(0.40, "regular_excess_24m"), "sens_040_12m": sens_row(0.40, "regular_excess_12m"),
        "sens_040_roll": sens_row(0.40, "rolling12_majority"), "sens_050_24m": sens_row(0.50, "regular_excess_24m"),
        "sens_060_24m": sens_row(0.60, "regular_excess_24m"),
        "equity_only_note": ("the equity-only definition gives the same counts" if same_counts
                             else "the equity-only definition gives different counts; see data/analysis/threshold_sensitivity.csv"),
        "n_agree_all": str(int((known.main_label_agreement == known.n_variants).sum())),
        "n_agree_main_threshold": str(int((known.agreement_at_main_threshold == known.n_variants_at_main_threshold).sum())),
        "n_variants_main_threshold": str(int(u.n_variants_at_main_threshold)),
        # funds without holdings
        "nc_neg24": str(int((nc.excess_regular_24m < 0).sum())), "nc_fee_mean": num(nc.gap_pp_regular_vs_bandhan.mean()),
        "nc_cr": indian(nc.annual_cost_rs_crore_at_q4fy26_aaum.sum()),
        # survivorship
        "surv_present": str(int(surv_n["present_at_start_and_now"])), "surv_new": str(int(surv_n["not_large_cap_at_window_start"])),
        # tables
        "fund_table": fund_table(d), "sensitivity_table": sensitivity_table(sens),
    }
    return v
