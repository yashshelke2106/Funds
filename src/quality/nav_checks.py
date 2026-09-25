"""NAV data-quality rules from the project brief.

Hard failures (pipeline exits non-zero):
  - non-positive NAV
  - duplicate (scheme_code, nav_date)
Logged flags (kept, reported, reviewed by a human):
  - gap of more than NAV_MAX_GAP_WEEKDAYS weekdays between consecutive NAVs
  - |daily return| > NAV_MAX_ABS_DAILY_MOVE

"Trading days" are approximated by weekdays (Mon-Fri). NSE holidays make some
weekday gaps legitimate, which is why gaps are flags, not failures (D-006).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src import config

ISSUE_COLS = ["scheme_code", "check", "severity", "nav_date", "prev_date", "value", "detail"]


def check_nav(nav: pd.DataFrame,
              max_gap_weekdays: int = config.NAV_MAX_GAP_WEEKDAYS,
              max_abs_move: float = config.NAV_MAX_ABS_DAILY_MOVE) -> pd.DataFrame:
    issues: list[dict] = []
    df = nav.copy()
    df["nav_date"] = pd.to_datetime(df["nav_date"])

    dup = df[df.duplicated(["scheme_code", "nav_date"], keep=False)]
    for _, r in dup.iterrows():
        issues.append(dict(scheme_code=r.scheme_code, check="duplicate_date", severity="fail",
                           nav_date=r.nav_date.date(), prev_date=None, value=r.nav,
                           detail="duplicate (scheme_code, nav_date)"))

    for _, r in df[df["nav"] <= 0].iterrows():
        issues.append(dict(scheme_code=r.scheme_code, check="non_positive_nav", severity="fail",
                           nav_date=r.nav_date.date(), prev_date=None, value=r.nav, detail="nav <= 0"))

    df = df.drop_duplicates(["scheme_code", "nav_date"]).sort_values(["scheme_code", "nav_date"])
    df["prev_date"] = df.groupby("scheme_code")["nav_date"].shift()
    df["prev_nav"] = df.groupby("scheme_code")["nav"].shift()
    has_prev = df["prev_date"].notna()
    x = df[has_prev].copy()
    # weekdays strictly between the two observations
    x["gap_weekdays"] = np.busday_count(
        (x["prev_date"] + pd.Timedelta(days=1)).values.astype("datetime64[D]"),
        x["nav_date"].values.astype("datetime64[D]"))
    for _, r in x[x["gap_weekdays"] > max_gap_weekdays].iterrows():
        issues.append(dict(scheme_code=r.scheme_code, check="gap_gt_5_weekdays", severity="flag",
                           nav_date=r.nav_date.date(), prev_date=r.prev_date.date(),
                           value=int(r.gap_weekdays), detail=f"{int(r.gap_weekdays)} weekdays missing"))

    x = x[x["prev_nav"] > 0]
    x["ret"] = x["nav"] / x["prev_nav"] - 1
    # round away float noise so exactly 10% is not flagged (110/100-1 = 0.10000000000000009)
    for _, r in x[x["ret"].abs().round(10) > max_abs_move].iterrows():
        issues.append(dict(scheme_code=r.scheme_code, check="abs_daily_move_gt_10pct", severity="flag",
                           nav_date=r.nav_date.date(), prev_date=r.prev_date.date(),
                           value=round(float(r.ret), 6), detail=f"{r.prev_nav} -> {r.nav}"))

    return pd.DataFrame(issues, columns=ISSUE_COLS)


def run() -> int:
    nav = pd.read_parquet(config.INTERIM / "nav.parquet")
    issues = check_nav(nav)
    out = config.QUALITY / "nav_issues.csv"
    issues.to_csv(out, index=False)
    n_fail = int((issues["severity"] == "fail").sum())
    summary = issues.groupby(["check", "severity"]).size().to_dict() if len(issues) else {}
    print(f"nav checks: {len(nav):,} rows, {nav.scheme_code.nunique()} schemes; issues={summary} -> {out}")
    return 1 if n_fail else 0
