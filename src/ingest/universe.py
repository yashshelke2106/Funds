"""Build the study universe from AMFI files, not from a hand-typed list.

Outputs (data/reference/):
  scheme_map.csv     one row per fund: direct + regular Growth codes/ISINs
  scheme_events.csv  survivorship diff between window-start snapshot and today

Eligibility on NAV history is added later by src/ingest/nav.py (universe.csv).
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from src import config
from src.ingest.amfi import FormatChangedError, parse_amfi_text

LARGE_CAP = "Open Ended Schemes | Equity Scheme - Large Cap Fund"
INDEX_CATS = ("Index Funds - Equity Funds", "Other Scheme - Index Funds")
NIFTY100_RE = re.compile(r"\bnifty\s*100\s+index\s+fund\b", re.I)

SCHEME_MAP_COLS = ["fund_id", "role", "amc", "scheme_name", "direct_code", "direct_isin",
                   "regular_code", "regular_isin", "category", "source_file"]


def normalise_plan(plan: str | None) -> str | None:
    p = (plan or "").strip().lower()
    if p.startswith("direct"):
        return "direct"
    if p.startswith("regular"):
        return "regular"
    return None


def is_growth(option: str | None) -> bool:
    o = (option or "").strip().lower()
    if "growth" not in o:
        return False
    return not any(bad in o for bad in ("bonus", "idcw", "institutional", "dividend"))


def infer_from_name(name: str | None) -> tuple[str | None, bool]:
    """(plan, is_growth) from a history-report NAV Name such as
    'Motilal Oswal Large Cap Direct Plan Growth' (DECISIONS D-022)."""
    n = (name or "").lower()
    plan = "direct" if "direct" in n else ("regular" if "regular" in n else None)
    return plan, is_growth(n)


def resolve_blank_plans(df: pd.DataFrame, history: pd.DataFrame | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fill blank Plan/Option in NAVAll rows from the history snapshot's NAV Name (same scheme code).

    Returns (df with plan_n / growth / plan_source, unresolved rows)."""
    out = df.copy()
    out["plan_n"] = out["plan"].map(normalise_plan)
    out["growth"] = out["option"].map(is_growth)
    out["plan_source"] = "navall"
    blank = out["plan_n"].isna() | (out["option"].fillna("").str.strip() == "")
    if history is not None and blank.any():
        hname = history.drop_duplicates("scheme_code").set_index("scheme_code")["scheme_name"]
        for i in out.index[blank]:
            code = out.at[i, "scheme_code"]
            if code in hname.index:
                plan, growth = infer_from_name(hname[code])
                if plan is not None:
                    out.at[i, "plan_n"], out.at[i, "growth"] = plan, growth
                    out.at[i, "plan_source"] = "history_name"
    unresolved = out[out["plan_n"].isna()]
    return out, unresolved


def slugify(s: str) -> str:
    s = re.sub(r"\bmutual fund\b", "", s, flags=re.I)
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def select_growth_plans(df: pd.DataFrame) -> pd.DataFrame:
    """Rows that are Large Cap or Nifty 100 index funds, Growth option, explicit plan."""
    is_lc = df["category"].eq(LARGE_CAP)
    is_idx = df["category"].str.contains("|".join(INDEX_CATS), regex=True) & \
        df["scheme_name"].str.contains(NIFTY100_RE)
    out = df[is_lc | is_idx].copy()
    out["role"] = pd.Series("active", index=out.index).where(is_lc[out.index], "index")
    if "plan_n" not in out:
        out["plan_n"] = out["plan"].map(normalise_plan)
        out["growth"] = out["option"].map(is_growth)
    out = out[out["growth"].astype(bool) & out["plan_n"].notna()]
    return out


STALE_NAV_DAYS = 10


