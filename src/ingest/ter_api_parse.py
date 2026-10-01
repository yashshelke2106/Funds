"""AMFI TER JSON API pages -> daily TER per study fund (DECISIONS D-049..D-052).

Input: pages cached by src.ingest.ter_api at data/raw/ter/api/mf_<id>/<YYYY-MM>/cat_<strCat>/pNNN.json.
Output: the same long table ter.py builds from the Excel exports (fund x plan x day, components + total),
so everything downstream is unchanged.

Two field sets, told apart per row (seen on real pages, 2026-09-28):
  old (e.g. Sep-2024): R_/D_ BaseTER, 6A_B, 6A_C, GST, TER  -> base, addl_b, addl_c, levies, total
  new (e.g. Aug-2026): R_/D_ BER, BrokerageCost, TransactionCost,
                       StatutoryLevies, TER                  -> base, brokerage, txn, levies, total
This is the mapping ter.py uses for the Excel columns (D-024), so both sources land in identical columns.
A row with any other field set stops the build.

Matching (D-050):
  active fund: the only scheme under Large Cap IDs {15, 74} for its AMC on each day. Exactly one row per
               (day, plan) and one scheme per day, else stop. A non-blank NSDL code must equal the fund's
               code in ter_scheme_map.csv (blank codes are normal before 2026).
  index fund:  rows under index IDs {50, 101} whose NSDL code is the fund's code, or whose normalised name
               is one of the fund's names (scheme_map name + every name seen with its code). Exactly one row
               per (day, plan), else stop. A row with an accepted name but a different code stops the build.
A fund-plan-month with no rows stops the build if that plan had NAVs by month end; before its first
NAV it is simply not launched yet.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pandas as pd

from src import config
from src.ingest.ter import COMPONENTS, TerFormatError, norm_name
from src.ingest.ter_api import INDEX_CATS, LARGE_CAP_CATS, check_filtered_labels, meta, month_param, rows_key

ID_KEYS = {"NSDLSchemeCode", "Scheme_Name", "SchemeType_Desc", "SchemeCat_Desc", "TER_Year", "TER_Date",
           "MF_ID", "Month"}
FIELDS = {
    "old": {"base": "BaseTER", "addl_b": "6A_B", "addl_c": "6A_C", "levies": "GST", "total": "TER"},
    "new": {"base": "BER", "brokerage": "BrokerageCost", "txn": "TransactionCost",
            "levies": "StatutoryLevies", "total": "TER"},
}
PLAN_PREFIX = {"regular": "R_", "direct": "D_"}
SUM_TOL = 0.011  # D-030: components must add to Total TER
LONG_COLS = ["nsdl_code", "scheme_name", "category", "ter_date", "plan", *COMPONENTS, "format", "source_file"]


def row_format(r: dict) -> str:
    missing = ID_KEYS - set(r)
    if missing:
        raise TerFormatError(f"TER API row lacks {sorted(missing)}")
    keys = set(r) - ID_KEYS
    for fmt, spec in FIELDS.items():
        if keys == {pre + f for pre in PLAN_PREFIX.values() for f in spec.values()}:
            return fmt
    raise TerFormatError(f"TER API row has an unrecognised field set: {sorted(keys)}")


def _num(v) -> float:
    if v is None or (isinstance(v, str) and not v.strip()):
        return float("nan")
    try:
        return float(v)
    except (TypeError, ValueError) as e:
        raise TerFormatError(f"non-numeric TER value {v!r}") from e


def _date(s, ym: str) -> date:
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})T00:00:00(?:\.0+)?Z", str(s))
    if not m:
        raise TerFormatError(f"unexpected TER_Date {s!r}")
    d = date.fromisoformat(m.group(1))
    if d.strftime("%Y-%m") != ym:
        raise TerFormatError(f"TER_Date {d} outside the page's month {ym}")
    return d


def rows_to_long(rows: list[dict], ym: str, source: str) -> pd.DataFrame:
    out = []
    for r in rows:
        fmt = row_format(r)
        if r["Month"] != month_param(ym):
            raise TerFormatError(f"row Month {r['Month']!r} on a {ym} page ({source})")
        d = _date(r["TER_Date"], ym)
        for plan, pre in PLAN_PREFIX.items():
            vals = {c: float("nan") for c in COMPONENTS}
            for comp, f in FIELDS[fmt].items():
                vals[comp] = _num(r[pre + f])
            if pd.isna(vals["total"]):
                continue  # plan not offered: drop it, never invent a zero (same rule as ter.py)
            parts = pd.Series([vals[c] for c in FIELDS[fmt] if c != "total"]).sum()  # NaN-skipping, as ter.py
            if abs(parts - vals["total"]) > SUM_TOL:
                raise TerFormatError(f"{source}: components {parts:.4f} != Total TER {vals['total']:.4f} "
                                     f"for {r['Scheme_Name']} {d} {plan}")
            out.append(dict(nsdl_code=re.sub(r"\s+", "", r["NSDLSchemeCode"] or ""),
                            scheme_name=str(r["Scheme_Name"]).strip(), category=str(r["SchemeCat_Desc"]).strip(),
                            ter_date=d, plan=plan, **vals, format=fmt, source_file=source))
    return pd.DataFrame(out, columns=LONG_COLS)


def load_month(raw_dir: Path, mf_id: int, ym: str, cats) -> pd.DataFrame:
    """All rows for one AMC-month over the given category IDs. Re-checks completeness, because a run that
    died between pages leaves a month with some pages missing."""
    frames = []
    for c in cats:
        d = raw_dir / f"mf_{mf_id}" / ym / f"cat_{c}"
        files = sorted(d.glob("p*.json"))
        if not files:
            raise TerFormatError(f"no pages in {d} - run `python -m src.ingest.ter_api fetch`")
        pages = [json.loads(f.read_text(encoding="utf-8")) for f in files]
        m = meta(pages[0])
        want_pages = max(int(m["pageCount"]), 1)
        rows = [r for p in pages for r in p[rows_key(p)]]
        if len(files) != want_pages or len(rows) != int(m["total"]):
            raise TerFormatError(f"{d}: {len(files)} page(s) / {len(rows)} rows on disk, server said "
                                 f"{want_pages} / {m['total']} - incomplete fetch, rerun the fetch")
        check_filtered_labels(pages, c)
        rel = d.relative_to(raw_dir).as_posix()
        frames.append(rows_to_long(rows, ym, f"api/{rel}"))
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=LONG_COLS)


def _one_per_day(df: pd.DataFrame, what: str) -> None:
    n = df.groupby(["ter_date", "plan"]).size()
    if (n > 1).any():
        k = n[n > 1].index[0]
        names = sorted(df[(df.ter_date == k[0]) & (df.plan == k[1])].scheme_name.unique())
        raise TerFormatError(f"{what}: {int(n[k])} rows on {k[0]} {k[1]} ({names}) - expected exactly one")


def match_active(lc: pd.DataFrame, fund_id: str, code: str | None, where: str,
                 ignore_codes: frozenset = frozenset()) -> pd.DataFrame:
    """`ignore_codes`: values listed in ter_api_code_exceptions.csv for this fund-month (D-053), treated as no code."""
    if lc.empty:
        return lc.assign(fund_id=fund_id)
    per_day = lc.groupby("ter_date").scheme_name.nunique()
    if (per_day > 1).any():
        d = per_day[per_day > 1].index[0]
        raise TerFormatError(f"{where}: {int(per_day[d])} Large Cap schemes on {d} "
                             f"{sorted(lc[lc.ter_date == d].scheme_name.unique())} - SEBI allows one per AMC")
    _one_per_day(lc, where)
    if code:
        bad = lc[(lc.nsdl_code != "") & (lc.nsdl_code != code) & ~lc.nsdl_code.isin(ignore_codes)]
        if len(bad):
            raise TerFormatError(f"{where}: Large Cap scheme {bad.scheme_name.iloc[0]!r} has NSDL code "
                                 f"{bad.nsdl_code.iloc[0]}, but {fund_id} is {code} in ter_scheme_map.csv")
    return lc.assign(fund_id=fund_id)


def index_names(ix_all: pd.DataFrame, scheme_name: str, code: str | None) -> tuple[str, set[str]]:
    """The fund's NSDL code (known, or found on rows carrying its exact name) and every name seen with it."""
    names = {norm_name(scheme_name)}
    if not code:
        found = set(ix_all.loc[ix_all.scheme_name.map(norm_name).isin(names) & (ix_all.nsdl_code != ""), "nsdl_code"])
        if len(found) > 1:
            raise TerFormatError(f"{scheme_name}: several NSDL codes carry this name: {sorted(found)}")
        code = found.pop() if found else ""
    if code:
        names |= set(ix_all.loc[ix_all.nsdl_code == code, "scheme_name"].map(norm_name))
    return code, names


