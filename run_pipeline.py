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

STEPS = ["universe", "nav", "benchmark", "portfolios", "quality", "checklist", "test"]


def step_universe(offline: bool) -> int:
    from src.ingest import amfi, universe
    if offline:
        navall = amfi.latest_navall()
        hist = config.RAW_AMFI / f"NAVHistory_{config.SURVIVORSHIP_SNAPSHOT_DATE.isoformat()}.txt"
        if not hist.exists():
            raise FileNotFoundError(f"{hist} missing; run once without --offline")
    else:
        navall = amfi.download_navall()
        hist = amfi.download_history_snapshot(config.SURVIVORSHIP_SNAPSHOT_DATE)
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


def step_quality(offline: bool) -> int:
    from src.quality import holdings_checks, nav_checks
    rc = nav_checks.run()
    if (config.INTERIM / "holdings.parquet").exists():
        rc = max(rc, holdings_checks.run())
    return rc


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
