"""Parser + universe tests on verbatim excerpts of real AMFI / mfapi files (D-008)."""
import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.ingest.amfi import FormatChangedError, normalise_category, parse_amfi_text
from src.ingest.nav import SourceError, parse_mfapi
from src.ingest.universe import build_scheme_map, is_growth, survivorship_events

FX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def navall():
    return parse_amfi_text((FX / "navall_excerpt.txt").read_text(encoding="utf-8"), "navall")


@pytest.fixture(scope="module")
def history():
    return parse_amfi_text((FX / "history_excerpt_2024-09-02.txt").read_text(encoding="utf-8"), "history")


# ---- AMFI parsing ---------------------------------------------------------
def test_category_spellings_normalise_to_one():
    a = normalise_category("Open Ended Schemes(Equity Scheme - Large Cap Fund)")
    b = normalise_category("Open Ended Schemes(Equity Schemes - Large Cap Fund)")
    c = normalise_category("Open Ended Schemes ( Equity Schemes - Large Cap Fund )")
    assert a == b == c == "Open Ended Schemes | Equity Scheme - Large Cap Fund"


def test_navall_parses_every_row(navall):
    assert len(navall) == 22  # 4 ABSL + 2 Samco + 4 Axis LC + 4 Multicap + 4 Nifty 50 + 4 Nifty 100
    r = navall.set_index("scheme_code").loc[119528]
    assert r.amc == "Aditya Birla Sun Life Mutual Fund"
    assert r.isin_growth_or_payout == "INF209K01YY7"
    assert r.isin_reinvest is None
    assert r.nav == pytest.approx(558.33)
    assert r.nav_date == date(2026, 9, 24)


def test_history_parses_with_different_column_order(history):
    r = history.set_index("scheme_code").loc[120465]
    assert r.isin_growth_or_payout == "INF846K01DP8"
    assert r.plan == "Direct Plan"
    assert r.nav == pytest.approx(70.07)
    assert r.nav_date == date(2024, 9, 2)


def test_header_change_stops_parsing():
    text = (FX / "navall_excerpt.txt").read_text(encoding="utf-8")
    with pytest.raises(FormatChangedError):
        parse_amfi_text(text.replace("Scheme Code;", "Code;", 1), "navall")


def test_wrong_kind_header_rejected():
    text = (FX / "navall_excerpt.txt").read_text(encoding="utf-8")
    with pytest.raises(FormatChangedError):
        parse_amfi_text(text, "history")


# ---- Universe -------------------------------------------------------------
@pytest.mark.parametrize("opt,expected", [
    ("GROWTH", True), ("Growth Option", True), ("Direct Growth", True),
    ("IDCW", False), ("Bonus Option", False), ("Institutional Plan Bonus Option", False),
    ("", False), (None, False),
])
def test_is_growth(opt, expected):
    assert is_growth(opt) is expected


def test_scheme_map_pairs_and_filters(navall):
    sm = build_scheme_map(navall, "navall_excerpt.txt").set_index("fund_id")
    # Large cap: ABSL, Axis, Samco; index: Axis Nifty 100 only (Nifty 50 and Multicap excluded)
    assert sorted(sm.index) == ["aditya_birla_sun_life_lc", "axis_lc", "axis_n100", "samco_lc"]
    assert sm.loc["aditya_birla_sun_life_lc", ["direct_code", "regular_code"]].tolist() == [119528, 103174]
    assert sm.loc["axis_lc", ["direct_isin", "regular_isin"]].tolist() == ["INF846K01DP8", "INF846K01164"]
    assert sm.loc["axis_n100", "role"] == "index"
    assert sm.loc["axis_n100", ["direct_code", "regular_code"]].tolist() == [147666, 147665]


def test_scheme_map_refuses_unpaired_plan(navall):
    broken = navall[navall.scheme_code != 103174]  # drop ABSL regular growth
    with pytest.raises(FormatChangedError, match="Aditya Birla"):
        build_scheme_map(broken, "x")


def test_survivorship_flags_new_launch_by_code(history, navall):
    ev = survivorship_events(history, navall).set_index("scheme_code")
    assert ev.loc[153239, "event"] == "not_large_cap_at_window_start"   # Samco, launched later
    assert ev.loc[119528, "event"] == "present_at_start_and_now"
    assert ev.loc[119528, "name_at_start"] != ev.loc[119528, "name_now"]  # format difference only
    assert "closed_merged_or_recategorised" not in set(ev["event"])


