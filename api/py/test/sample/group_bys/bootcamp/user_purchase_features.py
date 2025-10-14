"""
User Purchase Features GroupBy

This GroupBy reads from an Iceberg table that is materialized by a StagingQuery
from S3 parquet files.

Data flow:
1. S3 parquet (s3a://chronon/warehouse/data/purchases/purchases.parquet)
2. → StagingQuery (staging_queries/bootcamp/purchases_from_s3.py)
3. → Iceberg table (bootcamp.purchases_from_s3)
4. → This GroupBy → Feature computation

Features computed:
- Sum of purchase prices (1 day, 7 days)
- Count of purchases (1 day, 7 days)
- Average purchase price (1 day, 7 days)

To run:
1. First run the staging query to materialize S3 data to Iceberg:
   run.py --mode=staging-query-backfill staging_queries/bootcamp/purchases_from_s3.py
2. Then run this GroupBy:
   run.py --mode=backfill group_bys/bootcamp/user_purchase_features.py
"""

from ai.chronon.api.ttypes import Source, EventSource
from ai.chronon.query import Query, select
from ai.chronon.group_by import GroupBy, Aggregation, Operation, Window, TimeUnit

# Define the source - create Iceberg table in the setup, then read from it
source = Source(
    events=EventSource(
        table="bootcamp.purchases_iceberg",  # Iceberg table created in setup
        query=Query(
            selects=select("user_id", "purchase_price", "item_category"),
            setups=[
                # Create Iceberg table from data.purchases
                """
                CREATE TABLE IF NOT EXISTS bootcamp.purchases_iceberg
                USING iceberg
                AS SELECT * FROM data.purchases
                """
            ],
            time_column="ts"
        )
    )
)

# Define time windows for aggregations
window_sizes = [
    Window(length=1, timeUnit=TimeUnit.DAYS),    # 1 day
    Window(length=7, timeUnit=TimeUnit.DAYS),    # 7 days
]

# Create the GroupBy configuration
v1 = GroupBy(
    sources=[source],
    keys=["user_id"],
    aggregations=[
        # Sum of purchase prices
        Aggregation(
            input_column="purchase_price",
            operation=Operation.SUM,
            windows=window_sizes
        ),
        # Count of purchases
        Aggregation(
            input_column="purchase_price",
            operation=Operation.COUNT,
            windows=window_sizes
        ),
        # Average purchase price
        Aggregation(
            input_column="purchase_price",
            operation=Operation.AVERAGE,
            windows=window_sizes
        ),
    ],
    online=True,
    backfill_start_date="2023-12-01",
    output_namespace="bootcamp_features",
)
