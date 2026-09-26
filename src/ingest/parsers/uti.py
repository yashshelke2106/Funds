"""UTI MF: one workbook per month ('Sebi Exposure ...', Sep-2025 is .xlsm; sheet name varies:
Exposure/exposure/Sheet1/EXPOSURE/Sebi Exposure). EVERY scheme sits in ONE sheet, each block
between 'SCHEME CODE<nnn>STARTS' / 'SCHEME CODE<nnn>ENDS' in column 0; study fund = block 017
('SCHEME: UTI - Large Cap Fund'), found by title. Inspected: all 12 months (Sep-2025..Aug-2026).
Block layout: 'PROVISIONAL AND UNAUDITED PORTFOLIO DISCLOSURE AS OF 31/08/2026 (Market value in
Lacs)'; header ('NAME OF THE INSTRUMENT','RATING/INDUSTRY','QUANTITY','MARKET-VALUE','% TO NAV',
.., 'ISIN'); names prefixed 'EQ - '; weights in PERCENT; equity total 'TOTAL:  EQUITY AND EQUITY
RELATED'; NAV row 'TOTAL : UTI - Large Cap Fund' with NO % (unit checked on holdings, D-039).
Sep-Nov 2025: a 'FUTURES' table after the NAV row, under its own header, each row carrying the
underlying stock's ISIN. Aug-2026 file is a REVISED disclosure (SRC-3d).
"""
from src.ingest.portfolio_common import ParserConfig

CONFIG = ParserConfig(amc_slug="uti", pct_unit="percent", name_junk=("EQ - ",),
                      block_start=r"^SCHEME CODE\w+STARTS$", nav_row_is_scheme_total=True,
                      extra_derivative_labels=("futures",))
