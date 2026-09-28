"""Tata MF: one AMC-wide workbook per month (~70 sheets by scheme code); study sheet 'TTOFE', found by
title 'Tata large Cap Fund' (sheet 'TEOF' is Large & Mid Cap). Inspected: all 12 months (Sep-2025..Aug-2026).
Row 9 = 'Portfolio as on 31-08-26' - numeric day-first dates in four spellings (31/10/25, 28-02-26,
30-04-2026, 30/06/26); row 11 = header ('NAME OF THE INSTRUMENT','YIELD ( IN % )','INDUSTRY','ISIN CODE',
'QUANTITY','MKT VAL(Rs. Lacs)','% to NAV'). Weights PERCENT. Equity total 'EQUITY & EQUITY RELATED TOTAL';
NAV row 'NET ASSETS' (= 100). Hedging futures are listed INSIDE the equity block with a '^' suffix
and negative quantity (legend: '^ Hedging positions through futures'; e.g. Bajaj Finance Apr-2026, -1.45%);
they are parsed as stock futures on the row's own ISIN (D-045). Notes tables B-D are empty every month.
Tata LC is in the SENSITIVITY group, not the headline set (D-032).
"""
from src.ingest.portfolio_common import ParserConfig

CONFIG = ParserConfig(amc_slug="tata", pct_unit="percent", extra_nav_labels=("net assets",), hedge_marker="^")
