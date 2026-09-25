"""Nifty 100 Total Returns Index (TRI) from niftyindices.com, plus benchmark-proxy selection.

Layout inspected 2026-09-25 (DECISIONS D-013, D-014):
  file name  NIFTY 100_Historical_TR_<ddmmyyyy>to<ddmmyyyy>.csv   (one year max per download)
  header     "IndexName","Date","Total Returns Index"
  dates      '30 Aug 2024' (%d %b %Y), newest first, CRLF line endings
The price-return download ("..._PR_...", columns Open/High/Low/Close) is rejected:
it excludes dividends and would understate the benchmark.

Outputs
  data/interim/benchmark_tri.parquet            date, tri
  data/quality/calendar_mismatch.csv            TRI days with no NAV / NAV days with no TRI
  data/reference/benchmark_proxy_selection.csv  index-fund tracking vs TRI; chooses the proxy (D-010)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src import config

TRI_HEADER = ["IndexName", "Date", "Total Returns Index"]
INDEX_NAME = "NIFTY 100"


class BenchmarkFormatError(RuntimeError):
    pass


def parse_tri_file(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    if list(df.columns) != TRI_HEADER:
        raise BenchmarkFormatError(
            f"{path.name}: header {list(df.columns)} != {TRI_HEADER}. "
            "If it shows Open/High/Low/Close this is the PRICE index, not the TRI.")
    names = set(df["IndexName"].str.strip())
    if names != {INDEX_NAME}:
        raise BenchmarkFormatError(f"{path.name}: IndexName values {names} != {{{INDEX_NAME!r}}}")
    out = pd.DataFrame({
        "date": pd.to_datetime(df["Date"].str.strip(), format="%d %b %Y").dt.date,
        "tri": pd.to_numeric(df["Total Returns Index"], errors="raise"),
    })
    out["source_file"] = path.name
    return out


def combine(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate yearly chunks. An overlapping date must carry the identical value."""
    df = pd.concat(frames, ignore_index=True)
    g = df.groupby("date")["tri"].nunique()
    conflict = g[g > 1]
    if len(conflict):
        raise BenchmarkFormatError(f"overlapping dates with different TRI values: "
                                   f"{[d.isoformat() for d in conflict.index[:10]]}")
    df = df.sort_values(["date", "source_file"]).drop_duplicates("date").reset_index(drop=True)
    if (df["tri"] <= 0).any():
        raise BenchmarkFormatError("non-positive TRI value")
    return df[["date", "tri"]]


def check_coverage(tri: pd.DataFrame, start=config.NAV_START, end=config.WINDOW_END,
                   max_gap_days: int = 7) -> None:
    """Must span [start, end] (first/last trading day within 5 days) with no calendar gap > 7 days."""
    d = pd.to_datetime(tri["date"])
    if (d.min() - pd.Timestamp(start)).days > 5 or (pd.Timestamp(end) - d.max()).days > 5:
        raise BenchmarkFormatError(f"TRI covers {d.min().date()}..{d.max().date()}, need {start}..{end}")
    gaps = d.diff().dt.days
    if gaps.max() > max_gap_days:
        at = d[gaps.idxmax()].date()
        raise BenchmarkFormatError(f"calendar gap of {int(gaps.max())} days ending {at}: missing download chunk?")


def calendar_mismatch(tri: pd.DataFrame, nav: pd.DataFrame, codes: list[int],
                      start=config.NAV_START, end=config.WINDOW_END) -> pd.DataFrame:
    t = set(pd.to_datetime(tri["date"]))
    rows = []
    for c in codes:
        n = pd.to_datetime(nav.loc[nav.scheme_code == c, "nav_date"])
        n = set(n[(n >= pd.Timestamp(start)) & (n <= pd.Timestamp(end))])
        rows += [dict(scheme_code=c, date=d.date(), kind="tri_day_without_nav") for d in sorted(t - n)]
        rows += [dict(scheme_code=c, date=d.date(), kind="nav_day_without_tri") for d in sorted(n - t)]
    return pd.DataFrame(rows, columns=["scheme_code", "date", "kind"])


