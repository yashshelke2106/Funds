"""Shared machinery for AMC monthly-portfolio parsers (DECISIONS D-016..D-019).

Every AMC file seen so far (Bandhan, HDFC, ICICI Prudential, SBI; Aug-2026, inspected
2026-09-25) is a single table with the same logical structure, but different:
column order, weight units (fraction vs percent), encodings, label columns, and
footnote markers. The per-AMC modules in src/ingest/parsers/ pass a small config;
this module walks the grid.

Walk rules (derived from the real files, not assumed):
  * a header row is any row containing a 'name' header and a 'quantity' or
    'market value' header; columns are (re)mapped at every header row, because SBI's
    derivatives table uses a different column layout from its main table.
  * a HOLDING row has a numeric quantity and a numeric market value. Section
    headers, subtotals, TREPS and net-current-asset lines have no quantity.
  * section = 'equity' after an 'Equity & Equity related' label, 'non_equity' after
    any other top-level section label, 'derivative' after a derivatives label.
    Rows are classified by section, never by ISIN prefix (commercial paper has
    INE ISINs too).
  * the GRAND TOTAL / Total Net Assets row gives NAV (Rs lakh) and the unit check.
  * after the grand total only a derivatives section is read; everything else
    (top-10 tables, industry splits, notes) is ignored.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")

HEADER_SYNONYMS = {
    "name": ("name of the instrument", "company/issuer/instrument name", "name of the instrument / issuer",
             "name of instrument"),
    "isin": ("isin",),
    "industry": ("industry / rating", "industry+ /rating", "industry/rating", "rating / industry^", "industry ^",
                 "rating / industry", "industry*"),
    "quantity": ("quantity",),
    "mv": ("market/fair value ( rs. in lacs)", "market/ fair value (rs. in lacs.)",
           "exposure/market value(rs.lakh)", "market value (rs. in lakhs)", "market value  (rs. in lakhs)",
           "market/fair value (rs. in lakhs)"),
    "pct": ("% to nav", "% to aum", "% to net assets"),
    "side": ("long / short",),
}
EQUITY_LABELS = ("equity & equity related", "equity and equity related")
NON_EQUITY_LABELS = ("debt instruments", "money market instruments", "others", "treps",
                     "cash & cash equivalents", "cash and cash equivalents",
                     "other current assets", "units of real estate", "units of an alternative",
                     "term deposits", "short term deposits", "mutual fund units")
DERIVATIVE_LABELS = ("derivatives", "details of stock future", "stock / index futures", "stock futures",
                     "index / stock futures")
INDEX_FUTURE_RE = re.compile(r"\b(nifty|banknifty|finnifty|midcpnifty|sensex|bankex)\b", re.I)
GRAND_TOTAL_LABELS = ("grand total", "total net assets")
TOTAL_LABELS = ("total", "sub total", "subtotal")
DERIVATIVE_END = ("derivatives total", "notes", "note-", "note -")


class PortfolioFormatError(RuntimeError):
    """The file does not match the layout the parser was written against."""


@dataclass
class ParserConfig:
    amc_slug: str
    pct_unit: str                      # 'fraction' | 'percent' | 'auto' (decided per file from GRAND TOTAL %) | 'auto' (read from GRAND TOTAL row)
    skip_sheets: tuple[str, ...] = ()  # sheet names to ignore entirely
    name_junk: tuple[str, ...] = ()    # footnote markers to strip from names


@dataclass
class ParsedSheet:
    scheme_title: str
    as_of: date
    nav_lakh: float
    grand_total_pct: float
    reported_equity_total_lakh: float | None
    stated_benchmark: str | None
    rows: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------- readers
def read_grid(path: Path) -> dict[str, list[list]]:
    """{sheet_name: rows}. xlsx via openpyxl (cached values); csv utf-8 then cp1252.

    Some AMCs (Nippon India) publish real .xlsx files with a '.xls' extension. The
    extension is not trusted: a '.xls' file is opened by its actual bytes — a zip
    (PK magic) is read as xlsx, anything else falls back to xlrd for legacy BIFF .xls.
    """
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm") or (suffix == ".xls" and _is_zip(path)):
        import openpyxl
        # openpyxl gates on the file EXTENSION before even looking at the bytes (rejects
        # '.xls' outright, see openpyxl.reader.excel._validate_archive) unless given a
        # file-like object, which skips that check. A mislabelled '.xlsx-as-.xls' file
        # (Nippon India) needs the object form; passing 'path' directly would re-raise
        # the same "does not support the old .xls file format" error we just ruled out.
        with open(path, "rb") as fh:
            wb = openpyxl.load_workbook(fh, read_only=True, data_only=True)
            return {ws.title: [list(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets}
    if suffix == ".xls":
        import xlrd
        wb = xlrd.open_workbook(str(path))
        return {sh.name: [sh.row_values(r) for r in range(sh.nrows)] for sh in wb.sheets()}
    if suffix == ".csv":
        raw = path.read_bytes()
        for enc in ("utf-8-sig", "cp1252"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise PortfolioFormatError(f"{path.name}: undecodable")
        return {path.stem: [list(r) for r in csv.reader(io.StringIO(text))]}
    raise PortfolioFormatError(f"{path.name}: unsupported file type {path.suffix}")


def _is_zip(path: Path) -> bool:
    with open(path, "rb") as fh:
        return fh.read(4) == b"PK\x03\x04"


# ---------------------------------------------------------------- cell helpers
def norm_text(v) -> str:
    return re.sub(r"\s+", " ", str(v)).strip().lower() if v is not None else ""


def to_number(v) -> float | None:
    """Numbers as stored, or strings like ' 32,850,000 ', ' (7,208.31)'. Markers ($, ^, NIL, -) -> None."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").strip()
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


