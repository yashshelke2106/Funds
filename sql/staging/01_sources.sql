-- Staging: one view per input file, typed, renamed where needed. No logic (P3, D-054).
CREATE OR REPLACE VIEW staging.holdings AS
SELECT fund_id, amc_slug,
       CAST(month || '-01' AS DATE)  AS month,
       CAST(as_of AS DATE)           AS as_of,
       CAST(available_from AS DATE)  AS available_from,     -- D-009: known from the 11th of M+1
       section, derivative_kind, instrument_name, name_key, isin, underlying_isin, industry,
       quantity, market_value_lakh, weight_nav, weight_reported, isin_checksum_ok, source_file, source_row
FROM read_parquet('{{interim}}/holdings.parquet');

CREATE OR REPLACE VIEW staging.portfolio_meta AS
SELECT fund_id, CAST(month || '-01' AS DATE) AS month, CAST(as_of AS DATE) AS as_of, nav_lakh,
       equity_weight_raw, n_equity_rows, n_derivative_rows, derivative_net_weight, index_future_weight,
       stated_benchmark, source_file
FROM read_parquet('{{interim}}/portfolio_meta.parquet');

CREATE OR REPLACE VIEW staging.nav AS
SELECT CAST(scheme_code AS BIGINT) AS scheme_code, CAST(nav_date AS DATE) AS nav_date, nav
FROM read_parquet('{{interim}}/nav.parquet');

CREATE OR REPLACE VIEW staging.benchmark_tri AS
SELECT CAST(date AS DATE) AS tri_date, tri
FROM read_parquet('{{interim}}/benchmark_tri.parquet');

CREATE OR REPLACE VIEW staging.ter_daily AS
SELECT fund_id, plan, CAST(ter_date AS DATE) AS ter_date, base, addl_b, addl_c, brokerage, txn, levies, total,
       format, filled
FROM read_parquet('{{interim}}/ter_daily.parquet');

CREATE OR REPLACE VIEW staging.scheme_map AS
SELECT fund_id, role, amc, scheme_name, CAST(direct_code AS BIGINT) AS direct_code,
       CAST(regular_code AS BIGINT) AS regular_code
FROM read_csv('{{reference}}/scheme_map.csv', header = true, auto_detect = true);

CREATE OR REPLACE VIEW staging.universe AS
SELECT fund_id, role, amc, scheme_name, CAST(eligible AS BOOLEAN) AS eligible, report_group, exclusion_reason,
       CAST(direct_first_nav AS DATE) AS direct_first_nav, CAST(regular_first_nav AS DATE) AS regular_first_nav
FROM read_csv('{{reference}}/universe.csv', header = true, auto_detect = true, all_varchar = true);

CREATE OR REPLACE VIEW staging.benchmark_proxy AS
SELECT fund_id, CAST(selected_as_weight_proxy AS BOOLEAN) AS selected
FROM read_csv('{{reference}}/benchmark_proxy_selection.csv', header = true, auto_detect = true, all_varchar = true);

CREATE OR REPLACE VIEW staging.reference_portfolios AS
SELECT fund_id, index_name
FROM read_csv('{{reference}}/reference_portfolios.csv', header = true, auto_detect = true, all_varchar = true);

CREATE OR REPLACE VIEW staging.isin_changes AS   -- D-026: accepted corporate-action ISIN changes (turnover, P4)
SELECT old_isin, new_isin, name_key
FROM read_csv('{{reference}}/isin_changes.csv', header = true, auto_detect = true, all_varchar = true)
WHERE lower(accepted) = 'true';
-- staging.index_future_map is written by build.py from the same Python rule the quality step uses.