def match_index(ix: pd.DataFrame, fund_id: str, code: str, names: set[str], where: str) -> pd.DataFrame:
    by_name = ix.scheme_name.map(norm_name).isin(names)
    by_code = (ix.nsdl_code == code) & (code != "")
    hit = ix[by_name | by_code]
    clash = hit[(hit.nsdl_code != "") & (hit.nsdl_code != code)]
    if len(clash):
        raise TerFormatError(f"{where}: {clash.scheme_name.iloc[0]!r} has code {clash.nsdl_code.iloc[0]}, "
                             f"expected {code or '(none known)'} for {fund_id}")
    _one_per_day(hit, where)
    return hit.assign(fund_id=fund_id)


def load_code_exceptions(path: Path) -> pd.DataFrame:
    cols = ["fund_id", "month", "code", "reason"]
    if not path.exists():
        return pd.DataFrame(columns=cols)
    ex = pd.read_csv(path, dtype=str).fillna("")
    if list(ex.columns) != cols or (ex.reason.str.strip() == "").any():
        raise TerFormatError(f"{path.name}: needs columns {cols} and a reason on every row")
    return ex


def build(raw_dir: Path, scheme_map: pd.DataFrame, universe: pd.DataFrame, code_map: pd.DataFrame,
          mf_ids: dict[str, int], months: list[str], code_exceptions: pd.DataFrame | None = None) -> pd.DataFrame:
    """Matched long table for every study fund over `months` (D-050). Collects every gap before stopping,
    so one run shows all of them. A code exception that matches nothing also stops the build (no stale entries)."""
    codes = dict(zip(code_map.fund_id, code_map.nsdl_code))
    ex = code_exceptions if code_exceptions is not None else load_code_exceptions(Path("/nonexistent"))
    ex_codes = {(f, m): set(g.code) for (f, m), g in ex.groupby(["fund_id", "month"])}
    used = set()
    first_nav = {(r.fund_id, plan): pd.Timestamp(getattr(r, f"{plan}_first_nav"))
                 for r in universe.itertuples() for plan in PLAN_PREFIX
                 if pd.notna(getattr(r, f"{plan}_first_nav"))}
    frames, gaps = [], []
    for amc, g in scheme_map.groupby("amc"):
        mf_id = mf_ids[amc]
        active = g[g.role == "active"]
        index = g[g.role == "index"]
        if len(active) != 1:
            raise TerFormatError(f"{amc}: expected one active fund in scheme_map, got {list(active.fund_id)}")
        a = active.iloc[0]
        ix_months = {}
        for ym in months:
            lc = load_month(raw_dir, mf_id, ym, LARGE_CAP_CATS)
            ign = frozenset(ex_codes.get((a.fund_id, ym), set()))
            frames.append(match_active(lc, a.fund_id, codes.get(a.fund_id), f"{amc} {ym}", ign))
            used |= {(a.fund_id, ym, c) for c in ign if (lc.nsdl_code == c).any()}
            if len(index):
                ix_months[ym] = load_month(raw_dir, mf_id, ym, INDEX_CATS)
        if len(index):
            ix_all = pd.concat(ix_months.values(), ignore_index=True)
            for f in index.itertuples():
                code, names = index_names(ix_all, f.scheme_name, codes.get(f.fund_id))
                for ym, ix in ix_months.items():
                    frames.append(match_index(ix, f.fund_id, code, names, f"{f.fund_id} {ym}"))
    stale = [(r.fund_id, r.month, r.code) for r in ex.itertuples() if (r.fund_id, r.month, r.code) not in used]
    if stale:
        raise TerFormatError(f"ter_api_code_exceptions.csv entries that match no row (remove them): {stale}")
    frames = [f for f in frames if not f.empty]
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=LONG_COLS + ['fund_id'])
    have = set(zip(out.fund_id, out.plan, pd.to_datetime(out.ter_date).dt.strftime("%Y-%m")))
    for f in scheme_map.fund_id:
        for plan in PLAN_PREFIX:
            fn = first_nav.get((f, plan))
            for ym in months:
                month_end = pd.Period(ym, "M").end_time.normalize()
                if (f, plan, ym) not in have and fn is not None and fn <= month_end:
                    gaps.append(f"{f} {plan} {ym} (first NAV {fn.date()})")
    if gaps:
        raise TerFormatError(f"{len(gaps)} fund-plan-month(s) have NAVs but no TER rows in the API data: "
                             + "; ".join(gaps[:12]) + (" ..." if len(gaps) > 12 else ""))
    return out


