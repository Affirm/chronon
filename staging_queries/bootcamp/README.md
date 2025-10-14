# Bootcamp Staging Queries

This directory contains staging queries that read data from S3 (MinIO) parquet files and materialize them into Iceberg tables for use by Chronon GroupBys.

## Overview

Staging queries are preprocessing steps that:
1. Read raw data from S3/MinIO parquet files
2. Transform and clean the data (if needed)
3. Write the data to Iceberg tables in a partitioned format
4. Make the data available for GroupBy feature computation

## Files

### `purchases_from_s3.py`

Reads purchase data from S3 and writes to an Iceberg table.

**Source**: `s3a://chronon/warehouse/data/purchases/purchases.parquet`  
**Output**: `bootcamp.purchases_from_s3` (Iceberg table)

## Running Staging Queries

### 1. Run the Staging Query

First, execute the staging query to materialize S3 data into Iceberg:

```bash
# From the chronon-main container
docker-compose -f affirm/docker-compose-bootcamp.yml exec chronon-main bash

# Run the staging query backfill
run.py --mode=staging-query-backfill \
    --conf=staging_queries/bootcamp/purchases_from_s3.py

# Optional: specify date range
run.py --mode=staging-query-backfill \
    --conf=staging_queries/bootcamp/purchases_from_s3.py \
    --start-date=2023-12-01 \
    --end-date=2023-12-07
```

### 2. Verify the Iceberg Table

```bash
# Check that the Iceberg table was created
spark-sql -e "SHOW TABLES IN bootcamp"

# View the data
spark-sql -e "SELECT * FROM bootcamp.purchases_from_s3 LIMIT 10"

# Check record count
spark-sql -e "SELECT COUNT(*) FROM bootcamp.purchases_from_s3"
```

### 3. Run the GroupBy

Once the staging query has materialized the data, you can run the GroupBy:

```bash
run.py --mode=backfill \
    --conf=group_bys/bootcamp/user_purchase_features.py
```

## Data Flow

```
┌─────────────────────┐
│  S3/MinIO Storage   │
│  purchases.parquet  │
└──────────┬──────────┘
           │
           │ StagingQuery reads
           │ (via spark.read.parquet)
           ↓
┌─────────────────────┐
│  Staging Query      │
│  purchases_from_s3  │
└──────────┬──────────┘
           │
           │ Writes to Iceberg
           ↓
┌─────────────────────┐
│  Iceberg Table      │
│  bootcamp.          │
│  purchases_from_s3  │
└──────────┬──────────┘
           │
           │ GroupBy reads
           ↓
┌─────────────────────┐
│  GroupBy Features   │
│  user_purchase_     │
│  features           │
└─────────────────────┘
```

## Configuration Details

### Table Properties for Iceberg

The staging query specifies these table properties:

```python
tableProperties={
    "provider": "iceberg",
    "format-version": "2",
    "write.format.default": "parquet"
}
```

This ensures the output table is created in Iceberg format.

### Dependencies

The GroupBy automatically depends on the staging query output. Chronon will:
1. Wait for the staging query partition to be ready
2. Then execute the GroupBy backfill

## Troubleshooting

### Staging Query Fails

If the staging query fails:

1. **Check S3 connectivity**:
   ```bash
   spark-sql -e "SELECT * FROM parquet.\`s3a://chronon/warehouse/data/purchases/purchases.parquet\` LIMIT 5"
   ```

2. **Check MinIO is accessible**:
   ```bash
   curl http://minio:9000/minio/health/live
   ```

3. **View staging query logs**:
   ```bash
   docker-compose -f affirm/docker-compose-bootcamp.yml logs chronon-main
   ```

### GroupBy Can't Find Table

If the GroupBy can't find the Iceberg table:

1. **Verify staging query completed**:
   ```bash
   spark-sql -e "SHOW TABLES IN bootcamp"
   ```

2. **Check table exists**:
   ```bash
   spark-sql -e "DESCRIBE EXTENDED bootcamp.purchases_from_s3"
   ```

### Performance Issues

For large datasets:

1. Adjust Spark configuration in the staging query's `metaData.modeToEnvMap`
2. Consider partitioning strategy
3. Adjust parallelism settings

## Next Steps

After successfully running the staging query and GroupBy:

1. Check the computed features in the output table
2. Test online feature serving (if `online=True`)
3. Create additional staging queries for other data sources (e.g., users data)
4. Create joins that combine multiple GroupBys

