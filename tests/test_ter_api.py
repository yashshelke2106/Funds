"""Fetch-layer tests for the AMFI TER JSON API (D-049).

The HTTP responses below are PROTOCOL STUBS: pagination envelopes whose rows are empty objects.
They carry no fund, TER or date values and never reach the pipeline; they exist only to exercise
retry, validation, pagination, caching and resume. Parser tests use verbatim excerpts of real
responses (tests/fixtures), like every other parser in this project.
"""
import json

import pytest
import requests

from src.ingest.ter_api import TerApiError, fetch_amc_month, fetch_mf_list, month_param, scan_categories


class Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, params=None, timeout=None):
        self.calls.append(dict(params or {}))
        if not self.responses:
            raise AssertionError(f"unexpected request: {params}")
        return self.responses.pop(0)


def envelope(page, page_count, total, n_rows):
    # Shape observed from the server: {'data': [...], 'meta': {pagination}}.
    return Resp(json.dumps({"data": [{}] * n_rows,
                            "meta": {"page": page, "pageSize": 100, "total": total, "pageCount": page_count}}))


FAST = dict(sleep=0, tries=3)


def test_month_param():
    assert month_param("2024-09") == "09-2024"
    assert month_param("2026-12") == "12-2026"
    for bad in ["2024-9", "09-2024", "2024-13", "2024-00", "202409"]:
        with pytest.raises(ValueError):
            month_param(bad)


def test_request_parameters(tmp_path):
    s = FakeSession([envelope(1, 1, 3, 3)])
    fetch_amc_month(9, "2024-09", raw_dir=tmp_path, session=s, **FAST)
    assert s.calls == [{"MF_ID": "9", "Month": "09-2024", "strCat": "-1", "strType": "1",
                        "pageSize": "100", "page": "1"}]


def test_malformed_body_is_retried_and_never_cached(tmp_path):
    s = FakeSession([Resp("<html>throttled</html>"), Resp("{}"), envelope(1, 1, 2, 2)])
    pages = fetch_amc_month(9, "2024-09", raw_dir=tmp_path, session=s, **FAST)
    assert len(s.calls) == 3 and len(pages) == 1
    cached = list((tmp_path / "mf_9" / "2024-09" / "cat_-1").iterdir())
    assert [p.name for p in cached] == ["p001.json"]
    assert json.loads(cached[0].read_text(encoding="utf-8"))["meta"]["total"] == 2


def test_persistent_failure_raises_and_leaves_no_file(tmp_path):
    s = FakeSession([Resp("not json")] * 3)
    with pytest.raises(TerApiError, match="failed after 3 tries"):
        fetch_amc_month(9, "2024-09", raw_dir=tmp_path, session=s, **FAST)
    d = tmp_path / "mf_9" / "2024-09" / "cat_-1"
    assert not d.exists() or not any(d.iterdir())


def test_http_error_is_retried(tmp_path):
    s = FakeSession([Resp("", status=503), envelope(1, 1, 1, 1)])
    assert len(fetch_amc_month(9, "2024-09", raw_dir=tmp_path, session=s, **FAST)) == 1


def test_all_pages_fetched_then_resumed_from_cache(tmp_path):
    s = FakeSession([envelope(1, 3, 250, 100), envelope(2, 3, 250, 100), envelope(3, 3, 250, 50)])
    assert len(fetch_amc_month(9, "2024-09", raw_dir=tmp_path, session=s, **FAST)) == 3
    assert [c["page"] for c in s.calls] == ["1", "2", "3"]
    again = FakeSession([])  # any request would fail the test
    assert len(fetch_amc_month(9, "2024-09", raw_dir=tmp_path, session=again, **FAST)) == 3


def test_interrupted_run_resumes_at_missing_page(tmp_path):
    s = FakeSession([envelope(1, 2, 150, 100), Resp("x"), Resp("x"), Resp("x")])
    with pytest.raises(TerApiError):
        fetch_amc_month(9, "2024-09", raw_dir=tmp_path, session=s, **FAST)
    s2 = FakeSession([envelope(2, 2, 150, 50)])
    assert len(fetch_amc_month(9, "2024-09", raw_dir=tmp_path, session=s2, **FAST)) == 2
    assert [c["page"] for c in s2.calls] == ["2"]


