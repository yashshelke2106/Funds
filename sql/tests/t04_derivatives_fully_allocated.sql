-- Every index future must be spread in full; every stock future must have an underlying (D-020, D-027, D-044).
SELECT 't04_index_future_allocation' AS test,
       h.fund_id || ' ' || h.month || ' held=' || h.held || ' allocated=' || coalesce(l.alloc, 0) AS detail
FROM (SELECT fund_id, month, sum(weight_nav) AS held FROM staging.holdings
      WHERE derivative_kind = 'index_future' GROUP BY ALL) h
LEFT JOIN (SELECT fund_id, month, sum(index_fut_w) AS alloc FROM intermediate.index_future_lookthrough GROUP BY ALL) l
       USING (fund_id, month)
WHERE abs(h.held - coalesce(l.alloc, 0)) > 1e-9
UNION ALL
SELECT 't04_index_future_unmapped', instrument_name
FROM staging.index_future_map WHERE ref_fund_id IS NULL
UNION ALL
SELECT 't04_stock_future_no_underlying', fund_id || ' ' || month || ' ' || instrument_name
FROM staging.holdings WHERE derivative_kind = 'stock_future' AND underlying_isin IS NULL
UNION ALL
SELECT 't04_derivatives_conserved', fund_id || ' ' || month
FROM (SELECT fund_id, month, sum(stock_fut_w) AS s, sum(option_w) AS o FROM intermediate.fund_exposure GROUP BY ALL) e
JOIN (SELECT fund_id, month,
             coalesce(sum(weight_nav) FILTER (WHERE derivative_kind = 'stock_future'), 0) AS s,
             coalesce(sum(weight_nav) FILTER (WHERE derivative_kind = 'option'), 0) AS o
      FROM staging.holdings GROUP BY ALL) h USING (fund_id, month)
WHERE abs(e.s - h.s) > 1e-9 OR abs(e.o - h.o) > 1e-9;
