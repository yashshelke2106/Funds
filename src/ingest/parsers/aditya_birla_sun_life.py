"""Aditya Birla Sun Life MF: one AMC-wide workbook per month (~100+ scheme sheets); study fund
is sheet 'BSLFEF' (found by title, never by sheet code: 'ABSLBCF' is the Business Cycle Fund).
11/12 months are legacy BIFF .xls, Jun-2026 is .xlsx (read_grid dispatches on bytes, D-034).
Inspected: all 12 months (Sep-2025..Aug-2026). Row 0 = code + scheme name (col 2); row 2 =
'Portfolio Statement as on <date>'; row 3 = header ('Name of the Instrument / Issuer','ISIN',
'Industry^ / Rating','Quantity','Market value (Rs. in Lakhs)','% to AUM','YTM %'). Col 1 holds an
internal security code. Weights are FRACTIONS of AUM. Grand total row = 'GRAND TOTAL (AUM)'.
"""
from src.ingest.portfolio_common import ParserConfig

CONFIG = ParserConfig(amc_slug="aditya_birla_sun_life", pct_unit="fraction")
