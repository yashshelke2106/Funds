"""AMFI TER exports -> daily TER per fund (DECISIONS D-023, D-024).

Source: https://www.amfiindia.com/ter-of-mf-schemes  ('Download Excel', sheet 'TER_Revised').
Two layouts were inspected on 2026-09-25 and both are accepted; anything else stops the run.
  OLD (seen Mar-2026): <plan> - Base TER | Additional expense 52(6A)(b) | 52(6A)(c) | GST | Total TER
  NEW (seen Jul/Aug-2026, SEBI (MF) Regulations 2026): <plan> - Base Expense Ratio (BER) |
      Brokerage cost | Transaction Cost ... | Statutory Levies (including GST) | Total TER
Every export ends with a ~13-row 'Disclaimer' footer (no Scheme Category) which is dropped.
Schemes are keyed on the NSDL scheme code with ALL whitespace removed ('MAHM/O/E /LCF/..').
Names vary inside one code ('Invesco India Large cap Fund' / 'Largecap Fund'), so the
code -> fund_id map is built from names once and written to data/reference/ter_scheme_map.csv.

Outputs
  data/interim/ter_daily.parquet   fund_id, plan, ter_date, total_ter, components, format, filled
  data/quality/ter_coverage.csv    fund_id x month: days observed / filled / missing
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from src import config

ID_COLS = ["NSDL Scheme Code", "Scheme Name", "Scheme Type", "Scheme Category", "TER Date"]
OLD = {"base": "Base TER (%)", "addl_b": "Additional expense as per Regulation 52(6A)(b) (%)",
       "addl_c": "Additional expense as per Regulation 52(6A)(c) (%)", "levies": "GST (%)",
       "total": "Total TER (%)"}
NEW = {"base": "Base Expense Ratio (BER) (%)", "brokerage": "Brokerage cost (%)",
       "txn": "Transaction Cost incurred for the purpose of execution of trade (%)",
       "levies": "Statutory Levies (including GST) (%)", "total": "Total TER (%)"}
PLANS = {"regular": "Regular Plan - ", "direct": "Direct Plan - "}
COMPONENTS = ["base", "addl_b", "addl_c", "brokerage", "txn", "levies", "total"]
MAX_FILL_DAYS = 3


class TerFormatError(RuntimeError):
    pass


def detect_format(columns) -> str:
    cols = list(columns)
    if cols[:5] != ID_COLS:
        raise TerFormatError(f"unexpected id columns {cols[:5]}")
    for name, spec in (("new", NEW), ("old", OLD)):
        want = [p + c for p in PLANS.values() for c in spec.values()]
        if all(w in cols for w in want):
            return name
    raise TerFormatError(f"TER layout not recognised: {cols[5:]}")


def parse_ter_file(path: Path) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name=0)
    fmt = detect_format(raw.columns)
    body = raw[raw["Scheme Category"].notna()].copy()
    footer = raw[raw["Scheme Category"].isna()]
    if len(footer) and not footer["NSDL Scheme Code"].astype(str).str.contains("Disclaimer", case=False).any():
        raise TerFormatError(f"{path.name}: rows without category that are not the disclaimer footer")
    spec = NEW if fmt == "new" else OLD
    out = []
    for plan, prefix in PLANS.items():
        d = pd.DataFrame({
            "nsdl_code": body["NSDL Scheme Code"].astype(str).str.replace(r"\s+", "", regex=True),
            "scheme_name": body["Scheme Name"].astype(str).str.strip(),
            "category": body["Scheme Category"].astype(str).str.strip(),
            "ter_date": pd.to_datetime(body["TER Date"]).dt.date,
            "plan": plan,
        })
        for comp in COMPONENTS:
            d[comp] = pd.to_numeric(body[prefix + spec[comp]], errors="coerce") if comp in spec else float("nan")
        out.append(d)
    df = pd.concat(out, ignore_index=True)
    df["format"] = fmt
    df["source_file"] = path.name
    # a plan the scheme doesn't offer shows up as an all-empty row: drop it, don't invent a zero
    df = df[df["total"].notna()].reset_index(drop=True)
    comp_cols = [c for c in spec if c != "total"]
    gap = (df[comp_cols].sum(axis=1) - df["total"]).abs()
    if (gap > 0.011).any():
        bad = df[gap > 0.011].iloc[0]
        raise TerFormatError(f"{path.name}: components do not add to Total TER for {bad.scheme_name} {bad.ter_date}")
    return df


def combine(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Same (code, plan, date) may come from several downloads; values must agree exactly."""
    df = pd.concat(frames, ignore_index=True)
    key = ["nsdl_code", "plan", "ter_date"]
    n = df.groupby(key)["total"].nunique()
    if (n > 1).any():
        k = n[n > 1].index[0]
        raise TerFormatError(f"conflicting Total TER across files for {k}")
    return df.sort_values(key + ["source_file"]).drop_duplicates(key).reset_index(drop=True)


def norm_name(s: str) -> str:
    s = re.sub(r"\(.*?\)", " ", str(s).lower()).replace("largecap", "large cap")
    s = re.sub(r"\bmf\b", " ", s)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def map_codes(ter: pd.DataFrame, scheme_map: pd.DataFrame) -> pd.DataFrame:
    want = {norm_name(n): f for n, f in zip(scheme_map.scheme_name, scheme_map.fund_id)}
    names = ter.groupby("nsdl_code")["scheme_name"].unique()
    rows = []
    for code, ns in names.items():
        hits = {want[norm_name(n)] for n in ns if norm_name(n) in want}
        if len(hits) > 1:
            raise TerFormatError(f"{code} matches several funds: {hits}")
        if hits:
            rows.append(dict(nsdl_code=code, fund_id=hits.pop(), names=" | ".join(sorted(ns))))
    m = pd.DataFrame(rows, columns=["nsdl_code", "fund_id", "names"])
    dup = m[m.fund_id.duplicated(keep=False)]
    if len(dup):
        raise TerFormatError(f"fund mapped from several NSDL codes: {dup.values.tolist()}")
    return m


