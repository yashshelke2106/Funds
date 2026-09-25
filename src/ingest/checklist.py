"""Generate / refresh the manual-download tracker.

data/reference/download_checklist.csv has one row per (source, AMC, month) the
pipeline needs from you. `status` is recomputed from what is actually on disk,
so rerunning this after downloading shows what is still missing.

File-naming contract (the parsers in P2 rely on it):
  data/raw/portfolios/<amc_slug>/<YYYY-MM>__<original filename>
  data/raw/ter/<anything>.xlsx|.csv
  data/raw/benchmark/<anything>.csv
"""
from __future__ import annotations

import pandas as pd

from src import config
from src.ingest.universe import slugify


def months(start=config.HOLDINGS_START, end=config.WINDOW_END) -> list[str]:
    return [p.strftime("%Y-%m") for p in pd.period_range(start, end, freq="M")]


def build(universe: pd.DataFrame) -> pd.DataFrame:
    rows = []
    elig = universe[universe["eligible"]]
    amcs = sorted(set(elig["amc"]))
    for amc in amcs:
        slug = slugify(amc)
        funds = "; ".join(sorted(elig.loc[elig.amc == amc, "scheme_name"]))
        parsed = set()
        meta_path = config.INTERIM / "portfolio_meta.parquet"
        if meta_path.exists():
            pm = pd.read_parquet(meta_path)
            parsed = set(pm.loc[pm.amc_slug == slug, "month"])
        for m in months():
            present = m in parsed   # month read from INSIDE the file (D-018)
            rows.append(dict(source="portfolio", amc=amc, amc_slug=slug, month=m, schemes=funds,
                             expected_path=f"data/raw/portfolios/{slug}/<original filename>",
                             status="present" if present else "missing"))
    ter_present = config.RAW_TER.exists() and any(config.RAW_TER.iterdir())
    rows.append(dict(source="ter", amc="AMFI", amc_slug="amfi", month=f"{months()[0]}..{months()[-1]}",
                     schemes="all eligible direct+regular plans + index funds",
                     expected_path="data/raw/ter/", status="present" if ter_present else "missing"))
    bm_present = config.RAW_BENCHMARK.exists() and any(config.RAW_BENCHMARK.iterdir())
    rows.append(dict(source="benchmark_tri", amc="NSE Indices", amc_slug="nse", month=
                     f"{config.NAV_START:%Y-%m}..{months()[-1]}", schemes="Nifty 100 TRI (daily)",
                     expected_path="data/raw/benchmark/", status="present" if bm_present else "missing"))
    return pd.DataFrame(rows)


def run() -> None:
    uni = pd.read_csv(config.REFERENCE / "universe.csv")
    ck = build(uni)
    out = config.REFERENCE / "download_checklist.csv"
    ck.to_csv(out, index=False)
    s = ck.groupby(["source", "status"]).size().to_dict()
    print(f"checklist: {len(ck)} items {s} -> {out}")
