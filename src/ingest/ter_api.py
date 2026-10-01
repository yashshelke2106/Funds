"""AMFI TER JSON API -> raw monthly pages cached verbatim in data/raw/ter/api/ (DECISIONS D-049).

Same source as the TER Excel export (amfiindia.com/ter-of-mf-schemes), reached through the JSON
endpoint that page calls. One request = one AMC (MF_ID) x one month (MM-YYYY) x one page; rows are
daily, one per scheme per day.

- strCat=-1 (all categories). The Excel export splits Large Cap across two category spellings and
  silently drops funds (D-023); asking for every category makes that failure impossible.
- The server caps pageSize at 100 whatever is requested, so every month is paginated.
- Pagination lives in a nested 'meta' object (observed; the third-party notes were wrong).
- Throttling reportedly shows up as HTTP 200 with a malformed body, not 429. Every page must parse
  and pass structural checks before it is written; a bad body is retried with backoff and never
  cached. Pages are written atomically (tmp + rename), so an interrupted run can't leave a
  truncated file that later looks like data.
- Completeness: rows summed over a month's pages must equal the server's `total`, and `total` /
  `pageCount` must agree on every page (data changing mid-fetch would break that).

Only fetching lives here; nothing is parsed or transformed. The parser is written after the probe
has shown the real layout (project rule: never guess a layout).

    python -m src.ingest.ter_api probe             # populate-mf + one AMC for two months; prints structure
    python -m src.ingest.ter_api scan-categories   # which strCat ID returns which category (live)
    python -m src.ingest.ter_api fetch             # whole window; resumable; verifies the filter first
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from pathlib import Path

import requests

from src import config

PAGINATION = ("page", "pageSize", "total", "pageCount")
PAGE_SIZE_REQUEST = 100  # server caps at 100 anyway; asking for more changes nothing
# Category IDs, found by scanning the live API (data/reference/ter_api_categories.csv, D-051), not guessed.
# The label each ID returned is kept too: filtered rows must carry exactly that label.
LARGE_CAP_CATS = {15: "Equity Scheme - Large Cap Fund", 74: "Equity Schemes - Large Cap Fund"}
INDEX_CATS = {50: "Other Scheme - Index Funds", 101: "Index Funds - Equity Funds"}
PROBE_MF_ID = 9          # HDFC per populate-mf; has both a Large Cap fund and a Nifty 100 index fund.
                         # The probe prints scheme names, so a wrong id is visible, not silent.


class TerApiError(RuntimeError):
    pass


def month_param(ym: str) -> str:
    """'2024-09' -> '09-2024' (the API's Month format)."""
    m = re.fullmatch(r"(\d{4})-(\d{2})", ym)
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise ValueError(f"month must be YYYY-MM, got {ym!r}")
    return f"{m.group(2)}-{m.group(1)}"


def rows_key(page: dict) -> str:
    """The single list-valued key holding the rows (name pinned after the probe)."""
    keys = [k for k, v in page.items() if isinstance(v, list)]
    if len(keys) != 1:
        raise TerApiError(f"expected exactly one list-valued key in a TER page, got {keys} "
                          f"(keys: {sorted(page)}) - format changed?")
    return keys[0]


def meta(obj) -> dict:
    """Pagination block. The server nests it under 'meta' (seen 2026-09-28: top-level keys
    ['data', 'meta']); the third-party notes that put it at the top level were wrong."""
    m = obj.get("meta") if isinstance(obj, dict) else None
    if not isinstance(m, dict):
        keys = sorted(obj) if isinstance(obj, dict) else type(obj).__name__
        raise TerApiError(f"no 'meta' object in TER page (got {keys}) - format changed?")
    missing = [k for k in PAGINATION if k not in m]
    if missing:
        raise TerApiError(f"meta is missing {missing} (meta keys: {sorted(m)})")
    return m


def check_page(obj, page: int) -> None:
    if not isinstance(obj, dict):
        raise TerApiError(f"page {page}: expected a JSON object, got {type(obj).__name__}")
    m = meta(obj)
    if int(m["page"]) != page:
        raise TerApiError(f"asked for page {page}, server returned page {m['page']}")
    rows_key(obj)


def check_mf_list(obj) -> None:
    if not isinstance(obj, list) or not obj or not all(isinstance(x, dict) for x in obj):
        raise TerApiError("populate-mf: expected a non-empty JSON array of objects")


def get_json(url: str, params: dict | None = None, validate=None, *, session=requests,
             tries: int = config.TER_API_RETRIES, sleep: float = config.TER_API_SLEEP_S,
             reject_path: Path | None = None) -> tuple[object, str]:
    """GET -> (parsed, verbatim text). Retries network errors, unparseable bodies and bodies that
    fail `validate`, with exponential backoff. Sleeps `sleep` after every success (politeness).
    The last rejected body is kept at `reject_path` for inspection; it is never read as data."""
    last: Exception | None = None
    for attempt in range(tries):
        r = None
        try:
            r = session.get(url, params=params, timeout=config.TER_API_TIMEOUT_S)
            r.raise_for_status()
            obj = json.loads(r.text)
            if validate is not None:
                validate(obj)
        except (requests.RequestException, ValueError, TerApiError) as e:
            last = e
            if reject_path is not None and r is not None and getattr(r, "text", None):
                _write_atomic(reject_path, r.text)
            time.sleep(sleep * 2 ** attempt)
            continue
        time.sleep(sleep)
        return obj, r.text
    # reason first: the fetch log truncates long messages, and the reason is what matters
    raise TerApiError(f"GET failed after {tries} tries ({type(last).__name__}): {str(last)[:120]} | {url} {params}")


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def fetch_mf_list(*, raw_dir: Path | None = None, refresh: bool = False, session=requests,
                  tries: int = config.TER_API_RETRIES, sleep: float = config.TER_API_SLEEP_S) -> list[dict]:
    raw_dir = raw_dir or config.RAW_TER_API
    path = raw_dir / "populate-mf.json"
    if path.exists() and not refresh:
        obj = json.loads(path.read_text(encoding="utf-8"))
        check_mf_list(obj)
        return obj
    obj, text = get_json(config.AMFI_MF_LIST_URL, validate=check_mf_list, session=session,
                         tries=tries, sleep=sleep)
    _write_atomic(path, text)
    return obj


def fetch_amc_month(mf_id: int, ym: str, *, strcat: int = -1, raw_dir: Path | None = None,
                    refresh: bool = False, strict: bool = True, session=requests,
                    tries: int = config.TER_API_RETRIES, sleep: float = config.TER_API_SLEEP_S) -> list[dict]:
    """All pages for one AMC x month x category (-1 = all); each page cached verbatim at
    mf_<id>/<YYYY-MM>/cat_<strcat>/pNNN.json. Cached pages are reused, so an interrupted run
    resumes where it stopped."""
    raw_dir = raw_dir or config.RAW_TER_API
    d = raw_dir / f"mf_{mf_id}" / ym / f"cat_{strcat}"
    params = {"MF_ID": str(mf_id), "Month": month_param(ym), "strCat": str(strcat), "strType": "1",
              "pageSize": str(PAGE_SIZE_REQUEST)}
    pages: list[dict] = []
    page, page_count, total = 1, None, None
    while page_count is None or page <= page_count:
        path = d / f"p{page:03d}.json"
        if path.exists() and not refresh:
            obj = json.loads(path.read_text(encoding="utf-8"))
            try:
                check_page(obj, page)
            except TerApiError as e:
                raise TerApiError(f"cached {path} is invalid ({e}); remove that month's folder and refetch") from e
        else:
            obj, text = get_json(config.AMFI_TER_API_URL, {**params, "page": str(page)},
                                 validate=lambda o, p=page: check_page(o, p),
                                 session=session, tries=tries, sleep=sleep,
                                 reject_path=raw_dir / "_rejected" / f"mf_{mf_id}_{ym}_cat{strcat}_p{page:03d}.txt")
            _write_atomic(path, text)
        m = meta(obj)
        if page_count is None:
            page_count, total = int(m["pageCount"]), int(m["total"])
        elif int(m["pageCount"]) != page_count or int(m["total"]) != total:
            raise TerApiError(f"mf_{mf_id} {ym} cat {strcat} page {page}: total/pageCount {m['total']}/{m['pageCount']} "
                              f"differ from page 1's {total}/{page_count} - data changed mid-fetch; refetch the month")
        pages.append(obj)
        page += 1
    got = sum(len(p[rows_key(p)]) for p in pages)
    if got != total:
        msg = f"mf_{mf_id} {ym} cat {strcat}: {got} rows across {len(pages)} page(s), server total={total}"
        if strict:
            raise TerApiError(msg)
        print("WARNING (probe, not strict):", msg)
    return pages


def window_months(start=config.WINDOW_START, end=config.WINDOW_END) -> list[str]:
    return [str(p) for p in __import__("pandas").period_range(start, end, freq="M")]


def resolve_amcs(amcs, mf_list: list[dict]) -> dict[str, int]:
    """Exact-name match of scheme_map AMC names to populate-mf; any miss stops (no fuzzy matching)."""
    by_name = {str(m["mfName"]).strip(): int(m["mfId"]) for m in mf_list}
    miss = sorted(a for a in set(amcs) if a not in by_name)
    if miss:
        raise TerApiError(f"AMC(s) not in populate-mf by exact name: {miss}")
    return {a: by_name[a] for a in sorted(set(amcs))}


def plan_requests(scheme_map, mf_ids: dict[str, int], months: list[str]) -> list[tuple[int, str, int]]:
    """(mf_id, month, strCat): Large Cap IDs for every AMC; index IDs only for AMCs with an index fund."""
    index_amcs = set(scheme_map.loc[scheme_map.role == "index", "amc"])
    out = []
    for amc, mf_id in sorted(mf_ids.items(), key=lambda kv: kv[0].lower()):
        cats = list(LARGE_CAP_CATS) + (list(INDEX_CATS) if amc in index_amcs else [])
        out += [(mf_id, ym, c) for ym in months for c in cats]
    return out


def _rows(pages: list[dict]) -> list[dict]:
    return [r for p in pages for r in p[rows_key(p)]]


def check_filtered_labels(pages: list[dict], strcat: int) -> None:
    """A category filter must return only its own label."""
    want = {**LARGE_CAP_CATS, **INDEX_CATS}[strcat]
    bad = {r.get("SchemeCat_Desc") for r in _rows(pages)} - {want}
    if bad:
        raise TerApiError(f"strCat={strcat} returned other labels {sorted(map(str, bad))}; expected only {want!r}")


def verify_against_all_categories(mf_id: int, ym: str, *, raw_dir: Path | None = None, session=requests,
                                  tries: int = config.TER_API_RETRIES,
                                  sleep: float = config.TER_API_SLEEP_S) -> dict[str, int]:
    """Ground truth: rows from the category filters must equal, as a multiset, the rows carrying those
    labels in the cached all-category (strCat=-1) fetch of the same AMC-month."""
    raw_dir = raw_dir or config.RAW_TER_API
    full = fetch_amc_month(mf_id, ym, strcat=-1, raw_dir=raw_dir, session=session, tries=tries, sleep=sleep)
    out = {}
    for name, cats in (("large_cap", LARGE_CAP_CATS), ("index", INDEX_CATS)):
        got = []
        for c in cats:
            pages = fetch_amc_month(mf_id, ym, strcat=c, raw_dir=raw_dir, session=session, tries=tries, sleep=sleep)
            check_filtered_labels(pages, c)
            got += _rows(pages)
        want = [r for r in _rows(full) if r.get("SchemeCat_Desc") in set(cats.values())]
        canon = lambda rows: Counter(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows)
        if canon(got) != canon(want):
            raise TerApiError(f"mf_{mf_id} {ym} {name}: filtered fetch has {len(got)} rows, all-category fetch has "
                              f"{len(want)} with those labels - the filter is not trustworthy")
        out[name] = len(got)
    return out


def fetch_window(*, raw_dir: Path | None = None, session=requests, months: list[str] | None = None,
                 verify: tuple[tuple[int, str], ...] = ((PROBE_MF_ID, "2024-09"), (PROBE_MF_ID, "2026-08")),
                 tries: int = config.TER_API_RETRIES, sleep: float = config.TER_API_SLEEP_S,
                 cooldown: float = config.TER_API_COOLDOWN_S) -> int:
    """Everything the TER step needs, for the whole window. Resumable (cached pages are reused).
    A failed AMC-month is reported and skipped; exit code 1 until a rerun completes it."""
    import pandas as pd
    raw_dir = raw_dir or config.RAW_TER_API
    sm = pd.read_csv(config.REFERENCE / "scheme_map.csv")
    mf_ids = resolve_amcs(sm.amc, fetch_mf_list(raw_dir=raw_dir, session=session, tries=tries, sleep=sleep))
    for mf_id, ym in verify:  # stop before the bulk run if the filter doesn't reproduce the ground truth
        res = verify_against_all_categories(mf_id, ym, raw_dir=raw_dir, session=session, tries=tries, sleep=sleep)
        print(f"filter check mf_{mf_id} {ym}: identical to all-category fetch {res}")
    reqs = plan_requests(sm, mf_ids, months or window_months())
    names = {v: k for k, v in mf_ids.items()}
    failed = []
    t0 = time.time()
    for i, (mf_id, ym, cat) in enumerate(reqs, 1):
        try:
            pages = fetch_amc_month(mf_id, ym, strcat=cat, raw_dir=raw_dir, session=session, tries=tries, sleep=sleep)
            check_filtered_labels(pages, cat)
        except TerApiError as e:
            failed.append((mf_id, ym, cat, str(e)[:160]))
            print(f"  FAILED mf_{mf_id} {ym} cat {cat}: {str(e)[:160]}  (cooling down {cooldown:.0f}s)")
            time.sleep(cooldown)
            continue
        if i % 50 == 0 or i == len(reqs):
            el = time.time() - t0
            eta = el / i * (len(reqs) - i)
            print(f"  [{i}/{len(reqs)}] {names[mf_id]} {ym} cat {cat}  ({el / 60:.0f} min elapsed; "
                  f"~{eta / 60:.0f} min left at this pace; {len(failed)} failed so far)")
    print(f"ter_api fetch: {len(reqs)} AMC-month-category requests, {len(failed)} failed -> {raw_dir}")
    for f in failed:
        print("  failed:", f)
    return 1 if failed else 0


def scan_categories(mf_id: int = PROBE_MF_ID, months: tuple[str, ...] = ("2024-09", "2026-08"),
                    ids: range = range(1, 101), out_csv: Path | None = None, *, session=requests,
                    sleep: float = config.TER_API_SLEEP_S) -> list[dict]:
    """Find which strCat IDs return which categories, from the live API, instead of guessing.
    Page 1 only, one try per ID (an invalid ID is recorded as an error, not retried). Rows are
    not cached as data; the result is a reference file: data/reference/ter_api_categories.csv."""
    import csv
    out_csv = out_csv or (config.REFERENCE / "ter_api_categories.csv")
    base = {"MF_ID": str(mf_id), "strType": "1", "pageSize": str(PAGE_SIZE_REQUEST), "page": "1"}
    res = []
    for ym in months:
        for i in ids:
            rec = dict(mf_id=mf_id, month=ym, strcat=i, total="", page_count="", rows_page1="",
                       categories_page1="", error="")
            try:
                obj, _ = get_json(config.AMFI_TER_API_URL, {**base, "Month": month_param(ym), "strCat": str(i)},
                                  validate=lambda o: check_page(o, 1), session=session, tries=1, sleep=sleep)
                m, rows = meta(obj), obj[rows_key(obj)]
                rec.update(total=int(m["total"]), page_count=int(m["pageCount"]), rows_page1=len(rows),
                           categories_page1=" ; ".join(sorted({str(r.get("SchemeCat_Desc")) for r in rows})))
            except TerApiError as e:
                rec["error"] = str(e)[:200]
                time.sleep(sleep)
            res.append(rec)
            if rec["total"] not in ("", 0):
                print(f"  {ym} strCat={i:>3}: total={rec['total']:>5}  {rec['categories_page1']}")
    # merge with earlier scans: a new scan replaces only the same (mf_id, month, strcat) rows
    fields = list(res[0])
    keep = []
    if out_csv.exists():
        with open(out_csv, newline="", encoding="utf-8") as fh:
            new_keys = {(str(r["mf_id"]), r["month"], str(r["strcat"])) for r in res}
            keep = [r for r in csv.DictReader(fh) if (r["mf_id"], r["month"], r["strcat"]) not in new_keys]
    allrows = sorted(keep + res, key=lambda r: (int(r["mf_id"]), r["month"], int(r["strcat"])))
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(allrows)
    n_err = sum(1 for r in res if r["error"])
    print(f"scan: {len(res)} requests, {n_err} errors -> {out_csv}")
    return res


def probe(mf_id: int = PROBE_MF_ID, months: tuple[str, ...] = ("2024-09", "2026-08")) -> None:
    """Fetch a small sample and print its real structure. Uses .get() on row fields on purpose:
    their names are unverified until this output has been read."""
    mfl = fetch_mf_list()
    print(f"populate-mf: {len(mfl)} entries; keys of first entry: {sorted(mfl[0])}")
    hit = [m for m in mfl if str(mf_id) in {str(v) for v in m.values()}]
    print(f"  entries mentioning {mf_id}: {hit[:3]}")
    for ym in months:
        pages = fetch_amc_month(mf_id, ym, strict=False)
        key = rows_key(pages[0])
        rows = [r for p in pages for r in p[key]]
        m0 = meta(pages[0])
        print(f"\n== mf_{mf_id} {ym}: {len(pages)} page(s); rows={len(rows)}; server total={m0['total']}; "
              f"server pageSize={m0['pageSize']}; rows key={key!r}")
        print(f"   top-level keys: {sorted(pages[0])}; meta: {m0}")
        print(f"   rows per page: {[len(p[key]) for p in pages]}")
        print(f"   row keys: {sorted({k for r in rows for k in r})}")
        dates = sorted({str(r.get('TER_Date')) for r in rows})
        print(f"   TER_Date: {len(dates)} distinct, {dates[0]} .. {dates[-1]}")
        print(f"   SchemeCat_Desc: {dict(Counter(r.get('SchemeCat_Desc') for r in rows).most_common())}")
        null_codes = Counter(r.get("Scheme_Name") for r in rows if not r.get("NSDLSchemeCode"))
        print(f"   rows with empty NSDLSchemeCode: {sum(null_codes.values())} across {len(null_codes)} scheme(s): "
              f"{sorted(null_codes)[:15]}")
        focus = [r for r in rows if re.search(r"large\s*cap|nifty\s*100|index", str(r.get("Scheme_Name")), re.I)]
        print("   Large Cap / index schemes (name | category | NSDL code):")
        for t in sorted({(r.get("Scheme_Name"), r.get("SchemeCat_Desc"), r.get("NSDLSchemeCode")) for r in focus},
                        key=str):
            print("     ", " | ".join(str(x) for x in t))
        lc = [r for r in focus if re.search(r"large\s*cap", str(r.get("Scheme_Name")), re.I)]
        if lc:
            print(f"   first Large Cap row, verbatim: {json.dumps(lc[0], ensure_ascii=False)}")
    print(f"\nraw pages cached under {config.RAW_TER_API}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AMFI TER JSON API fetcher (D-049)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe", help="fetch a small sample and print its structure")
    p.add_argument("--mf-id", type=int, default=PROBE_MF_ID)
    p.add_argument("--months", nargs="+", default=["2024-09", "2026-08"])
    sc = sub.add_parser("scan-categories", help="map strCat IDs to categories from the live API")
    sc.add_argument("--mf-id", type=int, default=PROBE_MF_ID)
    sc.add_argument("--months", nargs="+", default=["2024-09", "2026-08"])
    sc.add_argument("--min-id", type=int, default=1)
    sc.add_argument("--max-id", type=int, default=100)
    sub.add_parser("fetch", help="fetch the whole window (resumable; checks the filter first)")
    a = ap.parse_args(argv)
    if a.cmd == "probe":
        probe(a.mf_id, tuple(a.months))
    elif a.cmd == "scan-categories":
        scan_categories(a.mf_id, tuple(a.months), range(a.min_id, a.max_id + 1))
    elif a.cmd == "fetch":
        return fetch_window()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