def test_row_total_mismatch_is_strict(tmp_path):
    s = FakeSession([envelope(1, 2, 150, 100), envelope(2, 2, 150, 40)])
    with pytest.raises(TerApiError, match="140 rows across 2 page"):
        fetch_amc_month(9, "2024-09", raw_dir=tmp_path, session=s, **FAST)


def test_row_total_mismatch_only_warns_when_not_strict(tmp_path, capsys):
    s = FakeSession([envelope(1, 2, 150, 100), envelope(2, 2, 150, 40)])
    assert len(fetch_amc_month(9, "2024-09", raw_dir=tmp_path, session=s, strict=False, **FAST)) == 2
    assert "WARNING" in capsys.readouterr().out


def test_total_changing_between_pages_raises(tmp_path):
    s = FakeSession([envelope(1, 2, 150, 100), envelope(2, 2, 151, 51)])
    with pytest.raises(TerApiError, match="data changed mid-fetch"):
        fetch_amc_month(9, "2024-09", raw_dir=tmp_path, session=s, **FAST)


def test_wrong_page_number_is_rejected(tmp_path):
    s = FakeSession([envelope(1, 2, 150, 100)] + [envelope(1, 2, 150, 100)] * 3)
    with pytest.raises(TerApiError, match="returned page 1"):
        fetch_amc_month(9, "2024-09", raw_dir=tmp_path, session=s, **FAST)


def test_empty_month_is_one_page(tmp_path):
    s = FakeSession([envelope(1, 0, 0, 0)])
    assert len(fetch_amc_month(9, "2024-09", raw_dir=tmp_path, session=s, **FAST)) == 1


def test_corrupt_cache_stops_instead_of_refetching(tmp_path):
    d = tmp_path / "mf_9" / "2024-09" / "cat_-1"
    d.mkdir(parents=True)
    (d / "p001.json").write_text('{"page": 1}', encoding="utf-8")
    with pytest.raises(TerApiError, match="remove that month's folder"):
        fetch_amc_month(9, "2024-09", raw_dir=tmp_path, session=FakeSession([]), **FAST)


def test_mf_list_validated_and_cached(tmp_path):
    s = FakeSession([Resp("[]"), Resp('[{"mfId": "9"}]')])
    assert fetch_mf_list(raw_dir=tmp_path, session=s, **FAST) == [{"mfId": "9"}]
    assert fetch_mf_list(raw_dir=tmp_path, session=FakeSession([]), **FAST) == [{"mfId": "9"}]


def test_top_level_pagination_is_rejected_and_kept_for_inspection(tmp_path):
    """The layout from the third-party notes (pagination at top level) is not what the server
    sends; it must fail, and the rejected body must be saved so the real shape can be read."""
    flat = Resp(json.dumps({"page": 1, "pageSize": 100, "total": 1, "pageCount": 1, "data": [{}]}))
    with pytest.raises(TerApiError, match="no 'meta' object"):
        fetch_amc_month(9, "2024-09", raw_dir=tmp_path, session=FakeSession([flat] * 3), **FAST)
    kept = tmp_path / "_rejected" / "mf_9_2024-09_cat-1_p001.txt"
    assert kept.exists() and '"pageCount": 1' in kept.read_text(encoding="utf-8")
    assert not (tmp_path / "mf_9" / "2024-09" / "cat_-1" / "p001.json").exists()


def test_meta_missing_a_key_is_rejected(tmp_path):
    bad = Resp(json.dumps({"data": [{}], "meta": {"page": 1, "total": 1}}))
    with pytest.raises(TerApiError, match="meta is missing"):
        fetch_amc_month(9, "2024-09", raw_dir=tmp_path, session=FakeSession([bad] * 3), **FAST)


def test_category_filter_param_and_cache_path(tmp_path):
    s = FakeSession([envelope(1, 1, 1, 1)])
    fetch_amc_month(9, "2026-08", strcat=7, raw_dir=tmp_path, session=s, **FAST)
    assert s.calls[0]["strCat"] == "7"
    assert (tmp_path / "mf_9" / "2026-08" / "cat_7" / "p001.json").exists()


