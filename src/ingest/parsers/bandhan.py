"""Bandhan MF: one xlsx per scheme, sheet named by internal code (IDF016, IDF278).
Inspected: 'Bandhan Large Cap Fund 31 August 2026.xlsx', 'Bandhan Nifty 100 Index Fund 31 August 2026.xlsx'.
Row 1 = code + 'Portfolio Statement as on August 31,2026'; row 2 = scheme name; row 4 = header.
Col A holds an internal security code. Weights are FRACTIONS (0.0885). '$' marks < 0.01%.
"""
from src.ingest.portfolio_common import ParserConfig

CONFIG = ParserConfig(amc_slug="bandhan", pct_unit="fraction")
