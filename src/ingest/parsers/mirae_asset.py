"""Mirae Asset MF: one xlsx per scheme per month, single sheet 'MIIOF' (legacy code from
'India Opportunities Fund'; file slug 'miiof' with inconsistent '_'/'-' separators and
month spellings, SRC-3e). Inspected: all 12 months (Sep-2025..Aug-2026).
Row 1 = scheme name; row 5 = name + code 'MI002' + as-of datetime; row 7 = 'Monthly Portfolio
Statement as on August 31, 2026'; row 8 = header ('Name of the Instrument','ISIN',
'Industry ^/ Rating','Quantity','Market/Fair Value (Rs. in Lacs)','% to Net Assets','YTM').
Weights are FRACTIONS (0.0897). Month comes from the 'as on' line, not the file name.
"""
from src.ingest.portfolio_common import ParserConfig

CONFIG = ParserConfig(amc_slug="mirae_asset", pct_unit="fraction")
