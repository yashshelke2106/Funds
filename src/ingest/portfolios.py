"""Parse every AMC portfolio file into one normalised holdings table.

Input : data/raw/portfolios/<amc_slug>/<files>   (xlsx / csv, unedited)
Output: data/interim/holdings.parquet       one row per holding line
        data/interim/portfolio_meta.parquet one row per (fund_id, month)
        data/reference/isin_master.csv      ISIN <-> name, built from parsed equity rows
The month comes from INSIDE the file ('as on' date). If a file name starts with
'YYYY-MM__' it must agree, else the pipeline stops.
Look-ahead guard (D-009): available_from = 11th of the month after as_of.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pandas as pd

from src import config
from src.ingest.portfolio_common import (DerivativeExposureMismatch, PortfolioFormatError, check_units,
                                         isin_valid, parse_sheet, read_grid)

HOLDING_COLS = ["fund_id", "amc_slug", "month", "as_of", "available_from", "section",
                "section_label", "derivative_kind", "instrument_name", "name_key", "isin", "isin_raw",
                "isin_checksum_ok", "underlying_isin", "industry", "quantity",
                "market_value_lakh", "weight_nav", "weight_reported", "source_file",
                "source_sheet", "source_row"]


def norm_scheme(s: str) -> str:
    s = re.sub(r"\(.*?\)", " ", str(s))
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def name_key(s: str) -> str:
    """Company-name key used to map futures to the underlying equity ISIN."""
    s = str(s).lower()
    s = re.sub(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", " ", s)      # expiry dates 29.09.2026
    s = re.sub(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{2,4}\b", " ", s)  # 'October 2025'
    s = re.sub(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\d{2,4}\b", " ", s)   # DSP 'Mar26', Kotak 'SEP2026' (D-041)
    s = re.sub(r"\bfutures?\b", " ", s)
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\b(limited|ltd|the)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def scheme_index(sm: pd.DataFrame) -> dict[str, str]:
    idx = {}
    for r in sm.itertuples():
        k = norm_scheme(r.scheme_name)
        if k in idx and idx[k] != r.fund_id:
            raise ValueError(f"scheme name collision: {k}")
        idx[k] = r.fund_id
    return idx


def identify_scheme(grid: list[list], idx: dict[str, str], max_rows: int = 12) -> tuple[str | None, str | None]:
    for row in grid[:max_rows]:
        for v in row:
            if isinstance(v, str) and v.strip():
                k = norm_scheme(re.sub(r"^\s*scheme\s*:\s*", "", v, flags=re.I))   # UTI 'SCHEME: ...'
                if k not in idx:
                    # Kotak: 'Portfolio of Kotak Large Cap Fund as on 31-Aug-2026' (D-040)
                    m2 = re.match(r"^\s*portfolio of\s+(.+?)\s+as on\b", v, flags=re.I)
                    k = norm_scheme(m2.group(1)) if m2 else k
                if k in idx:
                    return idx[k], v.strip()
    return None, None


def split_blocks(grids: dict[str, list[list]], block_start: str | None) -> dict[str, list[list]]:
    """UTI puts every scheme in one sheet, each block opening with 'SCHEME CODE017STARTS' in
    column 0 (D-039). Split so each block is parsed like its own sheet ('EXPOSURE#CODE017')."""
    if not block_start:
        return grids
    rx, out = re.compile(block_start), {}
    for sheet, rows in grids.items():
        starts_at = [i for i, r in enumerate(rows) if r and isinstance(r[0], str) and rx.match(r[0].strip())]
        if not starts_at:
            out[sheet] = rows
            continue
        for a, b in zip(starts_at, starts_at[1:] + [len(rows)]):
            out[f"{sheet}#{rows[a][0].strip()}"] = rows[a:b]
    return out


def placeholder_isins() -> dict[str, str]:
    """{code printed in the file: real ISIN}, each with evidence in the reference file (D-039)."""
    p = config.REFERENCE / "placeholder_isins.csv"
    if not p.exists():
        return {}
    m = pd.read_csv(p, dtype=str)
    bad = [i for i in m["isin"] if not isin_valid(i)]
    if bad:
        raise PortfolioFormatError(f"placeholder_isins.csv maps to invalid ISINs: {bad}")
    return dict(zip(m["isin_raw"], m["isin"]))


def exposure_exceptions() -> set[tuple[str, str]]:
    """(fund_id, month) pairs whose parsed futures may differ from the file's stated derivative
    exposure, each with a written reason (D-036). Anything else that differs stops the pipeline."""
    p = config.REFERENCE / "derivative_exposure_exceptions.csv"
    if not p.exists():
        return set()
    ex = pd.read_csv(p, dtype=str)
    return set(zip(ex.fund_id, ex.month))


def parse_file(path: Path, slug: str, idx: dict[str, str]) -> tuple[list[pd.DataFrame], list[dict], list[str]]:
    mod = importlib.import_module(f"src.ingest.parsers.{slug}")
    cfg = mod.CONFIG
    frames, metas, log = [], [], []
    for sheet, grid in split_blocks(read_grid(path), cfg.block_start).items():
        if sheet in cfg.skip_sheets:
            log.append(f"{slug}/{path.name}[{sheet}]: skipped by parser config")
            continue
        fund_id, title = identify_scheme(grid, idx)
        if fund_id is None:
            log.append(f"{slug}/{path.name}[{sheet}]: no study scheme in title rows — ignored")
            continue
        exposure_gap = 0.0
        try:
            ps = parse_sheet(grid, cfg, title)
        except DerivativeExposureMismatch as e:
            ps = e.parsed_sheet
            key = (fund_id, ps.as_of.strftime("%Y-%m"))
            if key not in exposure_exceptions():
                raise
            exposure_gap = e.stated - e.parsed
            log.append(f"{slug}/{path.name}: stated derivative exposure Rs {e.stated:.2f} lakh, parsed Rs {e.parsed:.2f} lakh "
                       f"- documented exception {key} in data/reference/derivative_exposure_exceptions.csv")
        unit = check_units(ps, cfg)
        month = ps.as_of.strftime("%Y-%m")
        m = re.match(r"^(\d{4}-\d{2})__", path.name)
        if m and m.group(1) != month:
            raise PortfolioFormatError(f"{path.name}: file-name month {m.group(1)} != content month {month}")
        df = pd.DataFrame(ps.rows)
        ph = placeholder_isins()
        hit = df["isin_raw"].isin(list(ph))
        if hit.any():
            # D-039: placeholder codes for not-yet-listed demerger shares (UTI 'DU1205A01025'...) ->
            # the real ISIN other AMCs and the benchmark proxy use; isin_raw keeps the file's code.
            for code in sorted(set(df.loc[hit, "isin_raw"])):
                log.append(f"{slug}/{path.name}: placeholder {code} -> {ph[code]} (data/reference/placeholder_isins.csv)")
            df.loc[hit, "isin"] = df.loc[hit, "isin_raw"].map(ph)
            df.loc[hit, "isin_checksum_ok"] = df.loc[hit, "isin"].map(isin_valid)
        df["fund_id"], df["amc_slug"], df["month"], df["as_of"] = fund_id, slug, month, ps.as_of
        df["available_from"] = (pd.Timestamp(ps.as_of) + pd.offsets.MonthBegin(1) + pd.Timedelta(days=10)).date()
        df["weight_nav"] = df["market_value_lakh"] / ps.nav_lakh
        df["weight_reported"] = df["pct_reported_raw"] / unit
        df["name_key"] = df["instrument_name"].map(name_key)
        df["underlying_isin"] = None
        df["source_file"], df["source_sheet"] = f"{slug}/{path.name}", sheet
        frames.append(df)
        eq = df[df.section == "equity"]
        metas.append(dict(
            fund_id=fund_id, month=month, as_of=ps.as_of, amc_slug=slug, scheme_title=title,
            nav_lakh=ps.nav_lakh, grand_total_pct_raw=ps.grand_total_pct, pct_unit=cfg.pct_unit,
            reported_equity_total_lakh=ps.reported_equity_total_lakh,
            equity_mv_sum_lakh=eq["market_value_lakh"].sum(), equity_weight_raw=eq["weight_nav"].sum(),
            n_equity_rows=len(eq), n_derivative_rows=int((df.section == "derivative").sum()),
            derivative_net_weight=df.loc[df.section == "derivative", "weight_nav"].sum(),
            index_future_weight=df.loc[df.derivative_kind == "index_future", "weight_nav"].sum(),
            stated_benchmark=ps.stated_benchmark, stated_derivative_exposure_lakh=ps.stated_derivative_exposure_lakh,
            derivative_exposure_gap_lakh=exposure_gap,
            source_file=f"{slug}/{path.name}", source_sheet=sheet,
        ))
    return frames, metas, log


def map_derivative_underlyings(h: pd.DataFrame, overrides: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Stock futures -> underlying equity ISIN by company name, SAME MONTH first.

    ISINs change on corporate actions (Kotak INE237A01028 -> INE237A01036 between Dec-2025
    and Jan-2026), so an all-time name lookup can be ambiguous; the month's own equity rows
    decide. All-time lookup is only a fallback when it is unambiguous.
    """
    eq = h[(h.section == "equity") & h["isin"].notna()]
    master = (eq.groupby("isin").agg(name_key=("name_key", "first"), instrument_name=("instrument_name", "first"),
                                     first_month=("month", "min"), last_month=("month", "max"),
                                     n_sources=("source_file", "nunique")).reset_index())
    by_month = eq.groupby(["month", "name_key"])["isin"].unique()
    by_key = eq.groupby("name_key")["isin"].unique()
    ov = dict(zip(overrides["name_key"], overrides["isin"])) if overrides is not None and len(overrides) else {}
    d = (h.section == "derivative") & (h.derivative_kind == "stock_future")
    eq_isins = set(eq["isin"])
    out = []
    for i in h.index[d]:
        k, m = h.at[i, "name_key"], h.at[i, "month"]
        isin = None
        own = h.at[i, "isin"]
        if isinstance(own, str) and own in eq_isins:
            isin = own        # the file gives the underlying's equity ISIN on the futures row (UTI, D-039)
        elif (m, k) in by_month.index and len(by_month[(m, k)]) == 1:
            isin = by_month[(m, k)][0]
        elif (m, k) in by_month.index:
            raise PortfolioFormatError(f"{m}: several ISINs for '{k}' in the same month: {list(by_month[(m, k)])}")
        elif k in by_key.index and len(by_key[k]) == 1:
            isin = by_key[k][0]
        elif k in ov:
            isin = ov[k]
        out.append((i, isin))
    for i, isin in out:
        h.at[i, "underlying_isin"] = isin
    return h, master


