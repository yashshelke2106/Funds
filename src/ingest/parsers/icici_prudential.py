"""ICICI Prudential MF: xlsx with a scheme sheet ('BLUECHIP') and a 'Derivative' annexure.
Inspected: 'ICICI Prudential Large Cap Fund.xlsx' (Aug-2026). Row 3 'Portfolio as on Aug 31,2026';
row 4 header (name col B, ISIN col C). Weights are FRACTIONS. '^' marks < 0.01%.
The equity total sits on the 'Equity & Equity Related Instruments' header row.
Stock/index futures are listed in-sheet under 'Details of Stock Future / Index Future',
signed (short = negative quantity and value); '$$' marks derivatives and is stripped.
The 'Derivative' annexure is SKIPPED: in the Aug-2026 file it labels these positions with
scheme code 'FOCUS' and carries a stale 'as on March 31, 2026' line (DECISIONS D-019).
"""
from src.ingest.portfolio_common import ParserConfig

CONFIG = ParserConfig(amc_slug="icici_prudential", pct_unit="fraction",
                      skip_sheets=("Derivative",), name_junk=("$$", "**"))
