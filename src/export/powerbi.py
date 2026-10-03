"""P6: export a star schema for Power BI (DECISIONS D-058) to data/powerbi/*.csv.

Dimensions: dim_fund (one row per fund, all 38), dim_date (calendar, Indian FY), dim_class.
Facts:      fact_fund_month (holdings months), fact_rolling (month-end windows), fact_daily (returns + growth of 100),
            fact_ter_daily (fund vs comparator TER), fact_variant (fund x robustness variant -> class).
Other:      sensitivity, passive_floor, build_info.
Every table is validated before writing (unique keys, every fund/date in a fact exists in its dimension); any
violation stops the export. Growth-of-100 lines are computed here (tested) so the dashboard needs no cumulative DAX.
CSV: UTF-8, comma, ISO dates (yyyy-mm-dd), '.' decimals, booleans as TRUE/FALSE text.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from src import config

OUT = config.DATA / "powerbi"
DB = config.DATA / "warehouse.duckdb"
CLASSES = [("truly_active", 1, "Truly active", "Active share >= 0.40"),
           ("closet", 2, "Closet indexer", "Active share < 0.40; beat the index after regular-plan fees (24m)"),
           ("closet_underperforming", 3, "Closet + underperforming", "Active share < 0.40; trailed the index after regular-plan fees (24m)"),
           ("not_classified", 4, "Not classified", "No holdings in scope (D-032): returns and fees only"),
           ("index_fund", 5, "Index fund", "Nifty 100 index fund (benchmark proxy / fee comparator)"),
           ("excluded", 6, "Excluded", "NAV history shorter than the window (D-012): not analysed")]

KEYS = {"dim_fund": ["fund_id"], "dim_date": ["date"], "dim_class": ["class_main"], "dim_plan": ["plan"],
        "fact_fund_month": ["fund_id", "month_start"], "fact_rolling": ["fund_id", "plan", "window", "month_end"],
        "fact_daily": ["fund_id", "plan", "date"], "fact_ter_daily": ["fund_id", "plan", "date"],
        "fact_variant": ["fund_id", "threshold", "active_share_version", "underperformance"],
        "sensitivity": ["threshold", "active_share", "underperformance"], "passive_floor": ["month_start"]}
FUND_FACTS = ("fact_fund_month", "fact_rolling", "fact_daily", "fact_ter_daily", "fact_variant")
DATE_COLS = {"fact_fund_month": "month_start", "fact_rolling": "month_end", "fact_daily": "date",
             "fact_ter_daily": "date", "passive_floor": "month_start"}


class ExportError(RuntimeError):
    pass


def fund_label(name: str) -> str:
    """Readable display name: drop bracketed notes ('(erstwhile Bluechip Fund)'); title-case only names written
    entirely in capitals, so acronyms in mixed-case names (HDFC, SBI, UTI, ICICI) are left alone."""
    import re
    n = re.sub(r"\s+", " ", re.sub(r"\s*\(.*?\)\s*", " ", str(name))).strip()
    if not n.isupper():
        return n
    acronyms = {"BNP", "LIC", "ITI", "HSBC", "PGIM", "SBI", "UTI", "DSP", "HDFC", "ICICI", "JM", "NIFTY"}
    return " ".join(w if w in acronyms else w.title() for w in n.split())


def date_dim(start, end) -> pd.DataFrame:
    d = pd.DataFrame({"date": pd.date_range(start, end, freq="D")})
    d["year"] = d.date.dt.year
    d["month_start"] = d.date.dt.to_period("M").dt.to_timestamp()
    d["month_label"] = d.date.dt.strftime("%b-%Y")
    d["month_sort"] = d.date.dt.year * 100 + d.date.dt.month
    d["is_month_end"] = d.date.dt.is_month_end
    fy = np.where(d.date.dt.month >= 4, d.date.dt.year + 1, d.date.dt.year)   # Indian FY: Apr-Mar, named by end year
    d["fiscal_year"] = [f"FY{str(y)[2:]}" for y in fy]
    d["in_window"] = d.date.between(pd.Timestamp(config.WINDOW_START), pd.Timestamp(config.WINDOW_END))
    d["in_holdings_window"] = d.date.between(pd.Timestamp(config.HOLDINGS_START), pd.Timestamp(config.WINDOW_END))
    return d


def growth_of_100(daily: pd.DataFrame, start, end) -> pd.DataFrame:
    """Rebase fund and benchmark to 100 at the window start: value_t = 100 x prod(1 + r) over returns dated in
    (start, t]. Rows outside the window get NaN. Expects columns fund_id, plan, date, fund_ret, bench_ret."""
    d = daily.sort_values(["fund_id", "plan", "date"]).copy()
    inw = (d.date > pd.Timestamp(start)) & (d.date <= pd.Timestamp(end))
    d["fund_growth_100"] = np.nan; d["bench_growth_100"] = np.nan
    for col, r in (("fund_growth_100", "fund_ret"), ("bench_growth_100", "bench_ret")):
        g = (1 + d[r].where(inw, 0.0)).groupby([d.fund_id, d.plan]).cumprod() * 100
        d.loc[inw, col] = g[inw]
    return d


def variants_long(cls: pd.DataFrame) -> pd.DataFrame:
    """class__<threshold>__<as_version>__<measure> columns -> one row per fund x variant."""
    cols = [c for c in cls.columns if c.startswith("class__")]
    v = cls[["fund_id"] + cols].melt(id_vars="fund_id", var_name="variant", value_name="class_variant")
    parts = v.variant.str.split("__", expand=True)
    v["threshold"] = parts[1].astype(float); v["active_share_version"] = parts[2]; v["underperformance"] = parts[3]
    main = cls.set_index("fund_id").class_main
    v["agrees_with_main"] = v.class_variant.values == main.reindex(v.fund_id).values
    return v.drop(columns="variant")


def validate(tables: dict[str, pd.DataFrame]) -> None:
    errs = []
    for t, keys in KEYS.items():
        if t not in tables:
            errs.append(f"{t}: missing"); continue
        dup = tables[t].duplicated(keys).sum()
        if dup:
            errs.append(f"{t}: {dup} duplicate key rows on {keys}")
    funds = set(tables["dim_fund"].fund_id)
    for t in FUND_FACTS:
        bad = set(tables[t].fund_id) - funds
        if bad:
            errs.append(f"{t}: fund_id not in dim_fund: {sorted(bad)[:5]}")
    dates = set(pd.to_datetime(tables["dim_date"].date))
    for t, c in DATE_COLS.items():
        bad = set(pd.to_datetime(tables[t][c])) - dates
        if bad:
            errs.append(f"{t}.{c}: {len(bad)} date(s) not in dim_date, e.g. {min(bad).date()}")
    plans = set(tables["dim_plan"].plan)
    for t in ("fact_rolling", "fact_daily", "fact_ter_daily"):
        bad = set(tables[t].plan) - plans
        if bad:
            errs.append(f"{t}.plan not in dim_plan: {sorted(bad)}")
    bad = set(tables["dim_fund"].class_main) - set(tables["dim_class"].class_main)
    if bad:
        errs.append(f"dim_fund.class_main not in dim_class: {sorted(bad)}")
    if errs:
        raise ExportError("Power BI export failed validation:\n  " + "\n  ".join(errs))


def build_tables(db: Path = DB, metrics_dir: Path = config.DATA / "metrics",
                 analysis_dir: Path = config.DATA / "analysis") -> dict[str, pd.DataFrame]:
    con = duckdb.connect(str(db), read_only=True)
    try:
        u = con.execute("SELECT fund_id, role, amc, scheme_name, eligible, report_group, exclusion_reason "
                        "FROM staging.universe").df()
        daily = con.execute("SELECT fund_id, plan, date, fund_ret, bench_ret, excess_ret, ter_total, n_tri_days "
                            "FROM marts.fund_daily").df()
        ter = con.execute(f"""SELECT fund_id, plan, ter_date AS date, total AS ter_fund, total_ex_costs, format, filled
                              FROM intermediate.ter_daily
                              WHERE ter_date BETWEEN DATE '{config.WINDOW_START}' AND DATE '{config.WINDOW_END}'""").df()
    finally:
        con.close()
    cls = pd.read_csv(analysis_dir / "fund_classification.csv")
    dec = pd.read_csv(analysis_dir / "monthly_decomposition.csv")
    sens = pd.read_csv(analysis_dir / "threshold_sensitivity.csv")
    pref = pd.read_csv(analysis_dir / "passive_reference.csv")
    asm = pd.read_csv(metrics_dir / "active_share_monthly.csv")
    tov = pd.read_csv(metrics_dir / "turnover_monthly.csv")
    rr = pd.read_csv(metrics_dir / "returns_rolling.csv")
    fd = pd.read_csv(metrics_dir / "fee_drag.csv")

    keep = [c for c in cls.columns if not c.startswith("class__")]
    f = u.merge(cls[keep].drop(columns=["report_group"]), on="fund_id", how="left")
    f["class_main"] = np.where(f.role == "index", "index_fund",
                      np.where(~f.eligible.astype(str).str.lower().eq("true"), "excluded", f.class_main.fillna("not_classified")))
    f["has_holdings"] = f.active_share_main_mean.notna()
    f = f.merge(fd[["fund_id", "regular_aaum_lakh", "fund_ter_regular_mean", "comparator_ter_regular_mean"]],
                on="fund_id", how="left")
    f["regular_aaum_crore"] = f.regular_aaum_lakh / 100
    f["fund_label"] = [fund_label(n) for n in f.scheme_name]

    dd = date_dim(config.NAV_START, config.WINDOW_END)
    dcl = pd.DataFrame(CLASSES, columns=["class_main", "class_sort", "class_label", "class_description"])

    fm = (asm[["fund_id", "month", "available_from", "active_share_main", "active_share_equity_only", "n_holdings_main",
               "dropped_main", "option_net", "no_isin_weight"]]
          .merge(dec[["fund_id", "month", "within_part", "out_part", "out_of_index_weight"]], on=["fund_id", "month"], how="left")
          .merge(tov, on=["fund_id", "month"], how="left"))
    fm["month_start"] = pd.to_datetime(fm.month + "-01"); fm = fm.drop(columns="month")
    fm = fm[fm.fund_id.isin(f.fund_id)]

    roll = rr.copy(); roll["month_end"] = pd.to_datetime(roll.month_end)
    daily["date"] = pd.to_datetime(daily.date)
    daily = growth_of_100(daily, config.WINDOW_START, config.WINDOW_END)

    ter["date"] = pd.to_datetime(ter.date)
    cmp_ = ter[ter.fund_id == "bandhan_n100"][["plan", "date", "ter_fund"]].rename(columns={"ter_fund": "ter_comparator"})
    ter = ter.merge(cmp_, on=["plan", "date"], how="left")
    ter["ter_gap_pp"] = ter.ter_fund - ter.ter_comparator

    pf = pref.copy(); pf["month_start"] = pd.to_datetime(pf.month + "-01"); pf = pf.drop(columns="month")
    info = pd.DataFrame([dict(window_start=config.WINDOW_START, window_end=config.WINDOW_END,
                              holdings_start=config.HOLDINGS_START, navall_snapshot=config.NAVALL_SNAPSHOT_DATE,
                              threshold_main=float(cls.threshold_main.iloc[0]),
                              generated_at=pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"))])
    dpl = pd.DataFrame({"plan": ["regular", "direct"], "plan_label": ["Regular plan", "Direct plan"], "plan_sort": [1, 2]})
    return dict(dim_fund=f, dim_date=dd, dim_class=dcl, dim_plan=dpl, fact_fund_month=fm, fact_rolling=roll, fact_daily=daily,
                fact_ter_daily=ter, fact_variant=variants_long(cls), sensitivity=sens, passive_floor=pf,
                build_info=info)


def run(out: Path = OUT, **kw) -> dict[str, pd.DataFrame]:
    tables = build_tables(**kw)
    validate(tables)
    out.mkdir(parents=True, exist_ok=True)
    for name, t in tables.items():
        t = t.copy()
        for c in t.columns:
            if pd.api.types.is_datetime64_any_dtype(t[c]):
                t[c] = t[c].dt.strftime("%Y-%m-%d")
            elif t[c].dtype == bool:
                t[c] = t[c].map({True: "TRUE", False: "FALSE"})
        t.to_csv(out / f"{name}.csv", index=False, encoding="utf-8")
    print(f"powerbi export -> {out}: " + ", ".join(f"{k} {len(v):,}" for k, v in tables.items()))
    return tables