def isin_valid(s: str | None) -> bool:
    """ISO 6166 check digit (letters -> 10..35, Luhn over the digit string)."""
    if not s or not ISIN_RE.match(s):
        return False
    digits = "".join(str(int(c, 36)) for c in s[:-1])
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d) * (2 if i % 2 == 0 else 1)
        total += n // 10 + n % 10
    return (10 - total % 10) % 10 == int(s[-1])


DATE_PATTERNS = (
    (re.compile(r"([A-Za-z]{3,9})\s+(\d{1,2})\s*,\s*(\d{4})"), "%B %d %Y", "mdY"),
    (re.compile(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})"), "%d %b %Y", "dmY"),
)


def find_as_of(grid: list[list], max_rows: int = 12) -> date:
    for row in grid[:max_rows]:
        for v in row:
            if v is None:
                continue
            s = str(v)
            if not re.search(r"as on|portfolio", s, re.I) and not re.fullmatch(r"\s*[A-Za-z]+ \d{1,2}, \d{4}\s*", s):
                continue
            for rx, _, order in DATE_PATTERNS:
                m = rx.search(s)
                if m:
                    a, b, c = m.groups()
                    txt = f"{b} {a[:3]} {c}" if order == "mdY" else f"{a} {b} {c}"
                    return pd.to_datetime(txt, format="%d %b %Y").date()
    raise PortfolioFormatError("no 'as on' date found in the first rows")


def row_label(row: list) -> str:
    """First text cell that is not a marker ('|') or a code in column 0."""
    for j, v in enumerate(row):
        if isinstance(v, str) and v.strip() and v.strip() != "|":
            if j == 0 and len(row) > 1 and row[1] not in (None, ""):
                continue  # col-0 security codes (Bandhan IBCL05, SBI 100012)
            return norm_text(v)
    return ""


HEADER_RULES = (
    # (key, predicate on the normalised header text). First matching cell, left to right, wins.
    ("name", lambda t: t.startswith("name of") or t.startswith("company/issuer") or t == "instrument name"),
    ("isin", lambda t: t.startswith("isin")),
    ("industry", lambda t: "industry" in t),
    ("quantity", lambda t: t.startswith("quantity")),
    ("mv", lambda t: ("market" in t and "value" in t) or t.startswith("exposure/market value")),
    ("pct", lambda t: t.startswith("% to")),
    ("side", lambda t: t == "long / short"),
)


def map_header(row: list) -> dict[str, int] | None:
    """Locate columns by RULE on header text (not exact strings), because wording varies
    across AMCs and across months within one AMC (Motilal: 'ISIN' -> 'ISIN Code')."""
    cells = {j: norm_text(v).replace("\n", " ") for j, v in enumerate(row) if isinstance(v, str) and v.strip()}
    found: dict[str, int] = {}
    for j in sorted(cells):
        t = cells[j]
        for key, pred in HEADER_RULES:
            if key not in found and pred(t):
                found[key] = j
                break
    if "name" in found and ("quantity" in found or "mv" in found):
        return found
    return None


def starts(label: str, options) -> bool:
    return any(label.startswith(o) for o in options)


