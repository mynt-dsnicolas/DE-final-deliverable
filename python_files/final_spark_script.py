from pyspark.sql import SparkSession
import pyspark.sql.functions as F

spark = SparkSession.builder.getOrCreate()

payment_df = spark.read.csv('/input/*.csv', inferSchema=True, header=True)

( 
    payment_df
        .groupby(F.expr("date_trunc('day', timestamp)").alias('day'))
            .agg(
            F.sum(F.col("amount")).alias("total_amount")
            )
).coalesce(1).write.mode("overwrite").csv('/output-airflow/payment_total_amount.csv', header=True)