def aligned_daily_returns(tri: pd.DataFrame, nav_one: pd.DataFrame) -> pd.DataFrame:
    """Daily returns on the TRI trading calendar (D-014).

    NAVs on non-TRI days are dropped; TRI days without a NAV are dropped from BOTH
    series, so the next return spans the gap identically in both. No forward fill.
    """
    b = pd.Series(tri["tri"].values, index=pd.to_datetime(tri["date"]), name="bench")
    f = pd.Series(nav_one["nav"].values, index=pd.to_datetime(nav_one["nav_date"]), name="fund")
    j = pd.concat([f, b], axis=1, join="inner").sort_index()
    r = j.pct_change().dropna()
    r.columns = ["fund_ret", "bench_ret"]
    return r


def proxy_selection(tri: pd.DataFrame, nav: pd.DataFrame, scheme_map: pd.DataFrame,
                    start=config.WINDOW_START, end=config.WINDOW_END) -> pd.DataFrame:
    """Rank Nifty 100 index funds (Direct plan) by tracking error vs the TRI over the window."""
    rows = []
    for _, f in scheme_map[scheme_map["role"] == "index"].iterrows():
        code = int(f["direct_code"])
        r = aligned_daily_returns(tri, nav[nav.scheme_code == code])
        r = r[(r.index >= pd.Timestamp(start)) & (r.index <= pd.Timestamp(end))]
        ex = r["fund_ret"] - r["bench_ret"]
        years = len(r) / 252
        tot_f = (1 + r["fund_ret"]).prod() - 1
        tot_b = (1 + r["bench_ret"]).prod() - 1
        rows.append(dict(
            fund_id=f["fund_id"], amc=f["amc"], direct_code=code, n_returns=len(r),
            tracking_error_ann=ex.std(ddof=1) * np.sqrt(252),
            fund_return_ann=(1 + tot_f) ** (1 / years) - 1,
            tri_return_ann=(1 + tot_b) ** (1 / years) - 1,
        ))
    out = pd.DataFrame(rows)
    out["tracking_difference_ann"] = out["fund_return_ann"] - out["tri_return_ann"]
    out = out.sort_values(["tracking_error_ann", "tracking_difference_ann"],
                          ascending=[True, False]).reset_index(drop=True)
    out["selected_as_weight_proxy"] = out.index == 0
    return out


def run() -> Path:
    files = sorted(config.RAW_BENCHMARK.glob("*.csv"))
    pr = [p.name for p in files if "_PR_" in p.name]
    if pr:
        raise BenchmarkFormatError(f"price-return files in data/raw/benchmark: {pr}. Move them out; TRI only.")
    if not files:
        raise FileNotFoundError("no TRI CSVs in data/raw/benchmark")
    tri = combine([parse_tri_file(p) for p in files])
    check_coverage(tri)
    out = config.INTERIM / "benchmark_tri.parquet"
    tri.to_parquet(out, index=False)
    print(f"TRI: {len(files)} files, {len(tri)} days {tri.date.min()}..{tri.date.max()} -> {out}")

    nav = pd.read_parquet(config.INTERIM / "nav.parquet")
    sm = pd.read_csv(config.REFERENCE / "scheme_map.csv")
    codes = sorted(set(sm.direct_code) | set(sm.regular_code))
    mm = calendar_mismatch(tri, nav, codes)
    mm.to_csv(config.QUALITY / "calendar_mismatch.csv", index=False)
    common = (mm[mm.kind == "tri_day_without_nav"].groupby("date").scheme_code.nunique() == len(codes))
    print(f"calendar: TRI days missing NAV for ALL schemes: {int(common.sum())}; "
          f"per-scheme extra NAV days: {int((mm.kind == 'nav_day_without_tri').sum())} -> data/quality/calendar_mismatch.csv")

    sel = proxy_selection(tri, nav, sm)
    sel.to_csv(config.REFERENCE / "benchmark_proxy_selection.csv", index=False)
    with pd.option_context("display.width", 200, "display.float_format", "{:.5f}".format):
        print(sel[["fund_id", "n_returns", "tracking_error_ann", "tracking_difference_ann",
                   "selected_as_weight_proxy"]].to_string(index=False))
    return out
