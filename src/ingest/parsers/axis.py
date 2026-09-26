"""Axis MF: one file per scheme per month, single sheet 'AXISEQF'. 7/12 months are .xlsx, 5/12
genuine legacy .xls (Sep-2025..Aug-2026 inspected; read_grid dispatches on bytes, D-034).
Row 0 = code + 'Axis Large Cap Fund'; row 2 = 'Monthly Portfolio Statement as on <date>';
row 3 = header ('Name of the Instrument','ISIN','Industry','Quantity',
'Market/Fair Value (Rs. in Lakhs)','% to Net Assets','YTM~','YTC^'). Col 0 = internal code.
Weights are FRACTIONS (0.0952). Futures (index and stock) sit in a 'Derivatives' block of the
main table in Dec-2025..Jul-2026. EXCEPTION Aug-2026: the main table has no derivatives block;
the NIFTY Sep-2026 future appears only in the notes ('Derivatives disclosure' table B) and in
note (5) total exposure Rs 26,592.87 lakh -> taken from there (D-036, user decision).
"""
from src.ingest.portfolio_common import ParserConfig

CONFIG = ParserConfig(amc_slug="axis", pct_unit="fraction", notes_futures_fallback=True)
