"""
Staging Query: Load Purchases from S3 to Iceberg

This StagingQuery reads parquet files from S3 (MinIO) and materializes them
into an Iceberg table. The GroupBy will then read from this Iceberg table.

The query:
1. Reads from s3a://chronon/warehouse/data/purchases/purchases.parquet
2. Writes to bootcamp.purchases_iceberg (Iceberg format)
3. Can be executed via: run.py --mode=staging-query-backfill ...
"""

from ai.chronon.api.ttypes import StagingQuery, MetaData

# SQL query to read from S3 parquet and prepare for Iceberg
# The setup creates a temp table from the parquet file
# The main query selects and partitions by ds
query = """
SELECT
    user_id,
    purchase_price,
    item_category,
    ts,
    DATE(FROM_UNIXTIME(ts / 1000)) as ds
FROM purchases_raw
WHERE DATE(FROM_UNIXTIME(ts / 1000)) BETWEEN '{{ start_date }}' AND '{{ end_date }}'
"""

v1 = StagingQuery(
    query=query,
    startPartition="2023-12-01",
    # Setup statement creates a temporary view from the S3 parquet file
    setups=[
        """
        CREATE OR REPLACE TEMPORARY VIEW purchases_raw
        USING parquet
        OPTIONS (
            path 's3a://chronon/warehouse/data/purchases/purchases.parquet'
        )
        """
    ],
    metaData=MetaData(
        name='purchases_from_s3',
        outputNamespace="bootcamp",
        # This staging query doesn't depend on partitioned tables
        # because it reads directly from S3 parquet
        dependencies=[],
        tableProperties={
            # Configure output as Iceberg table
            "provider": "iceberg",
            "format-version": "2",
            "write.format.default": "parquet"
        }
    )
)