def test_scan_categories_records_totals_labels_and_errors(tmp_path):
    """Stub labels 'CAT-A'/'CAT-B' are placeholders, not AMFI categories."""
    def page(total, labels):
        return Resp(json.dumps({"data": [{"SchemeCat_Desc": x} for x in labels],
                                "meta": {"page": 1, "pageSize": 100, "total": total, "pageCount": 1}}))
    s = FakeSession([page(2, ["CAT-A", "CAT-A"]), Resp("not json"), page(0, [])])
    out = tmp_path / "cats.csv"
    res = scan_categories(9, ("2026-08",), range(1, 4), out, session=s, sleep=0)
    assert [c["strCat"] for c in s.calls] == ["1", "2", "3"]           # one try per id, no retries
    assert res[0]["total"] == 2 and res[0]["categories_page1"] == "CAT-A"
    assert res[1]["error"] and res[1]["total"] == ""
    assert res[2]["total"] == 0
    assert out.read_text(encoding="utf-8").count("\n") == 4           # header + 3 ids


def test_scan_merges_with_earlier_scans(tmp_path):
    def page(total):
        return Resp(json.dumps({"data": [{"SchemeCat_Desc": "CAT-A"}] * total,
                                "meta": {"page": 1, "pageSize": 100, "total": total, "pageCount": 1}}))
    out = tmp_path / "cats.csv"
    scan_categories(9, ("2026-08",), range(1, 3), out, session=FakeSession([page(1), page(0)]), sleep=0)
    scan_categories(53, ("2026-08",), range(1, 2), out, session=FakeSession([page(2)]), sleep=0)
    scan_categories(9, ("2026-08",), range(2, 3), out, session=FakeSession([page(3)]), sleep=0)  # rescan id 2
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1 + 3                                     # (9,1) (9,2 rescanned) (53,1)
    assert lines[1].startswith("9,2026-08,1,1,") and lines[2].startswith("9,2026-08,2,3,")
    assert lines[3].startswith("53,2026-08,1,2,")


# ---- window fetch ----------------------------------------------------------------------------
import pandas as pd

from src import config
from src.ingest import ter_api
from src.ingest.ter_api import (INDEX_CATS, LARGE_CAP_CATS, check_filtered_labels, fetch_window,
                                plan_requests, resolve_amcs, verify_against_all_categories, window_months)


def labelled(page, page_count, total, labels):
    return Resp(json.dumps({"data": [{"SchemeCat_Desc": x, "Scheme_Name": f"S{i}"} for i, x in enumerate(labels)],
                            "meta": {"page": page, "pageSize": 100, "total": total, "pageCount": page_count}}))


def test_category_ids_are_backed_by_the_committed_scan():
    """Every ID used in code must have returned exactly its label in the live scan (D-051)."""
    scan = pd.read_csv(config.REFERENCE / "ter_api_categories.csv", dtype=str).fillna("")
    for cat, label in {**LARGE_CAP_CATS, **INDEX_CATS}.items():
        seen = set(scan.loc[(scan.strcat == str(cat)) & (scan.categories_page1 != ""), "categories_page1"])
        assert seen == {label}, (cat, seen)


def test_window_months():
    m = window_months()
    assert len(m) == 24 and m[0] == "2024-09" and m[-1] == "2026-08"


def test_resolve_amcs_exact_only():
    mfl = [{"mfName": "HDFC Mutual Fund", "mfId": "9"}, {"mfName": "Axis Mutual Fund", "mfId": "53"}]
    assert resolve_amcs(["HDFC Mutual Fund"], mfl) == {"HDFC Mutual Fund": 9}
    with pytest.raises(TerApiError, match="HDFC MF"):
        resolve_amcs(["HDFC MF"], mfl)


def test_plan_requests_index_cats_only_for_index_amcs():
    sm = pd.DataFrame({"amc": ["A MF", "A MF", "B MF"], "role": ["active", "index", "active"]})
    reqs = plan_requests(sm, {"A MF": 1, "B MF": 2}, ["2024-09", "2024-10"])
    a = {c for m, ym, c in reqs if m == 1}
    b = {c for m, ym, c in reqs if m == 2}
    assert a == set(LARGE_CAP_CATS) | set(INDEX_CATS) and b == set(LARGE_CAP_CATS)
    assert len(reqs) == 2 * (4 + 2)


