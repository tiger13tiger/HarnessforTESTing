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
    GROUP BY s.product_category;

    TRUNCATE TABLE dbo.fact_sales;
    INSERT INTO dbo.fact_sales (product_category, revenue, txn_count)
    SELECT product_category, revenue, txn_count FROM #tmp_fact_sales;
END