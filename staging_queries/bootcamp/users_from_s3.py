"""
Staging Query: Load Users from S3 to Iceberg

This StagingQuery reads user parquet files from S3 (MinIO) and materializes them
into an Iceberg table.

The query:
1. Reads from s3a://chronon/warehouse/data/users/users.parquet
2. Writes to bootcamp.users_from_s3 (Iceberg format)
3. Can be executed via: run.py --mode=staging-query-backfill ...
"""

from ai.chronon.api.ttypes import StagingQuery, MetaData

# SQL query to read from S3 parquet
# Users data is a snapshot, so we'll use signup_date as the partition
query = """
SELECT
    user_id,
    age,
    city,
    signup_date,
    signup_date as ds
FROM users_raw
WHERE signup_date BETWEEN '{{ start_date }}' AND '{{ end_date }}'
"""

v1 = StagingQuery(
    query=query,
    startPartition="2023-01-01",  # Users signed up throughout the year
    # Setup statement creates a temporary view from the S3 parquet file
    setups=[
        """
        CREATE OR REPLACE TEMPORARY VIEW users_raw
        USING parquet
        OPTIONS (
            path 's3a://chronon/warehouse/data/users/users.parquet'
        )
        """
    ],
    metaData=MetaData(
        name='users_from_s3',
        outputNamespace="bootcamp",
        dependencies=[],
        tableProperties={
            # Configure output as Iceberg table
            "provider": "iceberg",
            "format-version": "2",
            "write.format.default": "parquet"
        }
    )
)

