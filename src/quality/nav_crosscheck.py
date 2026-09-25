"""Cross-source NAV checks (project P1/P2 promise; DECISIONS D-029).

1. mfapi vs AMFI: every study scheme's mfapi NAV must equal AMFI's official NAV on the two
   AMFI snapshots we hold (NAVAll = latest date; NAV history report = 02-Sep-2024).
   AMFI prints 4 decimals (some schemes 2-3), mfapi up to 5, so the tolerance is half a unit
   in the 4th decimal plus float noise.
2. Direct vs Regular: for every fund, the Direct plan's return over the NAV window must be
   >= the Regular plan's (same portfolio, lower expenses). A failure means the plan codes
   are swapped or wrong -- the check that confirms D-022's name-based plan resolution.
fail: any NAV mismatch, missing NAV on a snapshot date for a scheme that should have one,
      or Direct return < Regular return.
"""
from __future__ import annotations

import pandas as pd

from src import config
from src.ingest.amfi import latest_navall, parse_amfi_text

NAV_TOL = 0.00051
COLS = ["check", "severity", "fund_id", "scheme_code", "date", "value", "detail"]


def nav_vs_amfi(nav: pd.DataFrame, amfi: pd.DataFrame, codes: set[int], label: str) -> list[dict]:
    rows = []
    a = amfi[amfi.scheme_code.isin(codes) & amfi.nav.notna()]
    n = nav.set_index(["scheme_code", "nav_date"])["nav"]
    for r in a.itertuples():
        key = (r.scheme_code, r.nav_date)
        if key not in n.index:
            rows.append(dict(check=f"mfapi_missing_on_{label}", severity="fail", fund_id=None,
                             scheme_code=r.scheme_code, date=r.nav_date, value=r.nav, detail="AMFI has a NAV, mfapi does not"))
            continue
        diff = float(n[key]) - float(r.nav)
        if abs(diff) > NAV_TOL:
            rows.append(dict(check=f"mfapi_vs_amfi_{label}", severity="fail", fund_id=None, scheme_code=r.scheme_code,
                             date=r.nav_date, value=diff, detail=f"mfapi={float(n[key])} amfi={r.nav}"))
    return rows


def direct_vs_regular(nav: pd.DataFrame, scheme_map: pd.DataFrame, start=config.WINDOW_START,
                      end=config.WINDOW_END) -> tuple[list[dict], pd.DataFrame]:
    rows, summ = [], []
    nv = nav.copy()
    nv["nav_date"] = pd.to_datetime(nv["nav_date"])
    for f in scheme_map.itertuples():
        d = nv[nv.scheme_code == f.direct_code].set_index("nav_date")["nav"]
        r = nv[nv.scheme_code == f.regular_code].set_index("nav_date")["nav"]
        j = pd.concat([d.rename("d"), r.rename("r")], axis=1, join="inner")
        j = j[(j.index >= pd.Timestamp(start)) & (j.index <= pd.Timestamp(end))]
        if len(j) < 2:
            continue
        rd, rr = j.d.iloc[-1] / j.d.iloc[0] - 1, j.r.iloc[-1] / j.r.iloc[0] - 1
        summ.append(dict(fund_id=f.fund_id, first=j.index[0].date(), last=j.index[-1].date(),
                         direct_return=rd, regular_return=rr, gap=rd - rr))
        if rd < rr:
            rows.append(dict(check="direct_return_below_regular", severity="fail", fund_id=f.fund_id,
                             scheme_code=f.direct_code, date=j.index[-1].date(), value=rd - rr,
                             detail=f"direct {rd:.4%} < regular {rr:.4%}: plan codes swapped?"))
    return rows, pd.DataFrame(summ)


def run() -> int:
    nav = pd.read_parquet(config.INTERIM / "nav.parquet")
    sm = pd.read_csv(config.REFERENCE / "scheme_map.csv")
    codes = set(sm.direct_code) | set(sm.regular_code)
    full = []
    for code in codes:  # nav.parquet is trimmed to the window; the Sep-2024 check needs raw history too
        p = config.RAW_NAV / f"{code}.json"
        if p.exists():
            import json
            from src.ingest.nav import parse_mfapi
            full.append(parse_mfapi(json.loads(p.read_text(encoding="utf-8")), int(code))[1])
    navfull = pd.concat(full, ignore_index=True) if full else nav
    now = parse_amfi_text(latest_navall().read_text(encoding="utf-8"), "navall")
    hist_path = config.RAW_AMFI / f"NAVHistory_{config.SURVIVORSHIP_SNAPSHOT_DATE.isoformat()}.txt"
    then = parse_amfi_text(hist_path.read_text(encoding="utf-8"), "history")
    issues = nav_vs_amfi(navfull, now, codes, "latest") + nav_vs_amfi(navfull, then, codes, "window_start")
    dr_issues, summ = direct_vs_regular(nav, sm)
    issues += dr_issues
    idf = pd.DataFrame(issues, columns=COLS)
    idf.to_csv(config.QUALITY / "nav_crosscheck_issues.csv", index=False)
    summ.to_csv(config.QUALITY / "direct_vs_regular.csv", index=False)
    n_latest = int(now.scheme_code.isin(codes).sum())
    n_then = int(then.scheme_code.isin(codes).sum())
    print(f"nav cross-check: mfapi vs AMFI on {max(now.nav_date)} ({n_latest} schemes) and "
          f"{config.SURVIVORSHIP_SNAPSHOT_DATE} ({n_then} schemes); direct>=regular for {len(summ)} funds; "
          f"issues={idf.groupby(['check','severity']).size().to_dict() if len(idf) else {}}")
    if len(summ):
        print(f"  direct-minus-regular return over window: min {summ.gap.min():.4%} "
              f"({summ.loc[summ.gap.idxmin(), 'fund_id']}), median {summ.gap.median():.4%}, max {summ.gap.max():.4%}")
    return 1 if (idf.severity == "fail").any() else 0