def fill_daily(ter_f: pd.DataFrame, max_gap: int = MAX_FILL_DAYS) -> pd.DataFrame:
    """Calendar-daily per (fund, plan); forward-fill gaps of <= max_gap days only (D-024)."""
    out = []
    for (fund, plan), g in ter_f.groupby(["fund_id", "plan"]):
        g = g.set_index(pd.to_datetime(g["ter_date"])).sort_index()
        full = pd.date_range(g.index.min(), g.index.max(), freq="D")
        r = g.reindex(full)
        r["filled"] = r["total"].isna()
        run = r["filled"].ne(r["filled"].shift()).cumsum()
        run_len = r.groupby(run)["filled"].transform("size")
        fillable = r["filled"] & (run_len <= max_gap)
        ffilled = r.ffill()
        cols = [c for c in r.columns if c not in ("filled",)]
        r.loc[fillable, cols] = ffilled.loc[fillable, cols]
        r = r[r["total"].notna()].copy()
        r["fund_id"], r["plan"] = fund, plan
        r["ter_date"] = r.index.date
        out.append(r.reset_index(drop=True))
    return pd.concat(out, ignore_index=True) if out else ter_f.assign(filled=False)


def coverage(daily: pd.DataFrame, funds: list[str], start=config.WINDOW_START, end=config.WINDOW_END) -> pd.DataFrame:
    months = pd.period_range(start, end, freq="M")
    d = daily.copy()
    d["month"] = pd.to_datetime(d["ter_date"]).dt.to_period("M")
    rows = []
    for f in funds:
        for plan in PLANS:
            x = d[(d.fund_id == f) & (d.plan == plan)]
            for m in months:
                y = x[x.month == m]
                n_obs, n_fill = int((~y.filled.astype(bool)).sum()), int(y.filled.astype(bool).sum())
                days = m.days_in_month
                status = "complete" if n_obs + n_fill == days else ("missing" if n_obs == 0 else "partial")
                rows.append(dict(fund_id=f, plan=plan, month=str(m), days_in_month=days, observed=n_obs,
                                 filled=n_fill, status=status))
    return pd.DataFrame(rows)


def run() -> Path:
    """TER step. Source = AMFI TER API pages (D-049..D-052); the Excel exports are kept for two jobs:
    the NSDL code map (ter_scheme_map.csv) and an exact cross-check against the API on every
    (fund, plan, day) both sources hold. Any disagreement stops the build."""
    import json
    from src.ingest import ter_api, ter_api_parse
    files = sorted(p for p in config.RAW_TER.rglob("*.xlsx") if not p.name.startswith("~$"))
    if not files:
        raise FileNotFoundError("no TER Excel exports in data/raw/ter (needed for the code map and the cross-check)")
    ter = combine([parse_ter_file(p) for p in files])
    sm = pd.read_csv(config.REFERENCE / "scheme_map.csv")
    uni = pd.read_csv(config.REFERENCE / "universe.csv")
    cmap = map_codes(ter, sm)
    cmap.to_csv(config.REFERENCE / "ter_scheme_map.csv", index=False)
    excel = ter.merge(cmap[["nsdl_code", "fund_id"]], on="nsdl_code", how="inner")

    mf_path = config.RAW_TER_API / "populate-mf.json"
    if not mf_path.exists():
        raise FileNotFoundError(f"{mf_path} missing - run `python -m src.ingest.ter_api fetch`")
    mf_ids = ter_api.resolve_amcs(sm.amc, json.loads(mf_path.read_text(encoding="utf-8")))
    months = ter_api.window_months()
    exc = ter_api_parse.load_code_exceptions(config.REFERENCE / "ter_api_code_exceptions.csv")
    api = ter_api_parse.build(config.RAW_TER_API, sm, uni, cmap, mf_ids, months, exc)
    eq = ter_api_parse.compare_with_excel(api, excel)

    daily = fill_daily(api.assign(source="api"))
    out = config.INTERIM / "ter_daily.parquet"
    daily.drop(columns=[c for c in ("month",) if c in daily], errors="ignore").to_parquet(out, index=False)
    funds = sorted(set(uni.loc[uni.eligible.astype(bool), "fund_id"]))
    cov = coverage(daily, funds)
    cov.to_csv(config.QUALITY / "ter_coverage.csv", index=False)
    names = (api.assign(month=pd.to_datetime(api.ter_date).dt.strftime("%Y-%m"))
             .groupby(["fund_id", "scheme_name"]).month.agg(["min", "max"]).reset_index())
    names.to_csv(config.QUALITY / "ter_api_scheme_names.csv", index=False)  # renames made visible (D-050)
    renamed = names.fund_id.value_counts().loc[lambda v: v > 1]
    s = cov.groupby("status").size().to_dict()
    print(f"TER (API): {len(api):,} fund-plan-day rows, {api.fund_id.nunique()} funds, {months[0]}..{months[-1]}, "
          f"formats={api.format.value_counts().to_dict()} -> {out}")
    print(f"  Excel cross-check: {eq['rows_compared']:,} rows, {eq['funds']} funds, months {eq['months']}: identical")
    print(f"  funds whose scheme name changed in the window: {len(renamed)} "
          f"(detail: data/quality/ter_api_scheme_names.csv)")
    print(f"TER coverage (eligible funds x plan x month, {config.WINDOW_START:%Y-%m}..{config.WINDOW_END:%Y-%m}): {s}")
    return out
