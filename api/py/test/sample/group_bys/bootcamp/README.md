# Bootcamp GroupBys - S3 to Iceberg Pipeline

This directory contains Chronon GroupBy configurations that compute features from Iceberg tables, which are populated from S3 parquet data via StagingQueries.

## Architecture Overview

```
S3 Parquet → StagingQuery → Iceberg Table → GroupBy → Features
```

### Why This Architecture?

1. **S3 Storage**: Raw data in parquet format (cost-effective, scalable)
2. **StagingQuery**: Loads and transforms S3 data into structured tables
3. **Iceberg Format**: Provides ACID, schema evolution, time travel
4. **GroupBy**: Computes time-windowed aggregations and features
5. **Output**: Both offline (tables) and online (KV store) features

## Files in This Directory

### GroupBy Configurations

- **`user_purchase_features.py`**: Computes purchase behavior features per user
  - Sum, count, average of purchases over 1d and 7d windows
  - Source: `bootcamp.purchases_from_s3` (Iceberg table)

### Supporting Files

- **`QUICKSTART.md`**: Step-by-step guide to run the pipeline
- **`__init__.py`**: Python package marker

## Related Files

### Staging Queries (in `staging_queries/bootcamp/`)

- **`purchases_from_s3.py`**: Loads purchase data from S3 to Iceberg
- **`users_from_s3.py`**: Loads user data from S3 to Iceberg

## Quick Start

### 1. Run the Staging Query

Load S3 data into Iceberg:

```bash
docker-compose -f affirm/docker-compose-bootcamp.yml exec chronon-main bash
cd /chronon

run.py --mode=staging-query-backfill \
    --conf=staging_queries/bootcamp/purchases_from_s3.py \
    --start-date=2023-12-01 \
    --end-date=2023-12-07
```

### 2. Run the GroupBy

Compute features:

```bash
run.py --mode=backfill \
    --conf=group_bys/bootcamp/user_purchase_features.py \
    --start-date=2023-12-01 \
    --end-date=2023-12-07
```

### 3. Upload to KV Store (Optional)

Enable online serving:

```bash
run.py --mode=upload \
    --conf=group_bys/bootcamp/user_purchase_features.py \
    --end-date=2023-12-07
```

## Data Flow Detail

### Input: S3 Parquet Files

Located in MinIO at:
- `s3a://chronon/warehouse/data/purchases/purchases.parquet`
- ~155 purchase records
- Date range: Dec 1-7, 2023

Schema:
```
user_id: string
purchase_price: double
item_category: string
ts: long (milliseconds)
```

### Intermediate: Iceberg Table

Created by StagingQuery at:
- `bootcamp.purchases_from_s3`

Schema (after transformation):
```
user_id: string
purchase_price: double
item_category: string
ts: long
ds: date (partition key)
```

### Output: Feature Table

Created by GroupBy at:
- `bootcamp_features.user_purchase_features`

Features (per user):
```
user_id: string
user_purchase_features_purchase_price_sum_1d: double
user_purchase_features_purchase_price_sum_7d: double
user_purchase_features_purchase_price_count_1d: long
user_purchase_features_purchase_price_count_7d: long
user_purchase_features_purchase_price_average_1d: double
user_purchase_features_purchase_price_average_7d: double
ds: date (partition key)
```

## Key Concepts

### StagingQuery

A StagingQuery is a Chronon construct that:
- Reads from external data sources (S3, databases, etc.)
- Applies SQL transformations
- Materializes data into structured tables
- Can output in Iceberg format

**Benefits**:
- Reusable: Multiple GroupBys can read from one StagingQuery
- Performant: Materialized tables are faster than reading S3 repeatedly
- Organized: Separates data loading from feature computation

### StagingQueryEventSource

When a GroupBy uses `StagingQueryEventSource`:
- It automatically reads from the StagingQuery's output table
- Chronon manages dependencies (waits for staging query to complete)
- The connection is explicit in the code (better than magic table names)

