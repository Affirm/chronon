# Chronon Bootcamp - S3 to Iceberg GroupBy Quickstart

This guide shows you how to create Chronon features from S3 parquet data using Iceberg tables.

## Architecture

```
┌─────────────────┐
│   S3/MinIO      │  Raw parquet files stored in object storage
│  Parquet Files  │  - purchases.parquet
└────────┬────────┘  - users.parquet
         │
         │ ① StagingQuery reads and transforms
         ↓
┌─────────────────┐
│ Staging Query   │  SQL-based transformation
│  (Chronon)      │  - Reads from S3
└────────┬────────┘  - Adds partitions
         │            - Applies filters
         │
         │ ② Writes to Iceberg
         ↓
┌─────────────────┐
│ Iceberg Tables  │  Structured, partitioned tables
│  (bootcamp.*)   │  - purchases_from_s3
└────────┬────────┘  - users_from_s3
         │
         │ ③ GroupBy reads
         ↓
┌─────────────────┐
│   GroupBy       │  Feature computation
│   (Chronon)     │  - Time-windowed aggregations
└────────┬────────┘  - User-level features
         │
         │ ④ Outputs features
         ↓
┌─────────────────┐
│ Feature Tables  │  Ready for ML
│  & KV Store     │  - Offline: Hive/Iceberg tables
└─────────────────┘  - Online: MongoDB/KV store
```

## Files Created

### Staging Queries
- `staging_queries/bootcamp/purchases_from_s3.py` - Loads purchase events from S3 to Iceberg
- `staging_queries/bootcamp/users_from_s3.py` - Loads user data from S3 to Iceberg

### GroupBys
- `group_bys/bootcamp/user_purchase_features.py` - Computes purchase features per user

## Step-by-Step Guide

### Prerequisites

1. **Start the Chronon bootcamp environment**:
   ```bash
   cd affirm
   ./setup-chronon-bootcamp.sh
   ```

2. **Wait for all services to be ready** (check the setup script output)

3. **Verify S3/MinIO has the parquet files**:
   ```bash
   # Check MinIO console: http://localhost:9001
   # Login: minioadmin / minioadmin
   # Navigate to: chronon/warehouse/data/
   ```

### Step 1: Run the Staging Query

The staging query reads S3 parquet and writes to Iceberg:

```bash
# Enter the chronon-main container
docker-compose -f affirm/docker-compose-bootcamp.yml exec chronon-main bash

# Navigate to chronon root
cd /chronon

# Run the purchases staging query
run.py --mode=staging-query-backfill \
    --conf=staging_queries/bootcamp/purchases_from_s3.py \
    --start-date=2023-12-01 \
    --end-date=2023-12-07
```

**What happens:**
1. Spark reads `s3a://chronon/warehouse/data/purchases/purchases.parquet`
2. Applies the SQL transformation (adds `ds` partition column)
3. Writes to Iceberg table `bootcamp.purchases_from_s3`

### Step 2: Verify the Iceberg Table

Check that the staging query created the Iceberg table:

```bash
# List tables in bootcamp namespace
spark-sql -e "SHOW TABLES IN bootcamp"

# View sample data
spark-sql -e "SELECT * FROM bootcamp.purchases_from_s3 LIMIT 10"

# Check record count
spark-sql -e "SELECT COUNT(*), MIN(ds), MAX(ds) FROM bootcamp.purchases_from_s3"

# Verify it's an Iceberg table
spark-sql -e "DESCRIBE EXTENDED bootcamp.purchases_from_s3" | grep -i provider
```

You should see:
- ~155 purchase records
- Dates ranging from 2023-12-01 to 2023-12-07
- Provider: iceberg

### Step 3: Run the GroupBy

Now compute features from the Iceberg table:

```bash
# Run the GroupBy backfill
run.py --mode=backfill \
    --conf=group_bys/bootcamp/user_purchase_features.py \
    --start-date=2023-12-01 \
    --end-date=2023-12-07
```

**What happens:**
1. GroupBy reads from `bootcamp.purchases_from_s3` (Iceberg table)
2. Computes aggregations per user:
   - Sum of purchase prices (1 day, 7 days)
   - Count of purchases (1 day, 7 days)
   - Average purchase price (1 day, 7 days)
3. Writes features to `bootcamp_features.user_purchase_features`

### Step 4: Verify the Features

Check the computed features:

```bash
# View the feature table
spark-sql -e "SHOW TABLES IN bootcamp_features"

# See sample features
spark-sql -e "SELECT * FROM bootcamp_features.user_purchase_features LIMIT 10"

# Check feature statistics
spark-sql -e "
SELECT 
    COUNT(DISTINCT user_id) as num_users,
    AVG(user_purchase_features_purchase_price_sum_1d) as avg_spend_1d,
    AVG(user_purchase_features_purchase_price_sum_7d) as avg_spend_7d
FROM bootcamp_features.user_purchase_features
WHERE ds = '2023-12-07'
"
```

### Step 5: Upload to KV Store (Optional)

If you want to serve features online:

```bash
# Upload features to MongoDB
run.py --mode=upload \
    --conf=group_bys/bootcamp/user_purchase_features.py \
    --end-date=2023-12-07
```

### Step 6: Test Online Fetching (Optional)

Fetch features for a specific user:

```python
from ai.chronon.fetcher import Fetcher

fetcher = Fetcher()
features = fetcher.fetch_group_by(
    name="user_purchase_features",
    keys={"user_id": "user_1"}
)
print(features)
```

