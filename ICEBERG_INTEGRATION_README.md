# Chronon + Iceberg + MinIO Integration Guide

## Overview

This guide documents the complete process to integrate Apache Iceberg table format with Chronon, using MinIO as the S3-compatible storage backend.

## What Was Achieved

✅ Built Chronon for **Spark 3.5** (upgraded from 3.1)  
✅ Integrated **Apache Iceberg 1.10.0** table format  
✅ Connected to **MinIO** S3-compatible storage  
✅ Chronon successfully writes data to Iceberg tables in MinIO  
⚠️ Aggregation pipeline incomplete (partition check error - data writes successfully)

## Architecture

```
Raw Data (S3/MinIO)
    ↓
Apache Iceberg (table format with versioning/metadata)
    ↓
Chronon Feature Engineering (reads from Iceberg)
    ↓
Chronon Computes Features (aggregations, windows)
    ↓
Chronon Writes to Iceberg Tables
    ↓
Iceberg Tables in MinIO (s3a://chronon/warehouse/)
```

## Prerequisites

- Docker & Docker Compose
- Spark Cluster running version 3.5.2
- MinIO running and accessible
- ~15-20 minutes for initial build

## Version Compatibility Matrix

| Component | Version | Required | Notes |
|-----------|---------|----------|-------|
| Spark | 3.5.2 | Yes | Cluster & Driver must match |
| Iceberg | 1.10.0 | Yes | Requires Java 11+ |
| Hadoop-AWS | 3.3.4 | Yes | Must match Spark's Hadoop version |
| Scala | 2.12.12 | Yes | Chronon requirement |
| Java (Build) | 11 | Yes | For compiling Chronon |
| Java (Runtime) | 11 | Yes | For Iceberg runtime |
| Thrift | 0.13.0 | Yes | Must match libthrift version |
| SBT | 1.8.2 | No | Any recent version works |

## Step 1: Build Chronon for Spark 3.5

### 1.1 Configure Build

Edit `build.sbt` (around line 47):

```scala
val use_spark_3_5 = settingKey[Boolean]("Flag to build for 3.5")
ThisBuild / use_spark_3_5 := true  // SET TO TRUE
```

Also comment out the Python API build (around line 269) to avoid build issues:

```scala
// sourceGenerators in Compile += python_api_build.taskValue,
```

### 1.2 Build with Docker (Recommended)

This approach avoids local environment issues:

```bash
cd /path/to/chronon-1

docker run --rm -v "$(pwd):/chronon" -w /chronon eclipse-temurin:11-jdk bash -c "
  # Install dependencies
  apt-get update -qq && 
  apt-get install -y -qq wget git build-essential libssl-dev automake \
    libtool flex bison pkg-config g++ libboost-dev > /dev/null 2>&1 &&
  
  # Install Thrift 0.13.0 (must match libthrift version)
  wget -q https://archive.apache.org/dist/thrift/0.13.0/thrift-0.13.0.tar.gz &&
  tar xzf thrift-0.13.0.tar.gz &&
  cd thrift-0.13.0 &&
  ./configure --without-python --without-java --without-go --without-ruby \
    --without-perl --without-php --without-csharp --without-erlang \
    --without-nodejs > /dev/null 2>&1 &&
  make -j4 > /dev/null 2>&1 &&
  make install > /dev/null 2>&1 &&
  
  cd /chronon &&
  
  # Download SBT
  wget -q https://github.com/sbt/sbt/releases/download/v1.8.2/sbt-1.8.2.tgz &&
  tar xzf sbt-1.8.2.tgz &&
  
  # Build with Java 8 bytecode compatibility (for Spark compatibility)
  ./sbt/bin/sbt \
    'set Global / javacOptions ++= Seq(\"-source\", \"1.8\", \"-target\", \"1.8\")' \
    'set Global / scalacOptions += \"-target:jvm-1.8\"' \
    ++2.12.12 spark_uber/assembly
"
```

**Build time:** 10-15 minutes

**Output JAR location:**
```
spark/target/scala-2.12/spark_uber-assembly-<branch>-<version>-SNAPSHOT.jar
```