def detect_isin_changes(h: pd.DataFrame) -> pd.DataFrame:
    """Corporate-action ISIN changes: same company name key, same issuer code (chars 3-7),
    never held under both ISINs in the same month. Written for review; used by turnover (P4)."""
    eq = h[(h.section == "equity") & h["isin"].notna()]
    rows = []
    for k, g in eq.groupby("name_key"):
        isins = g.groupby("isin")["month"].agg(["min", "max"]).sort_values("min")
        if len(isins) < 2:
            continue
        months = {i: set(g.loc[g["isin"] == i, "month"]) for i in isins.index}
        seq = list(isins.index)
        for a, b in zip(seq, seq[1:]):
            same_issuer = a[2:7] == b[2:7]
            overlap = bool(months[a] & months[b])
            rows.append(dict(name_key=k, old_isin=a, new_isin=b, old_last_month=isins.at[a, "max"],
                             new_first_month=isins.at[b, "min"], same_issuer_code=same_issuer,
                             months_overlap=overlap, accepted=same_issuer and not overlap))
    return pd.DataFrame(rows, columns=["name_key", "old_isin", "new_isin", "old_last_month", "new_first_month",
                                       "same_issuer_code", "months_overlap", "accepted"])


def run() -> Path:
    sm = pd.read_csv(config.REFERENCE / "scheme_map.csv")
    ref = pd.read_csv(config.REFERENCE / "reference_portfolios.csv")
    idx = scheme_index(pd.concat([sm[["fund_id", "scheme_name"]], ref[["fund_id", "scheme_name"]]]))
    frames, metas, log = [], [], []
    slugs = sorted(p for p in config.RAW_PORTFOLIOS.iterdir() if p.is_dir())
    for d in slugs:
        files = sorted(f for f in d.iterdir() if f.is_file() and not f.name.startswith((".", "~$")))
        if not files:
            continue
        if not (Path(__file__).parent / "parsers" / f"{d.name}.py").exists():
            raise PortfolioFormatError(f"no parser for '{d.name}' — upload one sample file for inspection first")
        for f in files:
            fr, me, lg = parse_file(f, d.name, idx)
            frames += fr; metas += me; log += lg
    if not frames:
        raise FileNotFoundError("no portfolio files parsed")
    h = pd.concat(frames, ignore_index=True)
    meta = pd.DataFrame(metas)
    lo, hi = config.HOLDINGS_START.strftime("%Y-%m"), config.WINDOW_END.strftime("%Y-%m")
    out_of_window = meta[(meta.month < lo) | (meta.month > hi)]
    for r in out_of_window.itertuples():
        log.append(f"{r.source_file}: month {r.month} outside holdings window {lo}..{hi} — dropped")
    keep = set(meta.loc[(meta.month >= lo) & (meta.month <= hi), "source_file"])
    h, meta = h[h.source_file.isin(keep)].copy(), meta[meta.source_file.isin(keep)].copy()
    dup = meta.duplicated(["fund_id", "month"], keep=False)
    if dup.any():
        raise PortfolioFormatError(f"same fund-month from several files: {meta.loc[dup, ['fund_id','month','source_file']].values.tolist()}")
    ov_path = config.REFERENCE / "isin_name_overrides.csv"
    overrides = pd.read_csv(ov_path) if ov_path.exists() else None
    h, master = map_derivative_underlyings(h, overrides)
    h = h[HOLDING_COLS]
    h.to_parquet(config.INTERIM / "holdings.parquet", index=False)
    meta.to_parquet(config.INTERIM / "portfolio_meta.parquet", index=False)
    master.to_csv(config.REFERENCE / "isin_master.csv", index=False)
    changes = detect_isin_changes(h)
    changes.to_csv(config.REFERENCE / "isin_changes.csv", index=False)
    if len(changes):
        log.append(f"ISIN changes detected: {len(changes)} ({int(changes.accepted.sum())} accepted) -> data/reference/isin_changes.csv")
    (config.QUALITY / "portfolio_parse_log.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
    print(f"portfolios: {len(meta)} fund-months, {len(h):,} holding rows -> data/interim/holdings.parquet")
    # sheets of non-study schemes in AMC-wide workbooks are expected; summarise, keep detail in the log file
    ignored = [l for l in log if "no study scheme in title rows" in l or "skipped by parser config" in l]
    per_file: dict[str, int] = {}
    for l in ignored:
        per_file[l.split("[")[0]] = per_file.get(l.split("[")[0], 0) + 1
    if ignored:
        print(f"  {len(ignored)} non-study sheets ignored across {len(per_file)} files "
              "(detail: data/quality/portfolio_parse_log.txt)")
    for line in log:
        if line not in ignored:
            print("  " + line)
    return config.INTERIM / "holdings.parquet"
