"""Single source of truth for paths, study window and source URLs.

Every date that defines the study lives here. Change it here, rerun, and every
downstream artefact is rebuilt. See DECISIONS.md D-003 / D-004 for rationale.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DATA = ROOT / "data"
RAW = DATA / "raw"
RAW_AMFI = RAW / "amfi"
RAW_NAV = RAW / "nav"
RAW_PORTFOLIOS = RAW / "portfolios"
RAW_TER = RAW / "ter"
RAW_BENCHMARK = RAW / "benchmark"
REFERENCE = DATA / "reference"
INTERIM = DATA / "interim"
QUALITY = DATA / "quality"
DOCS = ROOT / "docs"

# ---- Study window (D-003) --------------------------------------------------
# Holdings window: 24 complete calendar months of portfolio disclosures.
WINDOW_START = date(2024, 9, 1)
WINDOW_END = date(2026, 8, 31)
# Portfolio disclosures are ingested only for the last 12 months (D-011).
# NAV-based metrics (TE, returns, IR) still use the full 24-month window.
HOLDINGS_START = date(2025, 9, 1)
# NAV history starts 12 months earlier so rolling-12m tracking error is
# defined for every month of the holdings window (D-004).
NAV_START = date(2023, 9, 1)
# First trading day on/after WINDOW_START used for the survivorship snapshot.
SURVIVORSHIP_SNAPSHOT_DATE = date(2024, 9, 2)
# Pinned AMFI NAVAll snapshot (D-046). The universe and the mfapi-vs-AMFI cross-check read
# data/raw/amfi/NAVAll_<this date>.txt, never "whatever was downloaded last": the cached mfapi
# JSON is frozen (nav step never refetches), so an unpinned newer NAVAll is guaranteed to fail
# the cross-check. To roll the data forward, refetch mfapi AND change this date together.
NAVALL_SNAPSHOT_DATE = date(2026, 9, 24)

# ---- Sources ---------------------------------------------------------------
AMFI_NAVALL_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"
AMFI_HISTORY_URL = "https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx?frmdt={d}"
MFAPI_URL = "https://api.mfapi.in/mf/{code}"
# AMFI TER JSON API (D-049): the endpoint behind amfiindia.com/ter-of-mf-schemes.
AMFI_TER_API_URL = "https://www.amfiindia.com/api/populate-te-rdata-revised"
AMFI_MF_LIST_URL = "https://www.amfiindia.com/api/populate-mf"
RAW_TER_API = RAW_TER / "api"
TER_API_SLEEP_S = 1.5   # pause after every call; backoff between retries is 1.5 x 2^attempt
TER_API_RETRIES = 5
# Seen 2026-09-29: after a few hundred calls the server stops answering (no body at all, nothing in
# _rejected/), rather than returning junk. A normal reply takes ~2 s, so a 20 s timeout detects a stall
# without the 60 s-per-attempt cost of the generic HTTP_TIMEOUT_S; after a request fails every retry,
# the fetch cools down so the server's limit can reset before the next request.
TER_API_TIMEOUT_S = 20
TER_API_COOLDOWN_S = 180

HTTP_TIMEOUT_S = 60
HTTP_RETRIES = 3
HTTP_SLEEP_S = 0.5  # politeness delay between mfapi calls

# ---- Quality thresholds (project brief) ------------------------------------
NAV_MAX_GAP_WEEKDAYS = 5
NAV_MAX_ABS_DAILY_MOVE = 0.10


def ensure_dirs() -> None:
    for p in (RAW_AMFI, RAW_NAV, RAW_PORTFOLIOS, RAW_TER, RAW_BENCHMARK,
              REFERENCE, INTERIM, QUALITY):
        p.mkdir(parents=True, exist_ok=True)
