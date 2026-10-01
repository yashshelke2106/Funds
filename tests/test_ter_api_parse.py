"""Parser tests for AMFI TER API pages (D-049..D-052).

Fixtures in tests/fixtures/ter_api/ are verbatim pages from the live API (HDFC, mfId 9), fetched 2026-09-28/29:
  2024-09/cat_15  'HDFC Top 100 Fund', old field set, blank NSDL codes     2024-09/cat_74  empty
  2026-08/cat_15  'HDFC Large Cap Fund', new field set, NSDL codes         2026-08/cat_74  empty
  2024-09/cat_50/p002, 2026-08/cat_50/p002  index page with 'HDFC NIFTY 100 Index Fund' AND the Equal Weight fund
  2026-08/cat_101 'HDFC Nifty Auto Index Fund' (negative case)
Expected values are read off the raw JSON by hand. Negative tests alter a copy of a real row in memory; the
altered row never reaches the pipeline.
"""
import copy
import json
import shutil
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.ingest.ter import TerFormatError
from src.ingest.ter_api import INDEX_CATS, LARGE_CAP_CATS
from src.ingest.ter_api_parse import (build, compare_with_excel, index_names, load_month, match_active,
                                      match_index, row_format, rows_to_long)

FIX = Path(__file__).parent / "fixtures" / "ter_api"
HDFC_LC = "HDFC/O/E/LCF/96/10/0004"
HDFC_N100 = "HDFC/O/O/EIN/21/12/0081"


def rows(ym, cat, page=1):
    return json.loads((FIX / "mf_9" / ym / f"cat_{cat}" / f"p{page:03d}.json").read_text(encoding="utf-8"))["data"]


def test_row_format_old_and_new():
    assert row_format(rows("2024-09", 15)[0]) == "old"
    assert row_format(rows("2026-08", 15)[0]) == "new"
    r = copy.deepcopy(rows("2026-08", 15)[0])
    r["R_Surprise"] = "0.1"
    with pytest.raises(TerFormatError, match="unrecognised field set"):
        row_format(r)
    r = copy.deepcopy(rows("2026-08", 15)[0])
    del r["TER_Date"]
    with pytest.raises(TerFormatError, match="lacks"):
        row_format(r)


def test_old_format_values_hand_checked():
    df = rows_to_long(rows("2024-09", 15), "2024-09", "fx")
    assert df.scheme_name.unique().tolist() == ["HDFC Top 100 Fund"]
    assert len(df) == 60 and (df.nsdl_code == "").all() and (df.format == "old").all()
    d1 = df[df.ter_date == date(2024, 9, 1)].set_index("plan")
    # raw: R_BaseTER 1.4100, R_6A_B 0.0000, R_6A_C 0.0500, R_GST 0.1400, R_TER 1.6000; D_ 0.81/0/0.05/0.14/1.00
    assert d1.loc["regular", ["base", "addl_b", "addl_c", "levies", "total"]].tolist() == [1.41, 0.0, 0.05, 0.14, 1.60]
    assert d1.loc["direct", ["base", "addl_b", "addl_c", "levies", "total"]].tolist() == [0.81, 0.0, 0.05, 0.14, 1.00]
    assert d1[["brokerage", "txn"]].isna().all().all()


def test_new_format_values_hand_checked():
    df = rows_to_long(rows("2026-08", 15), "2026-08", "fx")
    assert df.scheme_name.unique().tolist() == ["HDFC Large Cap Fund"] and (df.nsdl_code == HDFC_LC).all()
    assert len(df) == 62 and (df.format == "new").all()
    d1 = df[df.ter_date == date(2026, 8, 1)].set_index("plan")
    # raw: R_BER 1.2900, R_BrokerageCost 0, R_TransactionCost 0.0100, R_StatutoryLevies 0.2600, R_TER 1.5600
    assert d1.loc["regular", ["base", "brokerage", "txn", "levies", "total"]].tolist() == [1.29, 0.0, 0.01, 0.26, 1.56]
    assert d1.loc["direct", ["base", "brokerage", "txn", "levies", "total"]].tolist() == [0.83, 0.0, 0.01, 0.18, 1.02]
    assert d1[["addl_b", "addl_c"]].isna().all().all()


def test_components_must_add_up():
    r = copy.deepcopy(rows("2026-08", 15)[0])
    r["R_TER"] = "1.6000"                      # parts still add to 1.56
    with pytest.raises(TerFormatError, match="components"):
        rows_to_long([r], "2026-08", "fx")


