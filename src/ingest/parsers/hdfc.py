"""HDFC MF: one xlsx per scheme ('Monthly HDFC Large Cap Fund - 31 August 2026.xlsx', sheet HDFCT2).
Rows 1-2: title / 'Portfolio as on 31-Aug-2026' repeated across merged cells; row 5 = header
with ISIN in col B and name in col D; col A holds '|' top-ten markers.
Weights are PERCENT (10.05). '£' after a name marks the sponsor company and is stripped.
"""
from src.ingest.portfolio_common import ParserConfig

CONFIG = ParserConfig(amc_slug="hdfc", pct_unit="percent", name_junk=("£",))