def test_survivorship_detects_disappearance(history, navall):
    now_without_axis = navall[~navall.scheme_code.isin([120465, 112277])]
    ev = survivorship_events(history, now_without_axis).set_index("scheme_code")
    assert ev.loc[120465, "event"] == "closed_merged_or_recategorised"


# ---- mfapi ----------------------------------------------------------------
def test_mfapi_parse_sorted_ascending():
    payload = json.loads((FX / "mfapi_118825_excerpt.json").read_text(encoding="utf-8"))
    meta, df = parse_mfapi(payload, 118825)
    assert meta["isin_growth"] == "INF769K01AX2"
    assert len(df) == 10
    assert df.nav_date.is_monotonic_increasing
    assert df.iloc[0].nav_date == date(2013, 1, 2) and df.iloc[0].nav == pytest.approx(18.972)
    assert df.iloc[-1].nav_date == date(2026, 9, 24) and df.iloc[-1].nav == pytest.approx(123.109)


def test_mfapi_wrong_code_rejected():
    payload = json.loads((FX / "mfapi_118825_excerpt.json").read_text(encoding="utf-8"))
    with pytest.raises(SourceError):
        parse_mfapi(payload, 999999)


def test_mfapi_bad_status_rejected():
    payload = json.loads((FX / "mfapi_118825_excerpt.json").read_text(encoding="utf-8"))
    payload["status"] = "FAIL"
    with pytest.raises(SourceError):
        parse_mfapi(payload, 118825)


def test_block_without_amc_header_parses_with_null_amc():
    # verbatim real block: Franklin segregated portfolio listed with no AMC header line
    df = parse_amfi_text((FX / "navall_no_amc_excerpt.txt").read_text(encoding="utf-8"), "navall")
    assert df["amc"].isna().all()
    assert df.iloc[0]["nav_date"] == date(2021, 12, 12)


def test_stale_nav_in_selected_scheme_stops_universe(navall):
    stale = navall.copy()
    stale.loc[stale.scheme_code == 120465, "nav_date"] = date(2026, 8, 1)
    with pytest.raises(FormatChangedError, match="stale NAV"):
        build_scheme_map(stale, "x")


# ---- D-022: blank Plan/Option in NAVAll (real Motilal Oswal rows, verbatim) ----------
def test_blank_plan_resolved_from_history_name():
    now = parse_amfi_text((FX / "navall_motilal_excerpt.txt").read_text(encoding="utf-8"), "navall")
    then = parse_amfi_text((FX / "history_motilal_excerpt.txt").read_text(encoding="utf-8"), "history")
    assert now.loc[now.scheme_code == 152354, "plan"].iloc[0] == ""        # the defect in the source
    sm = build_scheme_map(now, "x", then).set_index("fund_id")
    assert "motilal_oswal_lc" in sm.index                                  # previously dropped silently
    assert sm.loc["motilal_oswal_lc", ["direct_code", "regular_code"]].tolist() == [152354, 152352]
    assert "motilal_oswal_lm" not in sm.index                              # Large & Mid Cap stays out


def test_blank_plan_without_history_is_not_guessed():
    now = parse_amfi_text((FX / "navall_motilal_excerpt.txt").read_text(encoding="utf-8"), "navall")
    sm = build_scheme_map(now, "x", None)
    assert "motilal_oswal_lc" not in set(sm.fund_id)


def test_survivorship_counts_blank_option_growth_rows():
    now = parse_amfi_text((FX / "navall_motilal_excerpt.txt").read_text(encoding="utf-8"), "navall")
    then = parse_amfi_text((FX / "history_motilal_excerpt.txt").read_text(encoding="utf-8"), "history")
    ev = survivorship_events(then, now).set_index("scheme_code")
    assert ev.loc[152354, "event"] == "present_at_start_and_now"


def test_navall_snapshot_uses_pinned_file_not_newest(tmp_path):
    """D-046: a newer NAVAll on disk must not be picked up by the build."""
    from src.ingest.amfi import navall_snapshot
    (tmp_path / "NAVAll_2026-09-24.txt").write_text("x", encoding="utf-8")
    (tmp_path / "NAVAll_2026-09-27.txt").write_text("y", encoding="utf-8")
    assert navall_snapshot(date(2026, 9, 24), tmp_path).name == "NAVAll_2026-09-24.txt"


def test_navall_snapshot_missing_stops(tmp_path):
    from src.ingest.amfi import navall_snapshot
    (tmp_path / "NAVAll_2026-09-27.txt").write_text("y", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="NAVALL_SNAPSHOT_DATE"):
        navall_snapshot(date(2026, 9, 24), tmp_path)