### 1.3 Build Success Indicators

Look for this at the end of the build output:

```
[info] Built: /chronon/spark/target/scala-2.12/spark_uber-assembly-*.jar
[success] Total time: 60-90 s
```

## Step 2: Update Container Environment

### 2.1 Copy New JAR to Container

```bash
docker cp spark/target/scala-2.12/spark_uber-assembly-*.jar \
  affirm-chronon-main-1:/srv/spark/spark_embedded.jar
```

### 2.2 Upgrade Spark in Chronon Container

The chronon-main container needs Spark 3.5.2 to match the cluster:

```bash
docker exec -it affirm-chronon-main-1 bash -c "
  cd /tmp &&
  wget -q https://archive.apache.org/dist/spark/spark-3.5.2/spark-3.5.2-bin-hadoop3.tgz &&
  tar xzf spark-3.5.2-bin-hadoop3.tgz &&
  
  # Replace Spark binaries (preserve spark-events volume)
  cd spark-3.5.2-bin-hadoop3 &&
  for dir in bin jars python sbin; do
    rm -rf /opt/spark/\$dir 2>/dev/null || true
    cp -a \$dir /opt/spark/
  done &&
  
  echo 'Spark 3.5.2 installed successfully'
"
```

### 2.3 Install Java 11 in Container

Iceberg 1.10.0 requires Java 11+:

```bash
docker exec -it affirm-chronon-main-1 bash -c "
  apt-get update -qq &&
  apt-get install -y -qq openjdk-11-jdk &&
  update-alternatives --set java /usr/lib/jvm/java-11-openjdk-arm64/bin/java &&
  java -version
"
```

You should see: `openjdk version "11.0.x"`

## Step 3: Configure Spark Submit for Iceberg

### 3.1 Update spark_submit.sh

Edit `api/py/test/sample/scripts/spark_submit.sh`:

```bash
#!/usr/bin/env bash

# ... existing configuration ...

$SPARK_SUBMIT_PATH \
# Add Iceberg + Hadoop-AWS packages
--packages org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.10.0,org.apache.hadoop:hadoop-aws:3.3.4 \

# ... existing configs ...

# Add Iceberg SQL Extensions
--conf spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions \
--conf spark.sql.catalog.spark_catalog=org.apache.iceberg.spark.SparkCatalog \

# Hadoop Catalog (file-based, works with S3/MinIO)
--conf spark.sql.catalog.spark_catalog.type=hadoop \
--conf spark.sql.catalog.spark_catalog.warehouse=s3a://chronon/warehouse \

# MinIO S3 Configuration
--conf spark.hadoop.fs.s3a.endpoint=http://minio:9000 \
--conf spark.hadoop.fs.s3a.path.style.access=true \
--conf spark.hadoop.fs.s3a.access.key=minioadmin \
--conf spark.hadoop.fs.s3a.secret.key=minioadmin \
--conf spark.hadoop.fs.s3a.impl=org.apache.hadoop.fs.s3a.S3AFileSystem \

# Point to Spark cluster (not local)
--master spark://spark-master:7077 \

"$@"
```

### 3.2 Copy Updated Script to Container

```bash
docker cp api/py/test/sample/scripts/spark_submit.sh \
  affirm-chronon-main-1:/srv/chronon/scripts/spark_submit.sh
```

## Step 4: Create Iceberg Source Tables

Before running Chronon, source data must be available as Iceberg tables.

### 4.1 Create Source Tables

```bash
docker exec -it affirm-chronon-main-1 bash -c "
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-arm64
export PATH=\$JAVA_HOME/bin:\$PATH

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
  -e '
    -- Create database
    CREATE DATABASE IF NOT EXISTS data;
    
    -- Create Iceberg table from existing parquet data in MinIO
    CREATE TABLE IF NOT EXISTS data.purchases 
    USING iceberg 
    AS SELECT * FROM parquet.\`s3a://chronon/warehouse/data/purchases/purchases.parquet\`;
    
    -- Verify data loaded
    SELECT COUNT(*) as record_count FROM data.purchases;
  '
"
```

**Expected output:** Shows the count of records loaded

