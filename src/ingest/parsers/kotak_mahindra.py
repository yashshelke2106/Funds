"""Kotak Mahindra MF: 'Consolidated Portfolio' download = one xlsx per month, sheet 'K30' (the
single-fund link is broken on the site, SRC-3b). 10 files keep the site's names 'K30 (n).xlsx';
Apr/Jul-2026 are prefixed 'YYYY-MM__'. Inspected: all 12 months (Sep-2025..Aug-2026).
Row 0 = 'Portfolio of Kotak Large Cap Fund as on 31-Aug-2026'; row 1 = header ('Name of Instrument'
[col A],'ISIN Code','Industry','Yield','Quantity','Market Value (Rs.in Lacs)','% to Net Assets'),
but instrument names sit in column C (D-040). Weights PERCENT; 'Grand Total' = 100.
Futures sit in the main table under a 'Futures' label (index futures named 'CNX NIFTY-SEP2026',
'CNX BANK INDEX-SEP2026'; stock futures carry the underlying's ISIN). Futures values are NOT in
the Grand Total (notional). A second equity block after the first 'Total' (e.g. GSPL Transmission,
listing pending) has its own 'Total'; both are summed for reconciliation.
"""
from src.ingest.portfolio_common import ParserConfig

CONFIG = ParserConfig(amc_slug="kotak_mahindra", pct_unit="percent", extra_derivative_labels=("futures",))