def test_date_outside_month_and_month_mismatch():
    r = copy.deepcopy(rows("2026-08", 15)[0])
    r["TER_Date"] = "2026-09-01T00:00:00.000Z"
    with pytest.raises(TerFormatError, match="outside"):
        rows_to_long([r], "2026-08", "fx")
    with pytest.raises(TerFormatError, match="row Month"):
        rows_to_long(rows("2026-08", 15), "2026-07", "fx")


def test_plan_without_total_is_dropped_not_zero():
    r = copy.deepcopy(rows("2026-08", 15)[0])
    for k in [k for k in r if k.startswith("R_")]:
        r[k] = None
    df = rows_to_long([r], "2026-08", "fx")
    assert df.plan.tolist() == ["direct"]


def test_load_month_reads_both_large_cap_ids():
    df = load_month(FIX, 9, "2024-09", LARGE_CAP_CATS)
    assert len(df) == 60 and df.source_file.str.startswith("api/mf_9/2024-09/cat_15").all()


def test_load_month_rejects_incomplete_or_missing_fetch(tmp_path):
    shutil.copytree(FIX / "mf_9" / "2024-09" / "cat_15", tmp_path / "mf_9" / "2024-09" / "cat_15")
    with pytest.raises(TerFormatError, match="no pages"):        # cat_74 was never fetched
        load_month(tmp_path, 9, "2024-09", LARGE_CAP_CATS)
    shutil.copytree(FIX / "mf_9" / "2024-09" / "cat_74", tmp_path / "mf_9" / "2024-09" / "cat_74")
    p = tmp_path / "mf_9" / "2024-09" / "cat_15" / "p001.json"
    o = json.loads(p.read_text(encoding="utf-8"))
    o["meta"]["pageCount"], o["meta"]["total"] = 2, 130   # server said 2 pages, only 1 on disk
    p.write_text(json.dumps(o), encoding="utf-8")
    with pytest.raises(TerFormatError, match="incomplete fetch"):
        load_month(tmp_path, 9, "2024-09", LARGE_CAP_CATS)


def test_match_active_rename_proof_and_code_checked():
    old = rows_to_long(rows("2024-09", 15), "2024-09", "fx")
    new = rows_to_long(rows("2026-08", 15), "2026-08", "fx")
    assert match_active(old, "hdfc_lc", HDFC_LC, "t").fund_id.eq("hdfc_lc").all()   # blank codes pass
    assert len(match_active(new, "hdfc_lc", HDFC_LC, "t")) == 62
    with pytest.raises(TerFormatError, match="ter_scheme_map"):
        match_active(new, "hdfc_lc", "HDFC/O/E/LCF/00/00/9999", "t")


def test_two_large_cap_schemes_on_a_day_stop():
    df = rows_to_long(rows("2026-08", 15), "2026-08", "fx")
    twin = df.assign(scheme_name="Another Large Cap Fund", nsdl_code="")
    with pytest.raises(TerFormatError, match="SEBI allows one"):
        match_active(pd.concat([df, twin]), "hdfc_lc", HDFC_LC, "t")


def test_duplicate_row_for_same_day_and_plan_stops():
    df = rows_to_long(rows("2026-08", 15), "2026-08", "fx")
    with pytest.raises(TerFormatError, match="expected exactly one"):
        match_active(pd.concat([df, df.iloc[:1]]), "hdfc_lc", HDFC_LC, "t")


def test_index_match_picks_nifty100_not_equal_weight_or_auto():
    old = rows_to_long(rows("2024-09", 50, page=2), "2024-09", "fx")
    new = pd.concat([rows_to_long(rows("2026-08", 50, page=2), "2026-08", "fx"),
                     rows_to_long(rows("2026-08", 101), "2026-08", "fx")])
    code, names = index_names(pd.concat([old, new]), "HDFC NIFTY 100 Index Fund", None)
    assert code == HDFC_N100 and names == {"hdfc nifty 100 index fund"}
    for part in (old, new):
        hit = match_index(part, "hdfc_n100", code, names, "t")
        assert hit.scheme_name.unique().tolist() == ["HDFC NIFTY 100 Index Fund"]
    assert "Equal Weight" in " ".join(old.scheme_name.unique())    # it was there, and was not picked


def test_index_name_with_a_foreign_code_stops():
    new = rows_to_long(rows("2026-08", 50, page=2), "2026-08", "fx")
    with pytest.raises(TerFormatError, match="has code"):
        match_index(new, "hdfc_n100", "HDFC/O/O/EIN/00/00/0000", {"hdfc nifty 100 index fund"}, "t")