def build_scheme_map(df: pd.DataFrame, source_file: str, history: pd.DataFrame | None = None) -> pd.DataFrame:
    df, _ = resolve_blank_plans(df, history)
    g = select_growth_plans(df)
    problems = []
    if g["amc"].isna().any():
        problems += [f"no AMC header for scheme {c}" for c in g.loc[g.amc.isna(), "scheme_code"]]
    file_date = max(df["nav_date"])
    stale = g[g["nav_date"].map(lambda d: (file_date - d).days > STALE_NAV_DAYS)]
    problems += [f"stale NAV ({r.nav_date}) for {r.amc} / {r.scheme_name} [{r.scheme_code}] "
                 "— wound up? list it in scheme_events and exclude explicitly"
                 for r in stale.itertuples()]
    if problems:
        raise FormatChangedError("Universe problems:\n  " + "\n  ".join(problems))
    records = []
    for (amc, name, role), grp in g.groupby(["amc", "scheme_name", "role"], sort=True):
        d = grp[grp["plan_n"] == "direct"]
        r = grp[grp["plan_n"] == "regular"]
        if len(d) != 1 or len(r) != 1:
            problems.append(f"{amc} / {name}: {len(d)} direct, {len(r)} regular growth rows")
            continue
        suffix = "lc" if role == "active" else "n100"
        records.append({
            "fund_id": f"{slugify(amc)}_{suffix}",
            "role": role, "amc": amc, "scheme_name": name,
            "direct_code": int(d.iloc[0]["scheme_code"]),
            "direct_isin": d.iloc[0]["isin_growth_or_payout"],
            "regular_code": int(r.iloc[0]["scheme_code"]),
            "regular_isin": r.iloc[0]["isin_growth_or_payout"],
            "category": grp.iloc[0]["category"],
            "source_file": source_file,
        })
    if problems:
        raise FormatChangedError("Could not pair direct/regular growth plans:\n  " + "\n  ".join(problems))
    sm = pd.DataFrame(records, columns=SCHEME_MAP_COLS)
    if sm["fund_id"].duplicated().any():
        raise ValueError(f"duplicate fund_id: {sm.loc[sm.fund_id.duplicated(), 'fund_id'].tolist()}")
    return sm.sort_values(["role", "fund_id"]).reset_index(drop=True)


def survivorship_events(then: pd.DataFrame, now: pd.DataFrame) -> pd.DataFrame:
    """Compare Large Cap Growth plans at window start vs today, by scheme code.

    Names are NOT compared: the history report's 'NAV Name' embeds plan/option
    text ('... Fund - Growth - Direct Plan') while NAVAll has the bare scheme
    name, so a string diff would mark every scheme as renamed (DECISIONS D-007).
    Both names are written out for human review instead.
    """
    def lc(df):
        # every Large Cap plan code, any option: Plan/Option is blank for some live schemes
        # in NAVAll (D-022), so filtering on growth would invent closures.
        x = df[df["category"].eq(LARGE_CAP)]
        return x.set_index("scheme_code")[["amc", "scheme_name", "plan"]]

    t, n = lc(then), lc(now)
    rows = []
    for code in sorted(set(t.index) | set(n.index)):
        in_t, in_n = code in t.index, code in n.index
        if in_t and not in_n:
            ev = "closed_merged_or_recategorised"
        elif in_n and not in_t:
            ev = "not_large_cap_at_window_start"
        else:
            ev = "present_at_start_and_now"
        rows.append({
            "scheme_code": code,
            "amc": (n if in_n else t).at[code, "amc"],
            "plan": (n if in_n else t).at[code, "plan"],
            "name_at_start": t.at[code, "scheme_name"] if in_t else None,
            "name_now": n.at[code, "scheme_name"] if in_n else None,
            "event": ev,
        })
    return pd.DataFrame(rows)


def run(navall_path: Path, history_path: Path) -> tuple[Path, Path]:
    config.QUALITY.mkdir(parents=True, exist_ok=True)
    now = parse_amfi_text(navall_path.read_text(encoding="utf-8"), "navall")
    then = parse_amfi_text(history_path.read_text(encoding="utf-8"), "history")
    sm = build_scheme_map(now, navall_path.name, then)
    _, unresolved = resolve_blank_plans(now, then)
    in_scope = unresolved[unresolved["category"].eq(LARGE_CAP) |
                          unresolved["scheme_name"].str.contains(NIFTY100_RE)]
    in_scope[["scheme_code", "scheme_name", "amc", "category"]].to_csv(
        config.QUALITY / "universe_unresolved_plans.csv", index=False)
    if len(in_scope):
        print(f"WARNING: {len(in_scope)} in-scope NAVAll rows with blank plan not resolvable from "
              "the history snapshot -> data/quality/universe_unresolved_plans.csv")
    ev = survivorship_events(then, now)
    config.REFERENCE.mkdir(parents=True, exist_ok=True)
    p1 = config.REFERENCE / "scheme_map.csv"
    p2 = config.REFERENCE / "scheme_events.csv"
    config.QUALITY.mkdir(parents=True, exist_ok=True)
    sm.to_csv(p1, index=False)
    ev.to_csv(p2, index=False)
    print(f"scheme_map: {len(sm)} funds "
          f"({(sm.role == 'active').sum()} active, {(sm.role == 'index').sum()} index) -> {p1}")
    print("survivorship events:", ev["event"].value_counts().to_dict(), f"-> {p2}")
    return p1, p2
