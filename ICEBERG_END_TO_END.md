# Chronon + Iceberg + MinIO: End-to-End Tutorial

**Create features from MinIO S3 → Iceberg → Chronon aggregations → Iceberg**

---

## Prerequisites

1. **Docker environment running:**
   ```bash
   cd affirm/
   ./setup-chronon-bootcamp.sh
   ```

2. **Verify containers are up:**
   ```bash
   docker ps | grep -E "chronon|spark|minio"
   ```

3. **Custom Chronon JAR deployed** (with Iceberg partition fix):
   - JAR hash: `90b4ee2759a3ff899998450a98d97303d0a77f64`
   - Located at: `/srv/spark/spark_embedded.jar` in `chronon-main` container

---

## Step 1: Prepare Your Data in MinIO

### 1a. Upload Parquet Data to MinIO

Your raw data should be in Parquet format in MinIO. Example structure:

```
s3://chronon/warehouse/data/my_events/events.parquet
```

**Sample data schema:**
- `user_id` (STRING)
- `event_type` (STRING)
- `event_value` (DOUBLE)
- `ts` (TIMESTAMP)

### 1b. Verify Data in MinIO

Access MinIO UI at `http://localhost:9001` (user: `minioadmin`, password: `minioadmin`)

Navigate to: `chronon` bucket → `warehouse/data/my_events/`

---

## Step 2: Write Your GroupBy DSL

Create a Python file: `group_bys/myteam/my_feature_group.py`

```python
from ai.chronon.group_by import (
    GroupBy,
    Aggregation,
    Operation,
    TimeUnit,
    Window,
)
from ai.chronon.api.ttypes import EventSource
from sources import my_events_table

# Define your source
source = EventSource(
    table="myteam.events_iceberg",  # Iceberg table name
    query=Query(
        selects={
            "user_id": "user_id",
            "event_type": "event_type",
            "event_value": "event_value",
        },
        time_column="ts",
        setups=[
            # SQL to create Iceberg table from raw Parquet
            """
            CREATE TABLE IF NOT EXISTS myteam.events_iceberg 
            USING iceberg 
            AS SELECT 
              user_id, 
              event_type, 
              event_value,
              DATE_FORMAT(ts, 'yyyy-MM-dd') as ds,
              CAST(UNIX_TIMESTAMP(ts) * 1000 AS BIGINT) as ts
            FROM data.my_events
            """
        ]
    )
)

# Define aggregations
v1 = GroupBy(
    sources=[source],
    keys=["user_id"],
    aggregations=[
        # Count events in 7-day window
        Aggregation(
            input_column="event_value",
            operation=Operation.COUNT,
            windows=[Window(length=7, timeUnit=TimeUnit.DAYS)]
        ),
        # Sum values in 7-day window
        Aggregation(
            input_column="event_value",
            operation=Operation.SUM,
            windows=[Window(length=7, timeUnit=TimeUnit.DAYS)]
        ),
        # Average value in 30-day window
        Aggregation(
            input_column="event_value",
            operation=Operation.AVERAGE,
            windows=[Window(length=30, timeUnit=TimeUnit.DAYS)]
        ),
    ],
    online=True,
    output_namespace="myteam_features",
    backfill_start_date="2023-01-01"
)
```

### **CRITICAL: The `setups` SQL**

The `setups` field is where magic happens:

```sql
CREATE TABLE IF NOT EXISTS myteam.events_iceberg 
USING iceberg 
AS SELECT 
  user_id, 
  event_type, 
  event_value,
  DATE_FORMAT(ts, 'yyyy-MM-dd') as ds,           -- Partition column (required)
  CAST(UNIX_TIMESTAMP(ts) * 1000 AS BIGINT) as ts  -- Convert to millis (required)
FROM data.my_events
```

**Key requirements:**
1. **`ds` column**: Chronon expects a date partition column in format `yyyy-MM-dd`
2. **`ts` as BIGINT**: Chronon requires timestamp in Unix milliseconds (LONG type)
3. **`DATE_FORMAT` before `CAST`**: SQL evaluates left-to-right, so extract `ds` from original `ts` timestamp before converting

---

## Step 3: Compile Your GroupBy

```bash
docker exec affirm-chronon-main-1 bash -c "
  cd /srv/chronon && 
  python3 compile.py \
    --input_path=group_bys/myteam/my_feature_group.py \
    --output_path=production/group_bys
"
```

