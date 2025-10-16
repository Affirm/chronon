package ai.chronon.spark

import org.apache.spark.sql.SparkSession
import org.slf4j.LoggerFactory

import scala.util.Try

/**
 * Custom FormatProvider factory that properly detects Iceberg tables with Hadoop catalog
 */
object IcebergFormatProvider {
  def apply(sparkSession: SparkSession): FormatProvider = 
    IcebergFormatProviderImpl(sparkSession)
}

case class IcebergFormatProviderImpl(sparkSession: SparkSession) extends FormatProvider {
  @transient lazy val logger = LoggerFactory.getLogger(getClass)

  override def readFormat(tableName: String): Format = {
    if (isIcebergTable(tableName)) {
      Iceberg
    } else if (isDeltaTable(tableName)) {
      DeltaLake
    } else if (isView(tableName)) {
      View
    } else {
      Hive
    }
  }

  // Better Iceberg detection that works with Hadoop catalog
  private def isIcebergTable(tableName: String): Boolean = {
    Try {
      // Check if the table's provider is Iceberg
      val describeResult = sparkSession.sql(s"DESCRIBE TABLE EXTENDED $tableName")
      val provider = describeResult
        .filter(org.apache.spark.sql.functions.lower(org.apache.spark.sql.functions.col("col_name")) === "provider")
        .select("data_type")
        .collect()
        .headOption
        .map(_.getString(0).toLowerCase)

      provider.contains("iceberg")
    } match {
      case scala.util.Success(true) =>
        logger.info(s"IcebergCheck: Detected iceberg formatted table $tableName via DESCRIBE EXTENDED.")
        true
      case scala.util.Success(false) =>
        logger.info(s"IcebergCheck: Table $tableName provider is not iceberg.")
        false
      case scala.util.Failure(e) =>
        logger.info(s"IcebergCheck: Unable to check table $tableName format: ${e.getMessage}")
        false
    }
  }

  private def isDeltaTable(tableName: String): Boolean = {
    Try {
      val describeResult = sparkSession.sql(s"DESCRIBE DETAIL $tableName")
      describeResult.select("format").first().getString(0).toLowerCase
    } match {
      case scala.util.Success(format) =>
        logger.info(s"Delta check: Successfully read the format of table: $tableName as $format")
        format == "delta"
      case _ =>
        logger.info(s"Delta check: Unable to read the format of the table $tableName using DESCRIBE DETAIL")
        false
    }
  }

  private def isView(tableName: String): Boolean = {
    Try {
      val describeResult = sparkSession.sql(s"DESCRIBE TABLE EXTENDED $tableName")
      describeResult
        .filter(org.apache.spark.sql.functions.lower(org.apache.spark.sql.functions.col("col_name")) === "type")
        .select("data_type")
        .collect()
        .headOption
        .exists(row => row.getString(0).toLowerCase.contains("view"))
    } match {
      case scala.util.Success(isView) =>
        logger.info(s"View check: Table: $tableName is view: $isView")
        isView
      case _ =>
        logger.info(s"View check: Unable to check if the table $tableName is a view using DESCRIBE TABLE EXTENDED")
        false
    }
  }

  override def writeFormat(tableName: String): Format = {
    val useIceberg: Boolean = sparkSession.conf.get("spark.chronon.table_write.iceberg", "false").toBoolean

    val maybeFormat = sparkSession.conf.getOption("spark.chronon.table_write.format").map(_.toLowerCase) match {
      case Some("hive")    => Some(Hive)
      case Some("iceberg") => Some(Iceberg)
      case Some("delta")   => Some(DeltaLake)
      case _               => None
    }
    (useIceberg, maybeFormat) match {
      case (true, _)             => Iceberg
      case (false, Some(format)) => format
      case (false, None)         => Hive
    }
  }
}

