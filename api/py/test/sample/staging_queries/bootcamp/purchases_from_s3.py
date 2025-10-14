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

# SQL query to read from data.purchases and prepare for Iceberg
# We read from the existing data.purchases table and write to Iceberg format
query = """
SELECT
    user_id,
    purchase_price,
    item_category,
    ts,
    ds
FROM data.purchases
WHERE ds BETWEEN '{{ start_date }}' AND '{{ end_date }}'
"""

v1 = StagingQuery(
    query=query,
    startPartition="2023-12-01",
    # No setup needed - reading from existing table
    setups=[],
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

