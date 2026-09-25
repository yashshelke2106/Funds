"""Motilal Oswal MF: ONE workbook per month with a sheet per scheme (codes 'YO01'..), plus an Index sheet.
Inspected all 12 files Sep-2025..Aug-2026 (2026-09-25). TWO layouts inside the window:
  * up to Mar-2026: row 1 scheme name, row 2 'Portfolio as on March 31, 2026'; header 'Name of Instrument',
    '% to Net Assets' as FRACTIONS; a 'Derivatives > Index / Stock Futures' block sits BEFORE GRAND TOTAL.
  * from Apr-2026: AMC letterhead rows 1-5, row 6 'MONTHLY PORTFOLIO STATEMENT AS ON AUGUST 31, 2026',
    row 8 scheme name in capitals; header 'Name of the Instrument', '% to Net Assets' in PERCENT.
Unit is therefore detected per file from the GRAND TOTAL row (pct_unit='auto').
The large-cap scheme was sheet YO47 in Mar- and Aug-2026, but sheets are identified by title, not code.
Known source defect (Aug-2026): the month-end NAV note lists scheme codes against the wrong values;
that note is not read. Filenames are unreliable ('...october-2025.xlsx' holds Sep-30-2025).
"""
from src.ingest.portfolio_common import ParserConfig

CONFIG = ParserConfig(amc_slug="motilal_oswal", pct_unit="auto", skip_sheets=("Index", "INDEX"))