def _mini(first_nav="2024-09-01"):
    sm = pd.DataFrame({"fund_id": ["hdfc_lc"], "role": ["active"], "amc": ["HDFC Mutual Fund"],
                       "scheme_name": ["HDFC Large Cap Fund"]})
    uni = pd.DataFrame({"fund_id": ["hdfc_lc"], "direct_first_nav": [first_nav], "regular_first_nav": [first_nav]})
    cm = pd.DataFrame({"nsdl_code": [HDFC_LC], "fund_id": ["hdfc_lc"]})
    return sm, uni, cm


def test_build_over_real_months():
    sm, uni, cm = _mini()
    out = build(FIX, sm, uni, cm, {"HDFC Mutual Fund": 9}, ["2024-09", "2026-08"])
    assert out.groupby(pd.to_datetime(out.ter_date).dt.strftime("%Y-%m")).size().to_dict() == {"2024-09": 60, "2026-08": 62}


def test_build_stops_on_a_gap_after_first_nav(tmp_path):
    for ym in ("2024-09",):
        for c in LARGE_CAP_CATS:
            shutil.copytree(FIX / "mf_9" / ym / f"cat_{c}", tmp_path / "mf_9" / ym / f"cat_{c}")
    # 2024-10 fetched but empty for both Large Cap IDs: copy the real empty cat_74 page, relabelled month
    for c in LARGE_CAP_CATS:
        d = tmp_path / "mf_9" / "2024-10" / f"cat_{c}"
        d.mkdir(parents=True)
        shutil.copy(FIX / "mf_9" / "2024-09" / "cat_74" / "p001.json", d / "p001.json")
    sm, uni, cm = _mini()
    with pytest.raises(TerFormatError, match=r"hdfc_lc regular 2024-10"):
        build(tmp_path, sm, uni, cm, {"HDFC Mutual Fund": 9}, ["2024-09", "2024-10"])
    sm, uni, cm = _mini(first_nav="2024-11-05")           # not launched yet in Sep/Oct: no error
    build(tmp_path, sm, uni, cm, {"HDFC Mutual Fund": 9}, ["2024-09", "2024-10"])


def test_compare_with_excel_exact_and_catches_differences():
    api = rows_to_long(rows("2026-08", 15), "2026-08", "api").assign(fund_id="hdfc_lc")
    xl = api.drop(columns=["source_file"]).assign(source_file="x.xlsx")
    assert compare_with_excel(api, xl)["rows_compared"] == 62
    bad = xl.copy()
    bad.loc[bad.index[0], "levies"] += 0.01
    with pytest.raises(TerFormatError, match="disagree on levies"):
        compare_with_excel(api, bad)
    with pytest.raises(TerFormatError, match="missing from the API"):
        compare_with_excel(api.iloc[1:], xl)


def _exc(code, month="2026-08"):
    return pd.DataFrame({"fund_id": ["hdfc_lc"], "month": [month], "code": [code], "reason": ["test"]})


def test_listed_code_exception_is_tolerated_and_others_still_stop():
    new = rows_to_long(rows("2026-08", 15), "2026-08", "fx")
    odd = new.copy()
    odd.loc[odd.ter_date == date(2026, 8, 5), "nsdl_code"] = "10769358"     # a stray value on one day
    assert len(match_active(odd, "hdfc_lc", HDFC_LC, "t", frozenset({"10769358"}))) == 62
    with pytest.raises(TerFormatError, match="ter_scheme_map"):
        match_active(odd, "hdfc_lc", HDFC_LC, "t")                           # not listed -> stop
    with pytest.raises(TerFormatError, match="ter_scheme_map"):
        match_active(odd, "hdfc_lc", HDFC_LC, "t", frozenset({"99999999"}))  # a different listed value -> stop


def test_stale_code_exception_stops_the_build():
    sm, uni, cm = _mini()
    with pytest.raises(TerFormatError, match="match no row"):
        build(FIX, sm, uni, cm, {"HDFC Mutual Fund": 9}, ["2024-09", "2026-08"], _exc("10769358"))


def test_code_exception_file_needs_a_reason(tmp_path):
    from src.ingest.ter_api_parse import load_code_exceptions
    p = tmp_path / "x.csv"
    p.write_text("fund_id,month,code,reason\nhdfc_lc,2026-08,1,\n", encoding="utf-8")
    with pytest.raises(TerFormatError, match="reason"):
        load_code_exceptions(p)
