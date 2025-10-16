# Chronon + Iceberg Quick Start

## TL;DR - What You Need

```bash
# 1. Build Chronon for Spark 3.5 (edit build.sbt first: use_spark_3_5 := true)
docker run --rm -v "$(pwd):/chronon" -w /chronon eclipse-temurin:11-jdk bash -c "
  apt-get update -qq && apt-get install -y -qq wget git build-essential libssl-dev automake libtool flex bison pkg-config g++ libboost-dev &&
  wget -q https://archive.apache.org/dist/thrift/0.13.0/thrift-0.13.0.tar.gz && tar xzf thrift-0.13.0.tar.gz && cd thrift-0.13.0 &&
  ./configure --without-python --without-java --without-go --without-ruby --without-perl --without-php --without-csharp --without-erlang --without-nodejs &&
  make -j4 && make install && cd /chronon &&
  wget -q https://github.com/sbt/sbt/releases/download/v1.8.2/sbt-1.8.2.tgz && tar xzf sbt-1.8.2.tgz &&
  ./sbt/bin/sbt 'set Global / javacOptions ++= Seq(\"-source\", \"1.8\", \"-target\", \"1.8\")' 'set Global / scalacOptions += \"-target:jvm-1.8\"' ++2.12.12 spark_uber/assembly
"

# 2. Install Java 11 in container
docker exec -it affirm-chronon-main-1 bash -c "apt-get update && apt-get install -y openjdk-11-jdk"

# 3. Upgrade Spark to 3.5.2 in container
docker exec -it affirm-chronon-main-1 bash -c "
  cd /tmp && wget -q https://archive.apache.org/dist/spark/spark-3.5.2/spark-3.5.2-bin-hadoop3.tgz && tar xzf spark-3.5.2-bin-hadoop3.tgz &&
  cd spark-3.5.2-bin-hadoop3 && for dir in bin jars python sbin; do rm -rf /opt/spark/\$dir; cp -a \$dir /opt/spark/; done
"

# 4. Copy JAR to container
docker cp spark/target/scala-2.12/spark_uber-assembly-*.jar affirm-chronon-main-1:/srv/spark/spark_embedded.jar
```

## spark_submit.sh Configuration

Add these to your `api/py/test/sample/scripts/spark_submit.sh`:

```bash
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
--master spark://spark-master:7077 \
```

## Create Source Tables

```bash
docker exec -it affirm-chronon-main-1 bash -c "
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-arm64 && export PATH=\$JAVA_HOME/bin:\$PATH
spark-sql --packages org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.10.0,org.apache.hadoop:hadoop-aws:3.3.4 \
  --conf spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions \
  --conf spark.sql.catalog.spark_catalog=org.apache.iceberg.spark.SparkCatalog \
  --conf spark.sql.catalog.spark_catalog.type=hadoop \
  --conf spark.sql.catalog.spark_catalog.warehouse=s3a://chronon/warehouse \
  --conf spark.hadoop.fs.s3a.endpoint=http://minio:9000 \
  --conf spark.hadoop.fs.s3a.path.style.access=true \
  --conf spark.hadoop.fs.s3a.access.key=minioadmin \
  --conf spark.hadoop.fs.s3a.secret.key=minioadmin \
  --conf spark.hadoop.fs.s3a.impl=org.apache.hadoop.fs.s3a.S3AFileSystem \
  -e 'CREATE DATABASE IF NOT EXISTS data; 
      CREATE TABLE IF NOT EXISTS data.purchases USING iceberg 
      AS SELECT * FROM parquet.\`s3a://chronon/warehouse/data/purchases/purchases.parquet\`;'
"
```

## Run Chronon

```bash
docker exec -it affirm-chronon-main-1 bash -c "
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-arm64 && export PATH=\$JAVA_HOME/bin:\$PATH
cd /srv/chronon && run.py --conf production/group_bys/group_bys/bootcamp/user_purchase_features.v1 --mode backfill --ds 2023-12-07
"
```

## Verify Data

```bash
docker exec -it affirm-chronon-main-1 bash -c "
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-arm64 && export PATH=\$JAVA_HOME/bin:\$PATH
spark-sql --packages org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.10.0,org.apache.hadoop:hadoop-aws:3.3.4 \
  --conf spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions \
  --conf spark.sql.catalog.spark_catalog=org.apache.iceberg.spark.SparkCatalog \
  --conf spark.sql.catalog.spark_catalog.type=hadoop \
  --conf spark.sql.catalog.spark_catalog.warehouse=s3a://chronon/warehouse \
  --conf spark.hadoop.fs.s3a.endpoint=http://minio:9000 \
  --conf spark.hadoop.fs.s3a.path.style.access=true \
  --conf spark.hadoop.fs.s3a.access.key=minioadmin \
  --conf spark.hadoop.fs.s3a.secret.key=minioadmin \
  --conf spark.hadoop.fs.s3a.impl=org.apache.hadoop.fs.s3a.S3AFileSystem \
  -e 'SELECT COUNT(*) FROM bootcamp.purchases_iceberg;'
"
```

## Key Log Messages (Success)

```
INFO CatalogUtil: Loading custom FileIO implementation: org.apache.iceberg.hadoop.HadoopFileIO
INFO AppendDataExec: Data source write support IcebergBatchWrite committed.
INFO HadoopTableOperations: Committed a new metadata file s3a://chronon/warehouse/.../metadata/v1.metadata.json
```

## Version Requirements

| Component | Version |
|-----------|---------|
| Spark | 3.5.2 |
| Iceberg | 1.10.0 |
| Hadoop-AWS | 3.3.4 |
| Java | 11 |
| Scala | 2.12.12 |

See `ICEBERG_INTEGRATION_README.md` for full documentation.

