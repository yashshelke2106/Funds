"""quant MF: one xlsx per month ('quant_Large_Cap_Fund_<date>.xlsx'), single sheet 'quant_Large_Cap_Fund'.
Inspected: all 12 months (Sep-2025..Aug-2026); several dated on the last business day (SRC-3f).
Row 1 = scheme name; row 3 = 'MONTHLY PORTFOLIO STATEMENT AS ON 31 Aug 2026'; row 7 = header ('SR','ISIN',
'NAME OF THE INSTRUMENT','RATING','INDUSTRY','QUANTITY','MARKET VALUE(Rs.in Lakhs)','% to NAV','YTM').
Weights PERCENT; 'Grand Total' = 100. quant runs a large futures book: a 'DERIVATIVES' block in the main
table ('(a) Index / Stock Futures') holds 15-30% of NAV in stock futures every month, plus Bank Nifty
futures in Dec-2025..Feb-2026 (short -15.1% of NAV in Feb-2026). Futures ARE included in Grand Total
and offset by a negative 'NCA-NET CURRENT ASSETS'. The ISIN column of futures holds exchange contract
codes ('TCS290926'), so futures map to stocks by name (expiry 'dd/mm/yyyy' stripped).
"""
from src.ingest.portfolio_common import ParserConfig

CONFIG = ParserConfig(amc_slug="quant", pct_unit="percent")
