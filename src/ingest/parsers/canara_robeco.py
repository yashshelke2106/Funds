"""Canara Robeco MF: one xlsx per scheme per month, single sheet 'LC'. Inspected: all 12 months
(Sep-2025..Aug-2026). Row 0 = scheme name; row 2 = 'Monthly Portfolio Statement as on <date>';
row 3 = header ('Name of the Instrument','ISIN','Industry / Rating','Quantity',
'Market/Fair Value (Rs. in Lacs)','% to Net Assets','Market Capitalization','Yield %').
Weights are PERCENT (9.45). Grand total row = 'Grand Total' (100).
"""
from src.ingest.portfolio_common import ParserConfig

CONFIG = ParserConfig(amc_slug="canara_robeco", pct_unit="percent")
