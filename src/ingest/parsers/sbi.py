"""SBI MF: two layouts in the window (D-046).
(1) Aug-2026: CSV per scheme, cp1252-encoded, padded to 256 columns.
Inspected: 'sbi-large-cap-fund-monthly-portfolio---august-2026(SBLUECHIP).csv'.
Row 3 'SCHEME NAME :' | name; row 4 'PORTFOLIO STATEMENT AS ON :' | 'August 31, 2026'; row 6 header.
Numbers are text with thousands commas; negatives in brackets '(7,208.31)'. Weights are
PERCENT of AUM. Futures follow GRAND TOTAL under 'DERIVATIVES' with their own header row
(name, Long / Short, industry, quantity, value); names carry the expiry ('... 29.09.2026').
(2) Sep-2025..Jul-2026: 'All-Schemes-Monthly-Portfolio' xlsx, ~125 sheets by scheme code; study sheet
'SBLUECHIP' (title 'SBI Large Cap Fund'). Same columns as the CSV; the as-of date is an Excel DATE cell
next to 'PORTFOLIO STATEMENT AS ON :'; GRAND TOTAL is 'GRAND TOTAL (AUM)'. Futures expiries are written
'28-OCT-25'. Sep-2025 lists two NIFTY call options INSIDE the equity block, identified by their NSE
contract code ('OPTIDXNIFTY28-OCT-2025CE24700') in the ISIN column.
"""
from src.ingest.portfolio_common import ParserConfig

CONFIG = ParserConfig(amc_slug="sbi", pct_unit="percent")