This generates a `.v1` JSON file in `production/group_bys/group_bys/myteam/`

---

## Step 4: Run the Backfill

```bash
docker exec affirm-chronon-main-1 bash -c "
  export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-arm64 && 
  export PATH=\$JAVA_HOME/bin:\$PATH && 
  cd /srv/chronon && 
  run.py --mode backfill --conf production/group_bys/group_bys/myteam/my_feature_group.v1
"
```

**What happens:**
1. **Setup phase**: Creates `myteam.events_iceberg` table from raw Parquet in MinIO
2. **Aggregation phase**: Processes data in date ranges (e.g., `[2023-01-01...2023-01-30]`)
3. **Write phase**: Writes aggregated features to `myteam_features.myteam_my_feature_group_v1` in Iceberg format

**Expected output:**
```
Computing group by for range: [2023-01-01...2023-01-30] [1/23]
IcebergBatchWrite(table=myteam_features.myteam_my_feature_group_v1) committed.
addedRecords=CounterResult{value=1500}
...
SparkContext is stopping with exitCode 0.
```

---

## Step 5: Verify Results

### 5a. Check Output Table Exists

```bash
docker exec affirm-chronon-main-1 bash -c "
  export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-arm64 && 
  export PATH=\$JAVA_HOME/bin:\$PATH && 
  spark-sql \
    --packages org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.10.0,org.apache.hadoop:hadoop-aws:3.3.4 \
    --conf spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions \
    --conf spark.sql.catalog.spark_catalog=org.apache.iceberg.spark.SparkCatalog \
    --conf spark.sql.catalog.spark_catalog.type=hadoop \
    --conf spark.sql.catalog.spark_catalog.warehouse=s3a://chronon/warehouse \
    --conf spark.hadoop.fs.s3a.endpoint=http://minio:9000 \
    --conf spark.hadoop.fs.s3a.path.style.access=true \
    --conf spark.hadoop.fs.s3a.access.key=minioadmin \
    --conf spark.hadoop.fs.s3a.secret.key=minioadmin \
    --conf spark.hadoop.fs.s3a.impl=org.apache.hadoop.fs.s3a.S3AFileSystem \
    -e 'DESCRIBE EXTENDED myteam_features.myteam_my_feature_group_v1;'
" | grep -E "Provider|Location"
```

**Expected:**
```
Provider    iceberg
Location    s3a://chronon/warehouse/myteam_features/myteam_my_feature_group_v1
```

### 5b. Query Your Features

```bash
docker exec affirm-chronon-main-1 bash -c "
  export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-arm64 && 
  export PATH=\$JAVA_HOME/bin:\$PATH && 
  spark-sql \
    --packages org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.10.0,org.apache.hadoop:hadoop-aws:3.3.4 \
    --conf spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions \
    --conf spark.sql.catalog.spark_catalog=org.apache.iceberg.spark.SparkCatalog \
    --conf spark.sql.catalog.spark_catalog.type=hadoop \
    --conf spark.sql.catalog.spark_catalog.warehouse=s3a://chronon/warehouse \
    --conf spark.hadoop.fs.s3a.endpoint=http://minio:9000 \
    --conf spark.hadoop.fs.s3a.path.style.access=true \
    --conf spark.hadoop.fs.s3a.access.key=minioadmin \
    --conf spark.hadoop.fs.s3a.secret.key=minioadmin \
    --conf spark.hadoop.fs.s3a.impl=org.apache.hadoop.fs.s3a.S3AFileSystem \
    -e 'SELECT * FROM myteam_features.myteam_my_feature_group_v1 LIMIT 10;'
"
```

**Expected output:**
```
user_123  2023-01-15  42.5   15    1250.75
user_456  2023-01-15  31.2   8     950.00
...
```

### 5c. View in MinIO UI

1. Open `http://localhost:9001`
2. Navigate to: `chronon` bucket → `warehouse/myteam_features/myteam_my_feature_group_v1/`
3. You'll see:
   - `metadata/` - Iceberg metadata files
   - `data/` - Parquet data files
   - Partitioned by `ds` date

---

## Data Flow Summary

