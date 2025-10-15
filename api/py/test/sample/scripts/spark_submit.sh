#!/usr/bin/env bash

#
#    Copyright (C) 2023 The Chronon Authors.
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.
#

### ******************* NOTE ***************************
### This is just a template, you will most likely need to modify this file to get things to work

### Consider adding the following arguments to spark submit in your prod env. We do not include them by default, because it can cause issues on local runs on M1 Macbooks.
###--conf spark.io.compression.codec=zstd \
###--conf spark.io.compression.zstd.level=2 \
###--conf spark.io.compression.zstd.bufferSize=1M \

### ******************* END ****************************

set -euxo pipefail
CHRONON_WORKING_DIR=${CHRONON_TMPDIR:-/tmp}/${USER}
mkdir -p ${CHRONON_WORKING_DIR}
export TEST_NAME="${APP_NAME}_${USER}_test"
unset PYSPARK_DRIVER_PYTHON
unset PYSPARK_PYTHON
unset SPARK_HOME
unset SPARK_CONF_DIR
export LOG4J_FILE="${CHRONON_WORKING_DIR}/log4j_file"
cat > ${LOG4J_FILE} << EOF
log4j.rootLogger=INFO, stdout
log4j.appender.stdout=org.apache.log4j.ConsoleAppender
log4j.appender.stdout.Target=System.out
log4j.appender.stdout.layout=org.apache.log4j.PatternLayout
log4j.appender.stdout.layout.ConversionPattern=%d{yyyy-MM-dd HH:mm:ss} %-5p %c{1}:%L - %m%n
log4j.appender.stdout.layout.ConversionPattern=[%d{yyyy-MM-dd HH:mm:ss}] {%c{1}} %L - %m%n
log4j.logger.ai.chronon=INFO
EOF
$SPARK_SUBMIT_PATH \
--packages org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.10.0,org.apache.hadoop:hadoop-aws:3.3.6 \
--driver-java-options " -Dlog4j.configuration=file:${LOG4J_FILE}" \
--conf "spark.executor.extraJavaOptions= -XX:ParallelGCThreads=4 -XX:+UseParallelGC -XX:+UseCompressedOops" \
--conf spark.sql.shuffle.partitions=${PARALLELISM:-4000} \
--conf spark.dynamicAllocation.maxExecutors=${MAX_EXECUTORS:-1000} \
--conf spark.default.parallelism=${PARALLELISM:-4000} \
--conf spark.local.dir=${CHRONON_WORKING_DIR} \
--conf spark.jars.ivy=${CHRONON_WORKING_DIR} \
--conf spark.executor.cores=${EXECUTOR_CORES:-1} \
--conf spark.chronon.partition.column="${PARTITION_COLUMN:-ds}" \
--conf spark.chronon.partition.format="${PARTITION_FORMAT:-yyyy-MM-dd}" \
--conf spark.chronon.backfill.validation.enabled="${ENABLE_VALIDATION:-false}" \
--conf spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions \
--conf spark.sql.catalog.spark_catalog=org.apache.iceberg.spark.SparkCatalog \
--conf spark.sql.catalog.spark_catalog.type=rest \
--conf spark.sql.catalog.spark_catalog.uri=http://polaris:8181/api/catalog \
--conf spark.sql.catalog.spark_catalog.warehouse=s3a://chronon/warehouse \
--conf spark.sql.catalog.spark_catalog.io-impl=org.apache.iceberg.aws.s3.S3FileIO \
--conf spark.hadoop.fs.s3a.endpoint=http://minio:9000 \
--conf spark.hadoop.fs.s3a.path.style.access=true \
--conf spark.hadoop.fs.s3a.access.key=minioadmin \
--conf spark.hadoop.fs.s3a.secret.key=minioadmin \
--conf spark.hadoop.fs.s3a.impl=org.apache.hadoop.fs.s3a.S3AFileSystem \
--deploy-mode client \
--master "${JOB_MODE:-spark://spark-master:7077}" \
--executor-memory "${EXECUTOR_MEMORY:-2G}" \
--driver-memory "${DRIVER_MEMORY:-1G}" \
--conf spark.app.name=${APP_NAME} \
--conf spark.chronon.outputParallelismOverride=${OUTPUT_PARALLELISM:--1} \
--conf spark.chronon.rowCountPerPartition=${ROW_COUNT_PER_PARTITION:--1} \
--jars "${CHRONON_ONLINE_JAR:-}" \
"$@" 2>&1                                                  |
grep --line-buffered -v "YarnScheduler:70"                 |
grep --line-buffered -v "TransportResponseHandler:144"     |
grep --line-buffered -v "TransportClient:331"              |
grep --line-buffered -v "io.netty.channel.AbstractChannel" |
grep --line-buffered -v "ClosedChannelException"           |
grep --line-buffered -v "TransportResponseHandler:154"     |
grep --line-buffered -v "TransportRequestHandler:293"      |
grep --line-buffered -v "TransportResponseHandler:144"     |
tee ${CHRONON_WORKING_DIR}/${APP_NAME}_spark.log