def compare_with_excel(api: pd.DataFrame, excel: pd.DataFrame) -> dict:
    """Every (fund, plan, day) in both sources must agree on all components and the format (D-049).
    An Excel row the API lacks, inside a month the API covers, also stops the build."""
    key = ["fund_id", "plan", "ter_date"]
    a = api.assign(ter_date=pd.to_datetime(api.ter_date).dt.date)
    x = excel.assign(ter_date=pd.to_datetime(excel.ter_date).dt.date)
    j = a.merge(x, on=key, how="outer", suffixes=("_api", "_xl"), indicator=True)
    api_months = set(zip(a.fund_id, pd.to_datetime(a.ter_date).dt.strftime("%Y-%m")))
    in_api_month = pd.Series([(f, pd.Timestamp(d).strftime("%Y-%m")) in api_months
                              for f, d in zip(j.fund_id, j.ter_date)], index=j.index, dtype=bool)
    xl_only = j[(j._merge == "right_only") & in_api_month]
    if len(xl_only):
        r = xl_only.iloc[0]
        raise TerFormatError(f"{len(xl_only)} Excel TER row(s) missing from the API data, e.g. "
                             f"{r.fund_id} {r.plan} {r.ter_date}")
    both = j[j._merge == "both"]
    for c in COMPONENTS + ["format"]:
        va, vx = both[f"{c}_api"], both[f"{c}_xl"]
        if c == "format":
            diff = va != vx
        else:
            diff = ~((va.isna() & vx.isna()) | ((va - vx).abs() <= 1e-9))
        if diff.any():
            r = both[diff].iloc[0]
            raise TerFormatError(f"API vs Excel disagree on {c} for {r.fund_id} {r.plan} {r.ter_date}: "
                                 f"{r[f'{c}_api']} vs {r[f'{c}_xl']}")
    return {"rows_compared": int(len(both)), "funds": int(both.fund_id.nunique()),
            "months": sorted({pd.Timestamp(d).strftime("%Y-%m") for d in both.ter_date})}
