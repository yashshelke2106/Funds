"""Download and parse AMFI NAV files.

Two AMFI formats are handled; both were inspected on 2026-09-25 (DECISIONS D-001):

1. NAVAll.txt (current snapshot), header:
   Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date
   Category lines look like  "Open Ended Schemes(Equity Scheme - Large Cap Fund)"

2. DownloadNAVHistoryReport_Po.aspx?frmdt=DD-Mon-YYYY (historical single date), header:
   Scheme Code;NAV Name;Plan;Option;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Net Asset Value;Date
   Category lines look like  "Open Ended Schemes ( Equity Scheme - Large Cap Fund )"

Both files interleave three kinds of line: category headers, AMC-name headers,
and ';'-separated data rows. The parser is a small state machine. If the header
line changes, parsing stops with an error rather than guessing (project rule).
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd
import requests

from src import config

NAVALL_HEADER = ("Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;"
                 "Scheme Name;Plan;Option;Net Asset Value;Date")
HISTORY_HEADER = ("Scheme Code;NAV Name;Plan;Option;ISIN Div Payout/ISIN Growth;"
                  "ISIN Div Reinvestment;Net Asset Value;Date")

NAVALL_COLS = ["scheme_code", "isin_growth_or_payout", "isin_reinvest",
               "scheme_name", "plan", "option", "nav", "nav_date"]
HISTORY_COLS = ["scheme_code", "scheme_name", "plan", "option",
                "isin_growth_or_payout", "isin_reinvest", "nav", "nav_date"]

OUT_COLS = ["scheme_code", "scheme_name", "plan", "option", "isin_growth_or_payout",
            "isin_reinvest", "nav", "nav_date", "amc", "category_raw", "category"]


class FormatChangedError(RuntimeError):
    """Raised when an AMFI file no longer matches the inspected layout."""


def normalise_category(line: str) -> str:
    """'Open Ended Schemes ( Equity Schemes - Large Cap Fund )' ->
    'Open Ended Schemes | Equity Scheme - Large Cap Fund'.

    AMFI uses both 'Equity Scheme' and 'Equity Schemes' for the same category.
    """
    m = re.match(r"^\s*(.*?)\s*\(\s*(.*?)\s*\)\s*$", line)
    if not m:
        raise FormatChangedError(f"Unrecognised category line: {line!r}")
    scheme_type, sub = m.group(1), m.group(2)
    sub = re.sub(r"\s+", " ", sub)
    sub = re.sub(r"^Equity Schemes\b", "Equity Scheme", sub)
    scheme_type = re.sub(r"\s+", " ", scheme_type)
    return f"{scheme_type} | {sub}"


def _is_category_line(s: str) -> bool:
    return "(" in s and s.endswith(")") and "Scheme" in s


def parse_amfi_text(text: str, kind: str) -> pd.DataFrame:
    """Parse an AMFI NAV text file. kind in {'navall', 'history'}."""
    if kind == "navall":
        expected, cols = NAVALL_HEADER, NAVALL_COLS
    elif kind == "history":
        expected, cols = HISTORY_HEADER, HISTORY_COLS
    else:
        raise ValueError(kind)

    lines = text.splitlines()
    if not lines or lines[0].strip() != expected:
        got = lines[0].strip() if lines else "<empty>"
        raise FormatChangedError(f"{kind} header changed.\nexpected: {expected}\ngot:      {got}")

    rows: list[dict] = []
    category_raw = category = amc = None
    for lineno, line in enumerate(lines[1:], start=2):
        s = line.strip()
        if not s:
            continue
        if ";" not in s:
            if _is_category_line(s):
                category_raw, category = s, normalise_category(s)
                amc = None
            else:
                amc = s
            continue
        parts = s.split(";")
        if len(parts) != len(cols):
            raise FormatChangedError(f"line {lineno}: expected {len(cols)} fields, got {len(parts)}: {s!r}")
        rec = dict(zip(cols, (p.strip() for p in parts)))
        rec["amc"] = amc
        rec["category_raw"] = category_raw
        rec["category"] = category
        rows.append(rec)

    df = pd.DataFrame(rows, columns=OUT_COLS)
    if df.empty:
        raise FormatChangedError(f"{kind}: no data rows parsed")
    if df["category"].isna().any():
        raise FormatChangedError(f"{kind}: data rows before any category header")
    # Real AMFI quirk (seen 2026-09-25): some blocks, e.g. Franklin segregated
    # portfolios, have no AMC header line. Such rows keep amc=None; the universe
    # step refuses any *selected* row without an AMC rather than guessing one.
    df["scheme_code"] = df["scheme_code"].astype(int)
    df["nav"] = pd.to_numeric(df["nav"].replace({"N.A.": None, "": None}), errors="coerce")
    df["nav_date"] = pd.to_datetime(df["nav_date"], format="%d-%b-%Y").dt.date
    for c in ("isin_growth_or_payout", "isin_reinvest"):
        df[c] = df[c].replace({"-": None, "": None})
    return df


def _get(url: str) -> str:
    last: Exception | None = None
    for _ in range(config.HTTP_RETRIES):
        try:
            r = requests.get(url, timeout=config.HTTP_TIMEOUT_S)
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:  # pragma: no cover - network
            last = e
    raise RuntimeError(f"GET failed after {config.HTTP_RETRIES} tries: {url}: {last}")


def download_navall(dest_dir: Path = config.RAW_AMFI) -> Path:
    """Save today's NAVAll.txt as data/raw/amfi/NAVAll_<nav_date>.txt."""
    text = _get(config.AMFI_NAVALL_URL)
    df = parse_amfi_text(text, "navall")  # validate before saving
    d = max(df["nav_date"])
    path = dest_dir / f"NAVAll_{d.isoformat()}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def download_history_snapshot(d: date, dest_dir: Path = config.RAW_AMFI) -> Path:
    url = config.AMFI_HISTORY_URL.format(d=d.strftime("%d-%b-%Y"))
    text = _get(url)
    df = parse_amfi_text(text, "history")
    if not (df["nav_date"] == d).any():
        raise RuntimeError(f"AMFI history report for {d} contains no NAVs dated {d} (holiday?). "
                           "Change SURVIVORSHIP_SNAPSHOT_DATE in src/config.py.")
    path = dest_dir / f"NAVHistory_{d.isoformat()}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def latest_navall(dest_dir: Path = config.RAW_AMFI) -> Path:
    files = sorted(dest_dir.glob("NAVAll_*.txt"))
    if not files:
        raise FileNotFoundError("No NAVAll_*.txt in data/raw/amfi — run the 'universe' step.")
    return files[-1]
