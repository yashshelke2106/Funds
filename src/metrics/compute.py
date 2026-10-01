"""P4: compute every metric from the warehouse (D-054) with the definitions in src/metrics/core.py.

Outputs (data/metrics/, rebuilt each run):
  active_share_monthly.csv  fund x month: active share (main = equity + futures, D-020; equity_only = the brief's)
  turnover_monthly.csv      fund x month: turnover vs the previous month (ISIN changes mapped, D-026)
  returns_rolling.csv       fund x plan x month-end: trailing 12m / 24m return, excess, TE, IR
  fee_drag.csv              active fund: TER gap vs the comparator, Rs per Rs 1 lakh, aggregate at Q4 FY26 AUM
  fund_summary.csv          one row per active fund, the inputs P5 classifies on
Exclusions per D-055: options, ICICI 'covered call' rows and non-ordinary securities are dropped and both weight
sets renormalised (dropped share reported); no-ISIN rows stay as non-benchmark holdings.
"""
from __future__ import annotations

import math
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from src import config
from src.metrics import core

OUT = config.DATA / "metrics"
DB = config.DATA / "warehouse.duckdb"
COMPARATOR = "bandhan_n100"                      # D-055
INDEX_FUNDS = ("axis_n100", "bandhan_n100", "hdfc_n100")
WINDOWS = {"12m": 12, "24m": 24}
MIN_OBS = {"12m": 200, "24m": 400}               # a full window has ~245 / ~490 returns


# ---- holdings-based --------------------------------------------------------------------------
def _drop_keys(con) -> pd.DataFrame:
    """Keys excluded by D-055 per fund-month: non-ordinary securities and ICICI's covered-call rows."""
    cc = con.execute("""
        SELECT DISTINCT fund_id, month, 'NOISIN:' || name_key AS sec_key
        FROM staging.holdings
        WHERE section = 'equity' AND isin IS NULL AND lower(instrument_name) LIKE '%covered call%'""").df()
    return cc


def active_share_monthly(con) -> pd.DataFrame:
    w = con.execute("SELECT * FROM marts.fund_month_weights").df()
    cc = _drop_keys(con)
    cc_set = set(zip(cc.fund_id, cc.month.astype(str), cc.sec_key))
    fm = con.execute("SELECT fund_id, month, available_from, role, report_group, option_net, no_isin_weight "
                     "FROM marts.fund_month").df()
    rows = []
    for (f, m), g in w.groupby(["fund_id", "month"]):
        drop = set(g.loc[g.non_ordinary, "sec_key"]) | {k for k in g.sec_key if (f, str(m), k) in cc_set}
        bench, b_drop = core.renormalise(dict(zip(g.sec_key, g.w_bench)), drop)
        out = dict(fund_id=f, month=pd.Timestamp(m).strftime("%Y-%m"), bench_dropped=b_drop, n_dropped_keys=len(drop))
        for v, col in (("main", "w_fund_main"), ("equity_only", "w_fund_equity_only")):
            wf, dropped = core.renormalise(dict(zip(g.sec_key, g[col])), drop)
            wf = {k: x for k, x in wf.items() if x != 0}
            bb = {k: x for k, x in bench.items() if x != 0}
            out[f"active_share_{v}"] = core.active_share(wf, bb)
            out[f"dropped_{v}"] = dropped
            out[f"n_holdings_{v}"] = len(wf)
            out[f"overlap_{v}"] = sum(min(wf.get(k, 0), bb.get(k, 0)) for k in set(wf) | set(bb))
        rows.append(out)
    a = pd.DataFrame(rows)
    fm["month"] = pd.to_datetime(fm.month).dt.strftime("%Y-%m")
    return a.merge(fm, on=["fund_id", "month"], how="left")


def turnover_monthly(con) -> pd.DataFrame:
    w = con.execute("SELECT * FROM marts.fund_month_weights").df()
    cc = _drop_keys(con)
    cc_set = set(zip(cc.fund_id, cc.month.astype(str), cc.sec_key))
    imap = dict(con.execute("SELECT old_isin, new_isin FROM staging.isin_changes").fetchall())
    rows = []
    for f, gf in w.groupby("fund_id"):
        prev = {}
        for m, g in sorted(gf.groupby("month"), key=lambda t: t[0]):
            drop = set(g.loc[g.non_ordinary, "sec_key"]) | {k for k in g.sec_key if (f, str(m), k) in cc_set}
            cur = {}
            for v, col in (("main", "w_fund_main"), ("equity_only", "w_fund_equity_only")):
                wv, _ = core.renormalise(dict(zip(g.sec_key, g[col])), drop)
                cur[v] = {k: x for k, x in wv.items() if x != 0}
            mo = pd.Timestamp(m)
            if prev and (mo.to_period("M") - prev["m"].to_period("M")).n == 1:
                rows.append(dict(fund_id=f, month=mo.strftime("%Y-%m"),
                                 turnover_main=core.turnover(prev["main"], cur["main"], imap),
                                 turnover_equity_only=core.turnover(prev["equity_only"], cur["equity_only"], imap)))
            prev = dict(m=mo, **cur)
    return pd.DataFrame(rows)


