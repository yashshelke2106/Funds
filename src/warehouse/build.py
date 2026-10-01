"""DuckDB warehouse (P3, DECISIONS D-054): data/warehouse.duckdb, rebuilt on every run.

Inputs: data/interim/*.parquet (P2 outputs) and data/reference/*.csv. SQL lives in sql/:
  staging/       views, one per input, typed; no logic
  intermediate/  TRI calendar, plan NAVs on it, daily returns, exposures, weight variants, TER
  marts/         fund_month_weights, fund_month, fund_daily, fund: what P4 computes from
  tests/         each query returns the rows that break a rule; any row stops the build
Files run in name order within a layer. Paths and the study window reach the SQL as {{...}} placeholders,
so tests can build a warehouse from a small input directory. Each schema is dropped and recreated, so a
rebuild never keeps stale tables.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from src import config
from src.quality.holdings_checks import INDEX_FUTURE_REFERENCE, index_future_key

LAYERS = ("staging", "intermediate", "marts")
SQL_DIR = config.ROOT / "sql"
DB_PATH = config.DATA / "warehouse.duckdb"


class WarehouseTestError(RuntimeError):
    pass


def render(sql: str, params: dict[str, str]) -> str:
    for k, v in params.items():
        sql = sql.replace("{{" + k + "}}", v)
    if "{{" in sql:
        raise ValueError(f"unfilled placeholder in SQL: {sql[sql.index('{{'):][:40]}")
    return sql


def index_future_map(con, params) -> pd.DataFrame:
    """Instrument name -> reference portfolio, using the same rule as the quality step (D-027, D-044)."""
    names = con.execute(render(
        "SELECT DISTINCT instrument_name FROM read_parquet('{{interim}}/holdings.parquet') "
        "WHERE derivative_kind = 'index_future'", params)).fetchall()
    rows = []
    for (n,) in names:
        key = index_future_key(n)
        rows.append(dict(instrument_name=n, index_key=key, ref_fund_id=INDEX_FUTURE_REFERENCE.get(key)))
    return pd.DataFrame(rows, columns=["instrument_name", "index_key", "ref_fund_id"])


def build(db_path: Path = DB_PATH, interim: Path = config.INTERIM, reference: Path = config.REFERENCE,
          sql_dir: Path = SQL_DIR, window=(config.WINDOW_START, config.WINDOW_END)) -> dict[str, int]:
    params = {"interim": Path(interim).resolve().as_posix(), "reference": Path(reference).resolve().as_posix(),
              "window_start": window[0].isoformat(), "window_end": window[1].isoformat()}
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        for schema in reversed(LAYERS):
            con.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        for schema in LAYERS:
            con.execute(f"CREATE SCHEMA {schema}")
        ifm = index_future_map(con, params)
        con.register("ifm_df", ifm)
        con.execute("CREATE TABLE staging.index_future_map AS SELECT * FROM ifm_df")
        con.unregister("ifm_df")
        for layer in LAYERS:
            files = sorted((sql_dir / layer).glob("*.sql"))
            if not files:
                raise FileNotFoundError(f"no SQL in {sql_dir / layer}")
            for f in files:
                con.execute(render(f.read_text(encoding="utf-8"), params))
        failures = []
        for f in sorted((sql_dir / "tests").glob("*.sql")):
            rows = con.execute(render(f.read_text(encoding="utf-8"), params)).fetchall()
            failures += [(f.name, *r) for r in rows]
        if failures:
            shown = "\n".join(f"  {f}: {t}: {d}" for f, t, d in failures[:20])
            raise WarehouseTestError(f"{len(failures)} warehouse test failure(s):\n{shown}")
        counts = {f"{s}.{t}": con.execute(f"SELECT count(*) FROM {s}.{t}").fetchone()[0]
                  for s, t in con.execute("SELECT table_schema, table_name FROM information_schema.tables "
                                          "WHERE table_schema IN ('intermediate', 'marts') "
                                          "ORDER BY 1, 2").fetchall()}
        counts["tests"] = len(list((sql_dir / "tests").glob("*.sql")))
        return counts
    finally:
        con.close()


def run() -> Path:
    counts = build()
    n_tests = counts.pop("tests")
    print(f"warehouse: {DB_PATH} ({n_tests} SQL test files, 0 failures)")
    for k, v in counts.items():
        print(f"  {k:<40} {v:>9,}")
    return DB_PATH