```
┌─────────────────────────────────────────────────────┐
│  1. RAW DATA (Parquet in MinIO)                     │
│     s3://chronon/warehouse/data/my_events/          │
└────────────────────┬────────────────────────────────┘
                     │
                     │ SQL setup (in GroupBy DSL)
                     ▼
┌─────────────────────────────────────────────────────┐
│  2. ICEBERG INPUT TABLE                              │
│     myteam.events_iceberg                            │
│     Provider: iceberg                                │
│     Location: s3a://chronon/warehouse/...           │
└────────────────────┬────────────────────────────────┘
                     │
                     │ Chronon aggregations (COUNT, SUM, AVG)
                     ▼
┌─────────────────────────────────────────────────────┐
│  3. SPARK PROCESSING                                 │
│     - 7-day rolling windows                          │
│     - 30-day rolling windows                         │
│     - Grouped by user_id                             │
└────────────────────┬────────────────────────────────┘
                     │
                     │ Write to Iceberg
                     ▼
┌─────────────────────────────────────────────────────┐
│  4. ICEBERG OUTPUT TABLE (FEATURES)                  │
│     myteam_features.myteam_my_feature_group_v1       │
│     Provider: iceberg                                │
│     Location: s3a://chronon/warehouse/...           │
└─────────────────────────────────────────────────────┘
```

---

## Common Patterns

### Pattern 1: Simple Event Count

```python
Aggregation(
    input_column="event_value",
    operation=Operation.COUNT,
    windows=[Window(length=7, timeUnit=TimeUnit.DAYS)]
)
```

### Pattern 2: Sum with Multiple Windows

```python
Aggregation(
    input_column="purchase_amount",
    operation=Operation.SUM,
    windows=[
        Window(length=1, timeUnit=TimeUnit.DAYS),
        Window(length=7, timeUnit=TimeUnit.DAYS),
        Window(length=30, timeUnit=TimeUnit.DAYS),
    ]
)
```

### Pattern 3: Average with Filtering

```python
# In your SQL setup, filter before creating Iceberg table:
"""
CREATE TABLE IF NOT EXISTS myteam.filtered_events 
USING iceberg 
AS SELECT 
  user_id, 
  event_value,
  DATE_FORMAT(ts, 'yyyy-MM-dd') as ds,
  CAST(UNIX_TIMESTAMP(ts) * 1000 AS BIGINT) as ts
FROM data.my_events
WHERE event_type = 'purchase' AND event_value > 0
"""
```

---

## Troubleshooting

### Error: "Column `ds` cannot be resolved"

**Fix**: Add `ds` column in your `setups` SQL:
```sql
DATE_FORMAT(ts, 'yyyy-MM-dd') as ds
```

### Error: "Time column ts doesn't exist (or is not a LONG type)"

**Fix**: Convert timestamp to Unix milliseconds:
```sql
CAST(UNIX_TIMESTAMP(ts) * 1000 AS BIGINT) as ts
```

### Error: "Table or view not found"

**Fix**: Verify your raw Parquet data exists in MinIO at the path specified in the `FROM` clause.

### Job succeeds but no data

**Check**:
1. Date range: Make sure `backfill_start_date` matches your data dates
2. Data in input: Query the Iceberg input table directly to verify data loaded
3. Logs: Look for "addedRecords=0" in the Iceberg commit logs

---

## Example: Full Working GroupBy

See `group_bys/bootcamp/user_purchase_features.py` for a complete example that processes purchase data with:
- 1-day and 7-day windows
- COUNT, SUM, and AVERAGE operations
- Event filtering and column selection

**Verify it works:**
```bash
docker exec affirm-chronon-main-1 bash -c "
  export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-arm64 && 
  export PATH=\$JAVA_HOME/bin:\$PATH && 
  cd /srv/chronon && 
  run.py --mode backfill --conf production/group_bys/group_bys/bootcamp/user_purchase_features.v1
"
```

Output should show 700 aggregated feature rows written to Iceberg! 🎉

---

## Next Steps

1. **Try with your own data**: Replace `my_events` with your actual MinIO path
2. **Add more aggregations**: Experiment with `LAST`, `FIRST`, `MIN`, `MAX`
3. **Create Joins**: Combine multiple GroupBys with `Join` definitions
4. **Online serving**: Enable real-time feature serving with MongoDB KV store

For more details on Chronon DSL, see `group_bys/bootcamp/README.md`

