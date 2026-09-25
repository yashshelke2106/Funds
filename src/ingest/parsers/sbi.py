"""SBI MF: CSV per scheme, cp1252-encoded, padded to 256 columns.
Inspected: 'sbi-large-cap-fund-monthly-portfolio---august-2026(SBLUECHIP).csv'.
Row 3 'SCHEME NAME :' | name; row 4 'PORTFOLIO STATEMENT AS ON :' | 'August 31, 2026'; row 6 header.
Numbers are text with thousands commas; negatives in brackets '(7,208.31)'. Weights are
PERCENT of AUM. Futures follow GRAND TOTAL under 'DERIVATIVES' with their own header row
(name, Long / Short, industry, quantity, value); names carry the expiry ('... 29.09.2026').
"""
from src.ingest.portfolio_common import ParserConfig

CONFIG = ParserConfig(amc_slug="sbi", pct_unit="percent")