# ---------------------------------------------------------------- the walker
def parse_sheet(grid: list[list], cfg: ParserConfig, scheme_title: str) -> ParsedSheet:
    as_of = find_as_of(grid)
    cols: dict[str, int] | None = None
    section = "pre"
    section_label = ""
    nav = gt_pct = None
    reported_eq = None          # equity total printed on the header row (ICICI style)
    eq_totals: list[tuple[str, float]] = []   # ('total'|'sub total'|'subtotal', value) inside equity
    benchmark = None
    rows: list[dict] = []
    for i, row in enumerate(grid, start=1):
        if not any(v not in (None, "") for v in row):
            continue
        label = row_label(row)
        if "benchmark name" in label:
            benchmark = re.sub(r"^.*benchmark name\s*[-:]?\s*", "", label).strip() or benchmark
        h = map_header(row)
        if h:
            cols = h
            continue
        if cols is None:
            continue
        g = lambda k: row[cols[k]] if k in cols and cols[k] < len(row) else None  # noqa: E731
        qty, mv = to_number(g("quantity")), to_number(g("mv"))

        # ---- state transitions on label rows
        if section == "derivative" and nav is None and starts(label, GRAND_TOTAL_LABELS):
            nav, gt_pct = mv, to_number(g("pct"))
            section = "post"
            continue
        if section == "derivative" and nav is None and qty is None and starts(label, NON_EQUITY_LABELS):
            section, section_label = "non_equity", label
            continue
        if section == "derivative" and starts(label, DERIVATIVE_END):
            section = "done"
            continue
        if section in ("pre", "equity", "non_equity"):
            if starts(label, GRAND_TOTAL_LABELS):
                nav, gt_pct = mv, to_number(g("pct"))
                section = "post"
                continue
            if starts(label, EQUITY_LABELS):
                section, section_label = "equity", label
                if mv is not None and qty is None:
                    reported_eq = mv          # ICICI puts the equity total on the header row
                continue
            if section != "pre" and qty is None and starts(label, NON_EQUITY_LABELS):
                section, section_label = "non_equity", label
                continue
            if section == "equity" and qty is None and label in TOTAL_LABELS and mv is not None:
                eq_totals.append((label, mv))
                continue
        if section in ("post", "equity", "non_equity") and qty is None and starts(label, DERIVATIVE_LABELS):
            section, section_label = "derivative", label
            continue
        if section in ("pre", "post", "done"):
            continue
        if qty is None or mv is None:
            continue   # headers, subtotals, TREPS, cash lines: not holdings

        name = str(g("name") or "").strip()
        for junk in cfg.name_junk:
            name = name.replace(junk, "")
        name = name.strip()
        isin = str(g("isin")).strip().upper() if g("isin") not in (None, "") else None
        side = norm_text(g("side")) if "side" in cols else None
        if section == "derivative":
            sign = -1.0 if (side and "short" in side) else 1.0
            if qty < 0 or mv < 0:
                sign = 1.0  # already signed in the file (ICICI)
            qty, mv = qty * sign, mv * sign
        kind = None
        if section == "derivative":
            kind = "index_future" if INDEX_FUTURE_RE.search(name) else "stock_future"
        rows.append(dict(
            section=section, section_label=section_label, instrument_name=name, derivative_kind=kind,
            isin=isin if isin and isin_valid(isin) else None,
            isin_raw=isin, isin_checksum_ok=bool(isin and isin_valid(isin)),
            industry=str(g("industry")).strip() if g("industry") not in (None, "") else None,
            quantity=qty, market_value_lakh=mv, pct_reported_raw=to_number(g("pct")),
            source_row=i,
        ))
    if nav is None:
        raise PortfolioFormatError(f"{scheme_title}: no GRAND TOTAL / Total Net Assets row")
    reported_eq = resolve_equity_total(eq_totals, reported_eq)
    if not any(r["section"] == "equity" for r in rows):
        raise PortfolioFormatError(f"{scheme_title}: no equity holdings found")
    return ParsedSheet(scheme_title, as_of, nav, gt_pct, reported_eq, benchmark, rows)


def resolve_equity_total(eq_totals: list[tuple[str, float]], header_value: float | None) -> float | None:
    """The file's own equity total, for reconciliation (D-017).

    * Sub-totals present (Bandhan, HDFC, Motilal new layout): the 'Total' row is the overall
      equity total -> take the last 'Total'; if there is none, sum the sub-totals.
    * Only 'Total' rows (SBI; Motilal old layout, where listed and unlisted blocks each end
      in 'Total' with no overall line): they are per-block -> SUM them. Motilal Oct-2025 needed
      this: listed 6171.89 + unlisted/awaiting-listing TML Commercial Vehicles 28.62.
    * No total rows: the value printed on the equity header row (ICICI).
    """
    if not eq_totals:
        return header_value
    subs = [v for lab, v in eq_totals if lab in ("sub total", "subtotal")]
    tots = [v for lab, v in eq_totals if lab == "total"]
    if subs:
        return tots[-1] if tots else sum(subs)
    return sum(tots)


def check_units(ps: ParsedSheet, cfg: ParserConfig) -> float:
    """Return the divisor that turns reported % into a fraction; verify via grand total."""
    if cfg.pct_unit == "auto":
        if ps.grand_total_pct is not None and abs(ps.grand_total_pct - 1.0) <= 0.01:
            return 1.0
        if ps.grand_total_pct is not None and abs(ps.grand_total_pct - 100.0) <= 1.0:
            return 100.0
        raise PortfolioFormatError(f"{ps.scheme_title}: cannot infer % unit from grand total {ps.grand_total_pct}")
    expect = 1.0 if cfg.pct_unit == "fraction" else 100.0
    if ps.grand_total_pct is None or abs(ps.grand_total_pct - expect) > 0.01 * expect:
        raise PortfolioFormatError(f"{ps.scheme_title}: grand-total % {ps.grand_total_pct} "
                                   f"inconsistent with unit '{cfg.pct_unit}'")
    return expect
