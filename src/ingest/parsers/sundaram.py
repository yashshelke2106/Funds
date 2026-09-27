"""Sundaram MF: one 'Equity & Fund of Funds' workbook per month (file names are opaque
'monthlyportfolio_<timestamp>.xlsx'; the debt-only workbook is NOT used, SRC-3a). Sheets by scheme
code; study fund = sheet 'SUNBCF', found by title 'Sundaram Large Cap Fund'. Inspected: all 12
months (Sep-2025..Aug-2026). Row 2 = 'Monthly Portfolio Statement for the month ended 31 December
2025'; row 3 = header ('SL No','ISIN Code','Name of the instrument','Rating / Industry','Quantity',
'Mkt Value Rs. in Lacs','% of Net Asset','YTM (%)'). Weights FRACTIONS; 'Grand Total' = 1.
Sections are enumerated 'A) Equity & Equity Related', 'B) Debt Instruments'... (D-042).
Derivatives are listed as 'f) Derivative' INSIDE the equity block (empty in all 12 months); the
label opens a derivatives section so a future position there can never be counted as equity.
"""
from src.ingest.portfolio_common import ParserConfig

CONFIG = ParserConfig(amc_slug="sundaram", pct_unit="fraction", extra_derivative_labels=("f) derivative",))
