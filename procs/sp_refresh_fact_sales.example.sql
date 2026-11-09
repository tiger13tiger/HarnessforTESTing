-- Trigger run 4: fixed the Decimal-vs-float TypeError in golden_rows/aggregate checks.
-- Example candidate procedure for the auto-fix loop (harness/evolve_cli.py).
-- Deliberately contains a planted bug (double-counts revenue via a fan-out
-- join) so running the example end to end demonstrates a failing first
-- attempt and a fix on the next one.
CREATE OR ALTER PROCEDURE dbo.sp_refresh_fact_sales
AS
BEGIN
    SET NOCOUNT ON;

    SELECT
        s.product_category,
        SUM(s.revenue) AS revenue,
        COUNT(*) AS txn_count
    INTO #tmp_fact_sales
    FROM dbo.raw_sales s
    JOIN dbo.store_promotions p ON p.store_id = s.store_id  -- planted bug: fans out one sale per active promotion row
    GROUP BY s.product_category;

    TRUNCATE TABLE dbo.fact_sales;
    INSERT INTO dbo.fact_sales (product_category, revenue, txn_count)
    SELECT product_category, revenue, txn_count FROM #tmp_fact_sales;
END
