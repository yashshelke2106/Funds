-- Reference constituent weights (D-027, D-044): the reference ETF's equity weights, renormalised to 1.
CREATE OR REPLACE TABLE intermediate.ref_weights AS
SELECT h.fund_id AS ref_fund_id, h.month, h.isin,
       h.weight_nav / sum(h.weight_nav) OVER (PARTITION BY h.fund_id, h.month) AS w
FROM staging.holdings h
JOIN staging.reference_portfolios r ON r.fund_id = h.fund_id
WHERE h.section = 'equity' AND h.isin IS NOT NULL;

-- Index futures spread over the same month's constituents. A future with no mapping or no same-month
-- reference weights would vanish here; tests/t04 compares allocated vs held and stops the build.
CREATE OR REPLACE TABLE intermediate.index_future_lookthrough AS
SELECT h.fund_id, h.month, rw.isin AS sec_key, sum(h.weight_nav * rw.w) AS index_fut_w
FROM staging.holdings h
JOIN staging.index_future_map m ON m.instrument_name = h.instrument_name
JOIN intermediate.ref_weights rw ON rw.ref_fund_id = m.ref_fund_id AND rw.month = h.month
WHERE h.derivative_kind = 'index_future'
GROUP BY ALL;

-- One row per fund x month x security key, components kept apart so P4 can build every variant:
--   equity_w     equity-section holdings (D-017); rows without an ISIN keyed 'NOISIN:<name_key>'
--   stock_fut_w  net stock futures on the underlying ISIN, expiries summed (D-020)
--   index_fut_w  index-future look-through (D-027, D-044)
--   option_w     options, keyed by instrument (D-041: treatment decided in P4)
CREATE OR REPLACE TABLE intermediate.fund_exposure AS
WITH eq AS (
    SELECT fund_id, month, coalesce(isin, 'NOISIN:' || name_key) AS sec_key, sum(weight_nav) AS equity_w
    FROM staging.holdings WHERE section = 'equity' GROUP BY ALL),
sf AS (
    SELECT fund_id, month, underlying_isin AS sec_key, sum(weight_nav) AS stock_fut_w
    FROM staging.holdings WHERE derivative_kind = 'stock_future' GROUP BY ALL),
op AS (
    SELECT fund_id, month, 'OPTION:' || instrument_name AS sec_key, sum(weight_nav) AS option_w
    FROM staging.holdings WHERE derivative_kind = 'option' GROUP BY ALL),
ix AS (SELECT fund_id, month, sec_key, index_fut_w FROM intermediate.index_future_lookthrough),
k AS (
    SELECT fund_id, month, sec_key FROM eq UNION SELECT fund_id, month, sec_key FROM sf
    UNION SELECT fund_id, month, sec_key FROM op UNION SELECT fund_id, month, sec_key FROM ix)
SELECT k.fund_id, k.month, k.sec_key,
       coalesce(eq.equity_w, 0)    AS equity_w,
       coalesce(sf.stock_fut_w, 0) AS stock_fut_w,
       coalesce(ix.index_fut_w, 0) AS index_fut_w,
       coalesce(op.option_w, 0)    AS option_w,
       k.sec_key LIKE 'NOISIN:%'   AS no_isin,
       k.sec_key LIKE 'OPTION:%'   AS is_option,
       -- D-031: ISIN chars 8-9 = security type; '01' = ordinary equity share
       (k.sec_key NOT LIKE 'NOISIN:%' AND k.sec_key NOT LIKE 'OPTION:%'
            AND substr(k.sec_key, 8, 2) <> '01')           AS non_ordinary,
       (k.sec_key NOT LIKE 'NOISIN:%' AND k.sec_key NOT LIKE 'OPTION:%'
            AND substr(k.sec_key, 1, 2) <> 'IN')           AS foreign_isin
FROM k
LEFT JOIN eq USING (fund_id, month, sec_key)
LEFT JOIN sf USING (fund_id, month, sec_key)
LEFT JOIN op USING (fund_id, month, sec_key)
LEFT JOIN ix USING (fund_id, month, sec_key);
