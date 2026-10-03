"""One command to rebuild everything:  python run_pipeline.py

Steps run in order; pass step names to run a subset, e.g.
  python run_pipeline.py universe nav
  python run_pipeline.py --offline          # reuse cached raw files, no network
Later phases append steps (ingest, warehouse, metrics, analysis).
"""
from __future__ import annotations

import argparse
import subprocess
import sys

from src import config

STEPS = ["universe", "nav", "benchmark", "portfolios", "ter", "quality", "warehouse", "metrics", "analysis", "export", "checklist", "test"]


def step_universe(offline: bool) -> int:
    from src.ingest import amfi, universe
    if offline:
        navall = amfi.navall_snapshot()
        hist = config.RAW_AMFI / f"NAVHistory_{config.SURVIVORSHIP_SNAPSHOT_DATE.isoformat()}.txt"
        if not hist.exists():
            raise FileNotFoundError(f"{hist} missing; run once without --offline")
    else:
        fresh = amfi.download_navall()  # archived only; the build uses the pinned snapshot (D-046)
        hist = amfi.download_history_snapshot(config.SURVIVORSHIP_SNAPSHOT_DATE)
        navall = amfi.navall_snapshot()
        if fresh != navall:
            print(f"downloaded {fresh.name}; build still uses pinned {navall.name} (D-046)")
    universe.run(navall, hist)
    return 0


def step_nav(offline: bool) -> int:
    from src.ingest import nav
    nav.run(refresh=False)  # cached JSON is reused; delete data/raw/nav/*.json to refetch
    return 0


def step_benchmark(offline: bool) -> int:
    from src.ingest import benchmark
    benchmark.run()
    return 0


def step_portfolios(offline: bool) -> int:
    from src.ingest import portfolios
    portfolios.run()
    return 0


def step_ter(offline: bool) -> int:
    from src.ingest import ter, ter_api
    if not offline:
        rc = ter_api.fetch_window()  # resumable; with every page cached it makes no network calls
        if rc:
            return rc
    ter.run()
    return 0


def step_quality(offline: bool) -> int:
    from src.quality import holdings_checks, nav_checks, nav_crosscheck
    rc = nav_checks.run()
    rc = max(rc, nav_crosscheck.run())
    if (config.INTERIM / "holdings.parquet").exists():
        rc = max(rc, holdings_checks.run())
    return rc


def step_warehouse(offline: bool) -> int:
    from src.warehouse import build
    try:
        build.run()
    except build.WarehouseTestError as e:
        print(e)
        return 1
    return 0


def step_metrics(offline: bool) -> int:
    import pandas as pd
    from src.metrics import compute
    res = compute.run()
    s = res["fund_summary"].sort_values("active_share_main_mean")
    cols = {"fund_id": "fund", "report_group": "group", "active_share_main_mean": "AS_main",
            "active_share_equity_only_mean": "AS_eq", "turnover_main_mean": "turnover", "tracking_error_24m": "TE_24m",
            "excess_ann_24m": "excess_24m", "info_ratio_24m": "IR_24m", "gap_pp_regular_vs_bandhan": "fee_gap_pp",
            "rs_per_lakh_regular_vs_bandhan": "rs_per_lakh_2y", "annual_cost_rs_crore_at_q4fy26_aaum": "rs_cr_per_yr"}
    with pd.option_context("display.width", 220, "display.max_columns", 20, "display.float_format", "{:.4f}".format):
        print(s[list(cols)].rename(columns=cols).to_string(index=False))
    return 0


def step_analysis(offline: bool) -> int:
    import pandas as pd
    from src.analysis import run as analysis
    res = analysis.run()
    pref, c, sens = res["passive_reference"], res["fund_classification"], res["threshold_sensitivity"]
    print(f"analysis -> {analysis.OUT}")
    print(f"passive floors (12-month mean active share vs Nifty 100 proxy): Nifty 50 ETF {pref.nifty50_etf_as.mean():.4f} "
          f"(range {pref.nifty50_etf_as.min():.4f}-{pref.nifty50_etf_as.max():.4f}); 80% index + 20% outside "
          f"{pref.index_plus_sleeve_as.mean():.4f}")
    print(f"threshold {c.threshold_main.iloc[0]:.2f} (D-057); classification identical for any threshold in "
          f"({c.stable_band_low.iloc[0]:.4f}, {c.stable_band_high.iloc[0]:.4f}]")
    cols = {"fund_id": "fund", "active_share_main_mean": "AS", "within_part_mean": "AS_within", "out_of_index_weight_mean": "out_w",
            "tracking_error_24m": "TE", "excess_direct_24m": "xs_dir", "excess_regular_24m": "xs_reg",
            "alpha_ann_regular_24m": "alpha_reg", "beta_regular_24m": "beta_reg", "neg_share_12m_regular": "neg12",
            "gap_pp_regular_vs_bandhan": "fee_pp", "annual_cost_rs_crore_at_q4fy26_aaum": "rs_cr_yr", "class_main": "class",
            "agreement_at_main_threshold": "agree@0.40", "main_label_agreement": "agree_all"}
    with pd.option_context("display.width", 250, "display.max_columns", 30, "display.float_format", "{:.4f}".format):
        print(c.sort_values("active_share_main_mean")[list(cols)].rename(columns=cols).to_string(index=False))
        print(f"agree@0.40 = variants at the main threshold (of {c.n_variants_at_main_threshold.iloc[0]}) giving the main label; "
              f"agree_all = same across all {c.n_variants.iloc[0]} variants (thresholds 0.40/0.50/0.60)")
        m = sens[sens.active_share == "active_share_main_mean"]
        print("\nthreshold sensitivity (main active share):")
        print(m.drop(columns=["active_share"]).to_string(index=False))
    print("\nby class (main specification):")
    with pd.option_context("display.width", 250, "display.max_columns", 30, "display.float_format", "{:.4f}".format):
        print(res["class_summary"].drop(columns=["fund_ids"]).to_string(index=False))
    print("\nsurvivorship:", dict(zip(res["survivorship"].event, res["survivorship"].scheme_codes)))
    return 0


def step_export(offline: bool) -> int:
    from src.export import powerbi
    try:
        powerbi.run()
    except powerbi.ExportError as e:
        print(e)
        return 1
    return 0


def step_checklist(offline: bool) -> int:
    from src.ingest import checklist
    checklist.run()
    return 0


def step_test(offline: bool) -> int:
    return subprocess.call([sys.executable, "-m", "pytest", "-q"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("steps", nargs="*", default=[], help=f"subset of {STEPS}")
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    bad = [s for s in a.steps if s not in STEPS]
    if bad:
        ap.error(f"unknown step(s) {bad}; choose from {STEPS}")
    config.ensure_dirs()
    todo = a.steps or STEPS
    for s in STEPS:
        if s not in todo:
            continue
        print(f"\n=== {s} ===")
        rc = globals()[f"step_{s}"](a.offline)
        if rc:
            print(f"step '{s}' failed (exit {rc}); stopping.")
            return rc
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