# ---- return-based ----------------------------------------------------------------------------
def returns_rolling(con) -> pd.DataFrame:
    d = con.execute("SELECT fund_id, role, plan, date, fund_ret, bench_ret, excess_ret, n_tri_days "
                    "FROM marts.fund_daily").df()
    d["date"] = pd.to_datetime(d.date)
    first = d.groupby(["fund_id", "plan"]).date.min()
    ends = pd.period_range(config.WINDOW_START, config.WINDOW_END, freq="M").to_timestamp(how="end").normalize()
    rows = []
    for (f, p), g in d.groupby(["fund_id", "plan"]):
        g = g.sort_values("date")
        for end in ends:
            for wname, months in WINDOWS.items():
                start = end - pd.DateOffset(months=months)
                x = g[(g.date > start) & (g.date <= end)]
                r = dict(fund_id=f, role=g.role.iloc[0], plan=p, month_end=end.date(), window=wname, n_obs=len(x))
                # full window only: the plan's first return must fall within a week of the window start
                if first[(f, p)] > start + pd.Timedelta(days=7) or len(x) < MIN_OBS[wname]:
                    r["status"] = "insufficient_history"
                    rows.append(r)
                    continue
                years = months / 12
                rf, rb = core.period_return(x.fund_ret), core.period_return(x.bench_ret)
                af, ab = core.annualise(rf, years), core.annualise(rb, years)
                te = core.tracking_error(x.excess_ret)
                one = x[x.n_tri_days == 1]
                r.update(status="ok", fund_return=rf, bench_return=rb, fund_return_ann=af, bench_return_ann=ab,
                         excess_ann=af - ab, tracking_error=te, info_ratio=core.information_ratio(af - ab, te),
                         te_one_day_only=core.tracking_error(one.excess_ret), n_multi_day=int((x.n_tri_days > 1).sum()))
                rows.append(r)
    return pd.DataFrame(rows)


# ---- fees --------------------------------------------------------------------------------------
def regular_aaum_lakh(con) -> pd.DataFrame:
    """Jan-Mar 2026 AAUM of every regular-plan code (Growth + IDCW) of each study fund, found by the fund's exact
    AMFI scheme name in the pinned NAVAll (D-046); codes with no AAUM row are counted and reported."""
    from src.ingest.amfi import navall_snapshot, parse_amfi_text
    a = parse_amfi_text(navall_snapshot().read_text(encoding="utf-8"), "navall")
    sm = con.execute("SELECT fund_id, regular_code FROM staging.scheme_map").df()
    names = a[["scheme_code", "scheme_name"]].merge(sm, left_on="scheme_code", right_on="regular_code")[["fund_id", "scheme_name"]]
    fam = a.merge(names, on="scheme_name")
    reg = fam[fam.plan.str.lower().str.startswith("regular", na=False) | fam.scheme_code.isin(sm.regular_code)]
    x = pd.read_excel(config.RAW / "aum" / "average-aum.xlsx", header=1)
    x = x[pd.to_numeric(x["AMFI Code"], errors="coerce").notna()].copy()
    x["code"] = x["AMFI Code"].astype(int)
    x["aaum_lakh"] = pd.to_numeric(x.iloc[:, 2], errors="coerce").fillna(0) + pd.to_numeric(x.iloc[:, 3], errors="coerce").fillna(0)
    m = reg.merge(x[["code", "aaum_lakh"]], left_on="scheme_code", right_on="code", how="left")
    return m.groupby("fund_id").agg(regular_aaum_lakh=("aaum_lakh", "sum"), regular_codes=("scheme_code", "nunique"),
                                    regular_codes_without_aaum=("aaum_lakh", lambda s: int(s.isna().sum()))).reset_index()