### 4.2 Verify Tables Created

```bash
docker exec -it affirm-chronon-main-1 bash -c "
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-arm64
export PATH=\$JAVA_HOME/bin:\$PATH

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
  -e 'SHOW TABLES IN data;'
"
```

## Step 5: Run Chronon with Iceberg

### 5.1 Execute Chronon Job

```bash
docker exec -it affirm-chronon-main-1 bash -c "
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-arm64
export PATH=\$JAVA_HOME/bin:\$PATH

cd /srv/chronon
run.py \
  --conf production/group_bys/group_bys/bootcamp/user_purchase_features.v1 \
  --mode backfill \
  --ds 2023-12-07
"
```

### 5.2 Monitor for Success Indicators

Look for these log messages:

```
INFO CatalogUtil: Loading custom FileIO implementation: org.apache.iceberg.hadoop.HadoopFileIO
INFO AppendDataExec: Data source write support IcebergBatchWrite(table=bootcamp.purchases_iceberg, format=PARQUET) committed.
INFO HadoopTableOperations: Committed a new metadata file s3a://chronon/warehouse/bootcamp/purchases_iceberg/metadata/v1.metadata.json
```

## Step 6: Verify Iceberg Data

### 6.1 Query the Table

```bash
docker exec -it affirm-chronon-main-1 bash -c "
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-arm64
export PATH=\$JAVA_HOME/bin:\$PATH

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
  -e 'SELECT * FROM bootcamp.purchases_iceberg LIMIT 10;'
"
```

### 6.2 Check Table Metadata

```bash
docker exec -it affirm-chronon-main-1 bash -c "
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-arm64
export PATH=\$JAVA_HOME/bin:\$PATH

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
  -e 'DESCRIBE EXTENDED bootcamp.purchases_iceberg;'
"
```

Should show:
- Table type: `MANAGED`
- Provider: `iceberg`
- Location: `s3a://chronon/warehouse/bootcamp/purchases_iceberg`
- Format: `iceberg/parquet`

### 6.3 Check Iceberg Snapshots (Version History)

```bash
docker exec -it affirm-chronon-main-1 bash -c "
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-arm64
export PATH=\$JAVA_HOME/bin:\$PATH

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
  -e 'SELECT * FROM bootcamp.purchases_iceberg.snapshots;'
"
```

Shows version history with:
- Snapshot IDs
- Timestamp of each write
- Operation type (append, overwrite, etc.)
- Statistics (files added, records added, etc.)

### 6.4 View in MinIO Browser

1. Open browser: `http://localhost:9001`
2. Login with credentials (default: minioadmin/minioadmin)
3. Navigate to bucket: `chronon`
4. Browse to: `warehouse/bootcamp/purchases_iceberg/`
5. You should see:
   - `data/` folder: Contains Parquet data files
   - `metadata/` folder: Contains Iceberg metadata JSON and Avro files

## Known Issues & Workarounds

### Issue 1: Partition Check Fails After Data Write

**Symptoms:**
- Job exits with error after data is successfully written
- Error message: `TABLE_OR_VIEW_NOT_FOUND` when checking partitions
- Data is visible in MinIO and can be queried

**Root Cause:**
Chronon's partition detection logic doesn't recognize Iceberg table format

**Status:**
- ✅ Data writes successfully to Iceberg
- ❌ Job fails on partition validation step
- ❌ Aggregations may not complete

**Workaround:**
- Data is successfully in Iceberg format
- Can be queried with Spark SQL
- May need to disable partition checks or fix Chronon's Iceberg detection

### Issue 2: Thrift Version Mismatch

**Symptoms:**
- Build errors: `method readMapBegin in class TCompactProtocol cannot be applied`
- Java compilation errors about method signatures

**Root Cause:**
Generated Thrift code doesn't match runtime library version

**Solution:**
Use Thrift compiler version 0.13.0 (matches `libthrift` version in dependencies)

### Issue 3: Java Version Conflicts

**Symptoms:**
- `UnsupportedClassVersionError: class file version 55.0`
- Errors about unrecognized class file versions