## Understanding the Data Flow

### 1. StagingQuery Configuration

```python
# staging_queries/bootcamp/purchases_from_s3.py

query = """
SELECT
    user_id,
    purchase_price,
    item_category,
    ts,
    DATE(FROM_UNIXTIME(ts / 1000)) as ds  # Add partition column
FROM purchases_raw
WHERE DATE(FROM_UNIXTIME(ts / 1000)) BETWEEN '{{ start_date }}' AND '{{ end_date }}'
"""

setups = [
    # Create temp view from S3 parquet
    """
    CREATE OR REPLACE TEMPORARY VIEW purchases_raw
    USING parquet
    OPTIONS (path 's3a://chronon/warehouse/data/purchases/purchases.parquet')
    """
]

tableProperties = {
    "provider": "iceberg",  # Output as Iceberg
    "format-version": "2"
}
```

### 2. GroupBy Configuration

```python
# group_bys/bootcamp/user_purchase_features.py

# Source references the staging query output
source = StagingQueryEventSource(
    staging_query=purchases_staging_query,  # References staging query
    query=Query(
        selects=select("user_id", "purchase_price", "item_category"),
        time_column="ts"
    )
)

# Define aggregations
v1 = GroupBy(
    sources=[source],
    keys=["user_id"],
    aggregations=[
        Aggregation(
            input_column="purchase_price",
            operation=Operation.SUM,
            windows=[Window(1, TimeUnit.DAYS), Window(7, TimeUnit.DAYS)]
        ),
        # ... more aggregations
    ],
    online=True,  # Enable online serving
    backfill_start_date="2023-12-01"
)
```

## Common Patterns

### Pattern 1: Direct S3 to Features

When you have clean S3 data that just needs feature computation:

1. **StagingQuery**: Read S3 → Write Iceberg (minimal transformation)
2. **GroupBy**: Read Iceberg → Compute features

### Pattern 2: S3 with Transformation

When you need to clean/transform the data:

1. **StagingQuery**: Read S3 → Transform (SQL) → Write Iceberg
2. **GroupBy**: Read Iceberg → Compute features

### Pattern 3: Multiple Sources

When joining multiple S3 datasets:

1. **StagingQuery 1**: purchases from S3 → Iceberg
2. **StagingQuery 2**: users from S3 → Iceberg
3. **GroupBy 1**: purchase features
4. **GroupBy 2**: user features
5. **Join**: Combine features

## Troubleshooting

### Issue: "Table not found: bootcamp.purchases_from_s3"

**Solution**: Run the staging query first
```bash
run.py --mode=staging-query-backfill \
    --conf=staging_queries/bootcamp/purchases_from_s3.py
```

### Issue: "NoSuchKey: The specified key does not exist"

**Solution**: Verify S3/MinIO has the parquet file
```bash
# Check MinIO
mc ls local/chronon/warehouse/data/purchases/

# Or use Spark
spark-sql -e "SELECT COUNT(*) FROM parquet.\`s3a://chronon/warehouse/data/purchases/purchases.parquet\`"
```

### Issue: Staging query runs but table is empty

**Solution**: Check date range
```bash
# Verify data date range
spark-sql -e "
SELECT 
    MIN(DATE(FROM_UNIXTIME(ts / 1000))) as min_date,
    MAX(DATE(FROM_UNIXTIME(ts / 1000))) as max_date
FROM parquet.\`s3a://chronon/warehouse/data/purchases/purchases.parquet\`
"

# Adjust staging query date range accordingly
```

### Issue: Iceberg table created but not in Iceberg format

**Solution**: Verify `tableProperties` in StagingQuery
```python
tableProperties={
    "provider": "iceberg",  # Must specify this
    "format-version": "2"
}
```

## Next Steps

### 1. Add More Aggregations

Modify `user_purchase_features.py` to add more features:
- Last purchase timestamp
- Most frequent item category
- Unique item count
- Min/max purchase prices

### 2. Create User Features

Create a GroupBy for user demographic features from `users_from_s3`.

### 3. Create a Join

Combine purchase features and user features into a single join for ML training.

### 4. Schedule with Airflow

Integrate with Airflow to run staging queries and GroupBys on a schedule.

## Key Concepts

### Why StagingQuery?

- **Separation of concerns**: Data loading vs. feature computation
- **Reusability**: Multiple GroupBys can read from the same staging query
- **Performance**: Materialized tables are faster than reading S3 repeatedly
- **Iceberg benefits**: Schema evolution, time travel, partition pruning

### Why Iceberg?

- **Schema evolution**: Add/remove columns without breaking pipelines
- **Time travel**: Query historical versions of data
- **ACID transactions**: Reliable reads during writes
- **Efficient partitioning**: Better query performance
- **Open format**: Not locked into a specific vendor

### Chronon Orchestration

Chronon automatically handles:
- **Dependencies**: GroupBy waits for staging query to complete
- **Partitioning**: Processes data in date partitions
- **Backfilling**: Fills historical data efficiently
- **Online/Offline**: Same features in batch and real-time

## Resources

- **Chronon Docs**: See `affirm/CHRONON_BOOTCAMP.md`
- **Iceberg Docs**: https://iceberg.apache.org/
- **Spark SQL Reference**: https://spark.apache.org/docs/latest/sql-ref.html
- **MinIO Docs**: https://min.io/docs/minio/linux/index.html