def fee_drag(con) -> pd.DataFrame:
    t = con.execute(f"""SELECT fund_id, plan, ter_date, total, total_ex_costs FROM intermediate.ter_daily
                       WHERE ter_date BETWEEN DATE '{config.WINDOW_START}' AND DATE '{config.WINDOW_END}'""").df()
    roles = con.execute("SELECT fund_id, role, report_group, eligible FROM staging.universe").df()
    days_in_window = (config.WINDOW_END - config.WINDOW_START).days + 1
    idx = t[t.fund_id.isin(INDEX_FUNDS)]
    comps = {
        "bandhan": idx[idx.fund_id == COMPARATOR].set_index(["plan", "ter_date"])[["total", "total_ex_costs"]],
        "cheapest": idx.groupby(["plan", "ter_date"])[["total", "total_ex_costs"]].min(),
        "average": idx.groupby(["plan", "ter_date"])[["total", "total_ex_costs"]].mean(),
    }
    active = roles[(roles.role == "active") & roles.eligible]
    rows = []
    for f in active.fund_id:
        out = dict(fund_id=f)
        for plan in ("regular", "direct"):
            x = t[(t.fund_id == f) & (t.plan == plan)].set_index(["plan", "ter_date"])[["total", "total_ex_costs"]]
            for cname, c in comps.items():
                if plan == "direct" and cname != "bandhan":
                    continue
                j = x.join(c, rsuffix="_cmp", how="inner")
                tag = f"{plan}_vs_{cname}"
                gap = j.total - j.total_cmp
                out[f"days_{tag}"] = len(j)
                out[f"gap_pp_{tag}"] = float(gap.mean()) if len(j) else np.nan
                out[f"rs_per_lakh_{tag}"] = core.fee_drag_per_lakh(gap) if len(j) else np.nan
                if plan == "regular" and cname == "bandhan":
                    g2 = j.total_ex_costs - j.total_ex_costs_cmp
                    out["gap_pp_regular_vs_bandhan_ex_costs"] = float(g2.mean())
                    out["fund_ter_regular_mean"] = float(j.total.mean())
                    out["comparator_ter_regular_mean"] = float(j.total_cmp.mean())
        out["days_in_window"] = days_in_window
        rows.append(out)
    fd = pd.DataFrame(rows).merge(active[["fund_id", "report_group"]], on="fund_id")
    aum = regular_aaum_lakh(con)
    fd = fd.merge(aum, on="fund_id", how="left")
    # annual run-rate at Q4 FY26 regular AAUM: gap (pp) / 100 x AAUM; Rs lakh -> Rs crore (/100)
    fd["annual_cost_rs_crore_at_q4fy26_aaum"] = fd.gap_pp_regular_vs_bandhan / 100 * fd.regular_aaum_lakh / 100
    return fd


# ---- assembly ---------------------------------------------------------------------------------
def fund_summary(asm: pd.DataFrame, tov: pd.DataFrame, rr: pd.DataFrame, fd: pd.DataFrame, con) -> pd.DataFrame:
    u = con.execute("SELECT fund_id, role, amc, scheme_name, eligible, report_group FROM staging.universe").df()
    u = u[(u.role == "active") & u.eligible]
    a = asm.groupby("fund_id").agg(months_with_holdings=("month", "nunique"),
                                   active_share_main_mean=("active_share_main", "mean"),
                                   active_share_main_min=("active_share_main", "min"),
                                   active_share_main_max=("active_share_main", "max"),
                                   active_share_equity_only_mean=("active_share_equity_only", "mean")).reset_index()
    last = asm.sort_values("month").groupby("fund_id").tail(1)[["fund_id", "active_share_main"]].rename(
        columns={"active_share_main": "active_share_main_latest"})
    t = tov.groupby("fund_id").agg(turnover_main_mean=("turnover_main", "mean")).reset_index()
    end = config.WINDOW_END
    r = rr[(rr.status == "ok") & (rr.plan == "direct") & (pd.to_datetime(rr.month_end) == pd.Timestamp(end))]
    r24 = r[r.window == "24m"][["fund_id", "excess_ann", "tracking_error", "info_ratio", "fund_return_ann", "bench_return_ann"]].add_suffix("_24m").rename(columns={"fund_id_24m": "fund_id"})
    r12 = r[r.window == "12m"][["fund_id", "excess_ann", "tracking_error", "info_ratio"]].add_suffix("_12m").rename(columns={"fund_id_12m": "fund_id"})
    f = fd[["fund_id", "fund_ter_regular_mean", "comparator_ter_regular_mean", "gap_pp_regular_vs_bandhan",
            "rs_per_lakh_regular_vs_bandhan", "regular_aaum_lakh", "annual_cost_rs_crore_at_q4fy26_aaum"]]
    s = u.merge(a, on="fund_id", how="left").merge(last, on="fund_id", how="left").merge(t, on="fund_id", how="left")
    return s.merge(r24, on="fund_id", how="left").merge(r12, on="fund_id", how="left").merge(f, on="fund_id", how="left")


def run(db: Path = DB, out: Path = OUT) -> dict[str, pd.DataFrame]:
    con = duckdb.connect(str(db), read_only=True)
    try:
        asm = active_share_monthly(con)
        tov = turnover_monthly(con)
        rr = returns_rolling(con)
        fd = fee_drag(con)
        fs = fund_summary(asm, tov, rr, fd, con)
    finally:
        con.close()
    out.mkdir(parents=True, exist_ok=True)
    res = dict(active_share_monthly=asm, turnover_monthly=tov, returns_rolling=rr, fee_drag=fd, fund_summary=fs)
    for k, v in res.items():
        v.to_csv(out / f"{k}.csv", index=False)
    print(f"metrics -> {out}: " + ", ".join(f"{k} {len(v)}" for k, v in res.items()))
    return res
