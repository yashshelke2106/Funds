"""Nippon India MF: one AMC-wide workbook per month, ~100+ scheme sheets keyed by a
2-letter internal code (study fund = sheet 'EA'). Files are named '*.xls' but 10/12
are actually .xlsx (PK zip) mislabelled; 2/12 (Mar-2026, Nov-2025) are real legacy
BIFF .xls -- read_grid() dispatches on file bytes, not the extension.
Inspected: all 12 months (Sep-2025..Aug-2026), sheet 'EA'.
Row 0 = code + scheme name; row 1 = 'Monthly Portfolio Statement as on <date>'; row 3 = header
('ISIN','Name of the Instrument','Industry / Rating','Quantity',
 'Market/Fair Value\\n( Rs. in Lacs)','% to NAV','YIELD'). Weights are FRACTIONS (0.0865).
Equity block: 'Equity & Equity related' -> '(a) Listed...' holdings -> 'Subtotal' ->
'(b) UNLISTED' (NIL in all 12 months so far) -> 'Subtotal' -> 'Total'. Then 'Money Market
Instruments' (Triparty Repo), 'OTHERS' (Cash Margin - CCIL), 'Net Current Assets',
'GRAND TOTAL' (== 1.0). No derivative rows found in any of the 12 months (all say
"Total outstanding exposure in derivative instruments ... is Nil.").
"""
from src.ingest.portfolio_common import ParserConfig

CONFIG = ParserConfig(amc_slug="nippon_india", pct_unit="fraction")
