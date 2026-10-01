-- Σ equity weight per fund-month must equal what P2 reconciled against each file's own total (D-017).
SELECT 't03_equity_vs_meta' AS test,
       e.fund_id || ' ' || e.month || ' warehouse=' || e.s || ' meta=' || m.equity_weight_raw AS detail
FROM (SELECT fund_id, month, sum(equity_w) AS s FROM intermediate.fund_exposure GROUP BY ALL) e
JOIN staging.portfolio_meta m USING (fund_id, month)
WHERE abs(e.s - m.equity_weight_raw) > 1e-9
UNION ALL
SELECT 't03_fund_months_vs_meta', 'warehouse=' || (SELECT count(*) FROM marts.fund_month)
       || ' meta=' || (SELECT count(*) FROM staging.portfolio_meta)
WHERE (SELECT count(*) FROM marts.fund_month) <> (SELECT count(*) FROM staging.portfolio_meta);
