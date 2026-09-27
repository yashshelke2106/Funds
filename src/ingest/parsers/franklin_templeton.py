"""Franklin Templeton MF: one AMC-wide workbook per month ('Monthly-Portfolio-ISIN-<date>.xlsx',
~40 sheets by scheme code; study sheet 'FILCF', found by title 'Franklin India Large Cap Fund
(Formerly known as Franklin India Bluechip Fund)'). Inspected: all 12 months (Sep-2025..Aug-2026);
some months are dated on the last business day (e.g. 27-Feb-2026).
Row 0 = scheme name; row 2 = 'Portfolio Statement as on February 27, 2026'; row 3 = header
('ISIN Number','Name of the Instrument','Industry Classification / Rating','Quantity',
'Market Value (including accrued interest, if any) (Rs. in Lakhs)','% to Net Assets','YTM').
Weights PERCENT. NAV row is 'Net Assets' (= 100), not 'Grand Total' (D-042). Equity has a
'Foreign Equity Securities' block (e.g. Cognizant, US ISIN) - real equity, outside the benchmark.
"""
from src.ingest.portfolio_common import ParserConfig

CONFIG = ParserConfig(amc_slug="franklin_templeton", pct_unit="percent", extra_nav_labels=("net assets",))
