"""DSP MF: one AMC-wide equity workbook per month ('DSP Equity [FOF] ISIN Portfolio as on <date>',
~64 sheets named by scheme, e.g. 'Large Cap'; found by title 'DSP Large Cap Fund'). Files were
flattened from per-month download folders (D-033). Inspected: all 12 months (Sep-2025..Aug-2026).
Row 0 = scheme name; row 1 = 'Portfolio as on August 31, 2026'; row 3 = header ('Sr. No.',
'Name of Instrument','ISIN','Rating/Industry','Quantity','Market value (Rs. In lakhs)',
'% to Net Assets','Maturity Date','Put/Call Option','YTM (%)'). Weights are FRACTIONS.
Derivatives sit in a 'DERIVATIVES' block of the main table; the Rating/Industry column names the
instrument type ('Stock Futures', 'Index Futures', 'Index Options') - options are kept as
derivative_kind='option' and never allocated as futures (D-041).
"""
from src.ingest.portfolio_common import ParserConfig

CONFIG = ParserConfig(amc_slug="dsp", pct_unit="fraction")