**Root Cause:**
- Iceberg 1.10.0 requires Java 11+
- Container may have Java 8

**Solution:**
Install Java 11 in container and set `JAVA_HOME` before running commands

### Issue 4: Hadoop Version Mismatch

**Symptoms:**
- `ClassNotFoundException: org.apache.hadoop.fs.impl.prefetch.PrefetchingStatistics`

**Root Cause:**
Mismatched `hadoop-aws` version with Spark's Hadoop

**Solution:**
Use `hadoop-aws:3.3.4` to match Spark 3.5.2's Hadoop version

### Issue 5: SBT Cache Corruption

**Symptoms:**
- `bad constant pool index` errors
- `Could not initialize class sbt.internal.parser.SbtParser$`

**Root Cause:**
Corrupted SBT/Ivy caches on local machine

**Solution:**
Build in Docker with clean environment (recommended approach)

## Troubleshooting

### Check Spark Versions Match

```bash
# Check Spark Master
docker exec affirm-spark-master-1 cat /opt/spark/RELEASE

# Check Chronon container
docker exec affirm-chronon-main-1 spark-submit --version
```

Both should show: `Spark 3.5.2`

### Check Java Version

```bash
docker exec affirm-chronon-main-1 java -version
```

Should show: `openjdk version "11.0.x"`

### Check Iceberg Integration

```bash
docker exec affirm-chronon-main-1 bash -c "
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-arm64
spark-sql \
  --packages org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.10.0 \
  -e 'SELECT 1;'
"
```

Should download Iceberg JARs and execute successfully

### View Chronon Logs

```bash
docker logs affirm-chronon-main-1 --tail 100
```

### View Spark Worker Logs

```bash
docker logs affirm-spark-worker-1 --tail 100
```

## Success Criteria

✅ **Chronon JAR compiled for Spark 3.5**  
✅ **Iceberg runtime loaded** (check for "Loading custom FileIO" log)  
✅ **Tables created in MinIO** (visible in browser)  
✅ **Metadata files present** (`metadata/*.json` in MinIO)  
✅ **Data files present** (`data/*.parquet` in MinIO)  
✅ **Can query tables** with Spark SQL  
✅ **Version history works** (snapshots table has entries)  

⚠️ **Full aggregation pipeline** may fail on partition check (data still writes successfully)

## Benefits of Iceberg Integration

1. **ACID Transactions**: Atomic commits, no partial writes
2. **Time Travel**: Query data as of any snapshot
3. **Schema Evolution**: Add/remove columns safely
4. **Hidden Partitioning**: Partition pruning without user awareness
5. **Metadata Management**: Efficient metadata operations
6. **S3 Compatible**: Works with MinIO, AWS S3, or any S3 API

## Next Steps

1. **Fix Partition Detection**: Update Chronon to recognize Iceberg table format in partition checks
2. **Enable Full Aggregations**: Resolve partition validation to complete feature computation
3. **Add Polaris Catalog**: Migrate from Hadoop catalog to REST catalog (Apache Polaris) for better governance
4. **Optimize Performance**: Configure Iceberg table properties for your workload
5. **Set Up Time Travel**: Configure snapshot retention policies

## Additional Resources

- [Apache Iceberg Documentation](https://iceberg.apache.org/)
- [Iceberg Spark Integration](https://iceberg.apache.org/docs/latest/spark-configuration/)
- [Chronon Documentation](https://chronon.ai/)
- [MinIO Documentation](https://min.io/docs/)

## Quick Reference: Environment Variables

Always set these before running Chronon commands:

```bash
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-arm64
export PATH=$JAVA_HOME/bin:$PATH
```

## Files Modified

1. `build.sbt` - Enable Spark 3.5 compilation
2. `api/py/test/sample/scripts/spark_submit.sh` - Add Iceberg configurations
3. Container: Spark binaries upgraded to 3.5.2
4. Container: Java 11 installed
5. Container: Chronon JAR updated

---

**Last Updated:** October 15, 2025  
**Chronon Version:** Latest (mburack-newIcebergInt branch)  
**Spark Version:** 3.5.2  
**Iceberg Version:** 1.10.0