```python
from ai.chronon.staging_query import StagingQueryEventSource

source = StagingQueryEventSource(
    staging_query=purchases_staging_query,  # References the staging query
    query=Query(...)
)
```

### Iceberg Tables

Why use Iceberg format?

1. **ACID Transactions**: Safe concurrent reads/writes
2. **Schema Evolution**: Add/remove columns without breaking downstream
3. **Time Travel**: Query historical versions of data
4. **Partition Evolution**: Change partitioning without rewriting data
5. **Hidden Partitioning**: Users don't need to filter by partition columns

Configured via `tableProperties`:
```python
tableProperties={
    "provider": "iceberg",
    "format-version": "2",
    "write.format.default": "parquet"
}
```

## Development Workflow

### Adding a New Feature

1. **Modify the GroupBy**:
   ```python
   # Add a new aggregation
   Aggregation(
       input_column="purchase_price",
       operation=Operation.MAX,
       windows=window_sizes
   )
   ```

2. **Recompile**:
   ```bash
   run.py --mode=compile --conf=group_bys/bootcamp/user_purchase_features.py
   ```

3. **Backfill**:
   ```bash
   run.py --mode=backfill --conf=group_bys/bootcamp/user_purchase_features.py
   ```

### Adding a New Data Source

1. **Create a StagingQuery**:
   ```python
   # staging_queries/bootcamp/new_source.py
   v1 = StagingQuery(
       query="SELECT ... FROM new_data_raw WHERE ...",
       setups=["CREATE TEMP VIEW new_data_raw ..."],
       # ...
   )
   ```

2. **Create a GroupBy** that uses it:
   ```python
   from staging_queries.bootcamp.new_source import v1 as new_source_sq
   
   source = StagingQueryEventSource(
       staging_query=new_source_sq,
       query=Query(...)
   )
   ```

3. **Run**: Staging query first, then GroupBy

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| "Table not found" | Run staging query first |
| "NoSuchKey" (S3) | Verify parquet file exists in MinIO |
| Empty output table | Check date ranges match your data |
| Iceberg errors | Verify `tableProperties` include `"provider": "iceberg"` |
| Import errors | Ensure `__init__.py` files exist in directories |

### Debugging Commands

```bash
# Check if staging query output exists
spark-sql -e "SHOW TABLES IN bootcamp"

# View staging query output
spark-sql -e "SELECT * FROM bootcamp.purchases_from_s3 LIMIT 10"

# Check GroupBy output
spark-sql -e "SELECT * FROM bootcamp_features.user_purchase_features LIMIT 10"

# View table metadata
spark-sql -e "DESCRIBE EXTENDED bootcamp.purchases_from_s3"

# Check Iceberg table history
spark-sql -e "SELECT * FROM bootcamp.purchases_from_s3.history"
```

## Performance Tips

### For Large Datasets

1. **Partition wisely**: Use date partitioning for time-series data
2. **Adjust Spark config**: Set executor memory, cores, parallelism
3. **Incremental processing**: Use `start_date` and `end_date` parameters
4. **Iceberg benefits**: Automatic file compaction, statistics

### Configuration

Add to GroupBy's `env` parameter:
```python
env={
    'backfill': {
        'EXECUTOR_MEMORY': '8G',
        'EXECUTOR_CORES': '4',
        'SPARK_PARALLELISM': '100'
    }
}
```

## Next Steps

1. **Read `QUICKSTART.md`** for detailed walkthrough
2. **Run the pipeline** with the sample data
3. **Modify features** to add your own aggregations
4. **Create a Join** combining multiple GroupBys
5. **Test online serving** with MongoDB KV store
6. **Schedule with Airflow** for production

## Resources

- **Chronon Bootcamp**: `affirm/CHRONON_BOOTCAMP.md`
- **Staging Queries**: `staging_queries/bootcamp/README.md`
- **Quickstart Guide**: `QUICKSTART.md` (in this directory)
- **API Reference**: `api/py/ai/chronon/README.md`