def test_filtered_page_with_a_foreign_label_is_rejected():
    ok = [json.loads(labelled(1, 1, 1, [LARGE_CAP_CATS[15]]).text)]
    check_filtered_labels(ok, 15)
    bad = [json.loads(labelled(1, 1, 1, [LARGE_CAP_CATS[74]]).text)]
    with pytest.raises(TerApiError, match="other labels"):
        check_filtered_labels(bad, 15)


def _seed_all_categories(tmp_path, labels):
    d = tmp_path / "mf_9" / "2024-09" / "cat_-1"
    d.mkdir(parents=True)
    (d / "p001.json").write_text(labelled(1, 1, len(labels), labels).text, encoding="utf-8")


def test_verify_filter_matches_ground_truth(tmp_path):
    lc, ix = LARGE_CAP_CATS[15], INDEX_CATS[50]
    _seed_all_categories(tmp_path, [lc, "Debt Scheme - Gilt Fund", ix])
    # rows must be identical, so reproduce the same Scheme_Name suffixes as the seeded page (S0, S2)
    def one(label, name):
        return Resp(json.dumps({"data": [{"SchemeCat_Desc": label, "Scheme_Name": name}],
                                "meta": {"page": 1, "pageSize": 100, "total": 1, "pageCount": 1}}))
    empty = labelled(1, 0, 0, [])
    s = FakeSession([one(lc, "S0"), empty, one(ix, "S2"), empty])     # cats 15, 74, 50, 101
    assert verify_against_all_categories(9, "2024-09", raw_dir=tmp_path, session=s, **FAST) == {"large_cap": 1, "index": 1}


def test_verify_filter_detects_a_dropped_row(tmp_path):
    lc = LARGE_CAP_CATS[15]
    _seed_all_categories(tmp_path, [lc])
    empty = labelled(1, 0, 0, [])
    s = FakeSession([empty, empty, empty, empty])                       # filter returns nothing
    with pytest.raises(TerApiError, match="not trustworthy"):
        verify_against_all_categories(9, "2024-09", raw_dir=tmp_path, session=s, **FAST)


def test_fetch_window_continues_past_a_failure_and_resumes(tmp_path, monkeypatch):
    ref = tmp_path / "ref"
    ref.mkdir()
    pd.DataFrame({"amc": ["X Mutual Fund"], "role": ["active"]}).to_csv(ref / "scheme_map.csv", index=False)
    monkeypatch.setattr(config, "REFERENCE", ref)
    mfl = Resp(json.dumps([{"mfName": "X Mutual Fund", "mfId": "7"}]))
    s = FakeSession([mfl, labelled(1, 1, 1, [LARGE_CAP_CATS[15]])] + [Resp("x")] * 3)   # cat 74 keeps failing
    rc = fetch_window(raw_dir=tmp_path, session=s, months=["2024-09"], verify=(), cooldown=0, **FAST)
    assert rc == 1
    s2 = FakeSession([labelled(1, 0, 0, [])])                           # only cat 74 is requested again
    assert fetch_window(raw_dir=tmp_path, session=s2, months=["2024-09"], verify=(), cooldown=0, **FAST) == 0
    assert [c["strCat"] for c in s2.calls] == ["74"]


def test_failure_message_leads_with_the_reason(tmp_path):
    class Boom:
        def get(self, url, params=None, timeout=None):
            raise requests.ConnectTimeout("read timed out")
    with pytest.raises(TerApiError, match=r"^GET failed after 2 tries \(ConnectTimeout\): read timed out"):
        fetch_amc_month(9, "2024-09", raw_dir=tmp_path, session=Boom(), sleep=0, tries=2)


def test_ter_api_uses_its_own_short_timeout(tmp_path):
    seen = []
    class Spy(FakeSession):
        def get(self, url, params=None, timeout=None):
            seen.append(timeout)
            return super().get(url, params, timeout)
    fetch_amc_month(9, "2024-09", raw_dir=tmp_path, session=Spy([envelope(1, 1, 1, 1)]), **FAST)
    assert seen == [config.TER_API_TIMEOUT_S] and config.TER_API_TIMEOUT_S < config.HTTP_TIMEOUT_S
