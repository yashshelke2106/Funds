"""Fetch daily NAV history from mfapi.in for every code in scheme_map.csv.

mfapi response (inspected 2026-09-25, scheme 118825, DECISIONS D-001):
  {"meta": {"fund_house", "scheme_type", "scheme_category", "scheme_code",
            "scheme_name", "isin_growth", "isin_div_reinvestment"},
   "data": [{"date": "dd-mm-yyyy", "nav": "123.10900"}, ...],   # newest first
   "status": "SUCCESS"}

Raw JSON is cached verbatim in data/raw/nav/<code>.json (re-fetch with --refresh).
Parsed output: data/interim/nav.parquet  (scheme_code, nav_date, nav)
Eligibility:   data/reference/universe.csv
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
import requests

from src import config

NAV_COLS = ["scheme_code", "nav_date", "nav"]


class SourceError(RuntimeError):
    pass


def parse_mfapi(payload: dict, expected_code: int) -> tuple[dict, pd.DataFrame]:
    if payload.get("status") != "SUCCESS":
        raise SourceError(f"{expected_code}: status={payload.get('status')!r}")
    meta = payload.get("meta") or {}
    if int(meta.get("scheme_code", -1)) != expected_code:
        raise SourceError(f"{expected_code}: meta.scheme_code={meta.get('scheme_code')}")
    data = payload.get("data")
    if not data:
        raise SourceError(f"{expected_code}: empty data")
    df = pd.DataFrame(data)
    if set(df.columns) != {"date", "nav"}:
        raise SourceError(f"{expected_code}: unexpected data keys {sorted(df.columns)}")
    out = pd.DataFrame({
        "scheme_code": expected_code,
        "nav_date": pd.to_datetime(df["date"], format="%d-%m-%Y").dt.date,
        "nav": pd.to_numeric(df["nav"], errors="coerce"),
    })
    if out["nav"].isna().any():
        bad = df.loc[out["nav"].isna(), "nav"].unique()[:5]
        raise SourceError(f"{expected_code}: non-numeric NAV values {list(bad)}")
    return meta, out.sort_values("nav_date").reset_index(drop=True)


def fetch_one(code: int, refresh: bool = False, raw_dir: Path = config.RAW_NAV) -> dict:
    path = raw_dir / f"{code}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    last: Exception | None = None
    for attempt in range(config.HTTP_RETRIES):
        try:
            r = requests.get(config.MFAPI_URL.format(code=code), timeout=config.HTTP_TIMEOUT_S)
            r.raise_for_status()
            payload = r.json()
            path.write_text(json.dumps(payload), encoding="utf-8")
            time.sleep(config.HTTP_SLEEP_S)
            return payload
        except (requests.RequestException, ValueError) as e:  # pragma: no cover - network
            last = e
            time.sleep(2 ** attempt)
    raise SourceError(f"{code}: fetch failed: {last}")


def eligibility(scheme_map: pd.DataFrame, nav: pd.DataFrame, metas: dict[int, dict]) -> pd.DataFrame:
    span = nav.groupby("scheme_code")["nav_date"].agg(first_nav="min", last_nav="max", n_obs="size")
    rows = []
    for _, f in scheme_map.iterrows():
        rec = f.to_dict()
        for plan in ("direct", "regular"):
            code = int(f[f"{plan}_code"])
            s = span.loc[code] if code in span.index else None
            meta = metas.get(code, {})
            rec[f"{plan}_first_nav"] = s["first_nav"] if s is not None else None
            rec[f"{plan}_last_nav"] = s["last_nav"] if s is not None else None
            rec[f"{plan}_mfapi_category"] = meta.get("scheme_category")
            rec[f"{plan}_mfapi_isin"] = meta.get("isin_growth")
            rec[f"{plan}_isin_match"] = meta.get("isin_growth") == f[f"{plan}_isin"]
        firsts = [rec["direct_first_nav"], rec["regular_first_nav"]]
        lasts = [rec["direct_last_nav"], rec["regular_last_nav"]]
        known = all(x is not None for x in firsts + lasts)
        rec["covers_holdings_window"] = known and max(firsts) <= config.WINDOW_START \
            and min(lasts) >= config.WINDOW_END
        rec["covers_rolling_lookback"] = known and max(firsts) <= config.NAV_START
        rec["eligible"] = bool(rec["covers_holdings_window"] and rec["direct_isin_match"]
                               and rec["regular_isin_match"])
        reasons = []
        if not rec["covers_holdings_window"]:
            reasons.append("nav_history_shorter_than_window")
        if not (rec["direct_isin_match"] and rec["regular_isin_match"]):
            reasons.append("isin_mismatch_amfi_vs_mfapi")
        rec["exclusion_reason"] = ";".join(reasons) or None
        rows.append(rec)
    return pd.DataFrame(rows)


def run(refresh: bool = False) -> Path:
    sm = pd.read_csv(config.REFERENCE / "scheme_map.csv")
    codes = sorted(set(sm["direct_code"]).union(sm["regular_code"]))
    frames, metas, errors = [], {}, []
    for i, code in enumerate(codes, 1):
        try:
            meta, df = parse_mfapi(fetch_one(int(code), refresh), int(code))
            metas[int(code)] = meta
            frames.append(df)
            print(f"[{i:>3}/{len(codes)}] {code} {meta.get('scheme_name')} "
                  f"{df.nav_date.min()}..{df.nav_date.max()} n={len(df)}")
        except SourceError as e:
            errors.append(str(e))
            print(f"[{i:>3}/{len(codes)}] ERROR {e}")
    if errors:
        (config.QUALITY / "nav_fetch_errors.txt").write_text("\n".join(errors), encoding="utf-8")
        raise SourceError(f"{len(errors)} scheme(s) failed; see data/quality/nav_fetch_errors.txt. "
                          "Stopping — no data is substituted.")
    nav = pd.concat(frames, ignore_index=True)
    nav = nav[nav["nav_date"] >= config.NAV_START].reset_index(drop=True)
    out = config.INTERIM / "nav.parquet"
    nav.to_parquet(out, index=False)
    uni = eligibility(sm, nav, metas)
    uni.to_csv(config.REFERENCE / "universe.csv", index=False)
    print(f"nav rows: {len(nav):,} -> {out}")
    print(f"eligible funds: active={int(uni[(uni.role == 'active')].eligible.sum())}"
          f"/{int((uni.role == 'active').sum())}, index={int(uni[(uni.role == 'index')].eligible.sum())}"
          f"/{int((uni.role == 'index').sum())}")
    ex = uni[~uni["eligible"]]
    for _, r in ex.iterrows():
        print(f"  excluded: {r.fund_id}: {r.exclusion_reason}")
    return out
