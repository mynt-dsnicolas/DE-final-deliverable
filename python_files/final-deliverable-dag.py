from datetime import datetime, timedelta

import airflow
from airflow import DAG
from postgres_s3_lib.postgres_to_s3_operator import PostgresToS3Operator
from airflow.providers.amazon.aws.transfers.s3_to_redshift import S3ToRedshiftOperator
from airflow.operators.dummy_operator import DummyOperator
from airflow.contrib.operators.emr_add_steps_operator import EmrAddStepsOperator
from airflow.contrib.sensors.emr_step_sensor import EmrStepSensor
from airflow.operators.latest_only_operator import LatestOnlyOperator

SPARK_STEPS = [
    {
        "Name": "Copy data and spark script from bucket2",
        "ActionOnFailure": "CANCEL_AND_WAIT",
        "HadoopJarStep": {
            "Jar": "command-runner.jar",
            "Args": [
                "s3-dist-cp",
                "--src=s3://{{ params.BUCKET_NAME }}/input/",
                "--dest=hdfs:///input/",
            ],
        },
    },
    {
        "Name": "Run Pyspark script for total amount",
        "ActionOnFailure": "CANCEL_AND_WAIT",
        "HadoopJarStep": {
            "Jar": "command-runner.jar",
            "Args": [
                "spark-submit",
                "hdfs:///input/{{ params.s3_script }}",
            ],
        },
    },
    {
        "Name": "Copy Output to S3 bucket2",
        "ActionOnFailure": "CANCEL_AND_WAIT",
        "HadoopJarStep": {
            "Jar": "command-runner.jar",
            "Args": [
                "s3-dist-cp",
                "--src=hdfs:///output-airflow",
                "--dest=s3://{{ params.BUCKET_NAME }}/",
            ],
        },
    },
]


with DAG(
    dag_id="final-deliverable-dag",
    start_date=airflow.utils.dates.days_ago(5),
    schedule_interval="@daily"
) as dag:

    get_payment_data = PostgresToS3Operator(
        task_id="get_payment_data",
        postgres_conn_id="payment-database",
        query=(
            "select p.id, replace(p.amount,'$','')::float as amount, p.timestamp, p.customer_id, c.first_name, c.last_name, c.email, c.gender "
            "from payment as p "
            "join customer as c "
            "on p.customer_id::int = c.id "
            "where timestamp >= '{{ ds }}' and timestamp < '{{ next_ds }}';"
        ),
        s3_conn_id="aws-default",
        s3_bucket="final-deliverable-bucket2-dsnicolas",
        s3_key="input/payment-{{ ds }}.csv"
    )

    S3_BUCKET = "final-deliverable-bucket2-dsnicolas"
    S3_KEY = "input/payment-{{ ds }}.csv"
    REDSHIFT_TABLE = "payment"

    transfer_s3_to_redshift = S3ToRedshiftOperator(
        s3_bucket=S3_BUCKET,
        s3_key=S3_KEY,
        schema="PUBLIC",
        table=REDSHIFT_TABLE,
        copy_options=['CSV IGNOREHEADER 1'],
        task_id='transfer_s3_to_redshift',
    )

    get_payment_data >> transfer_s3_to_redshift

    perform_spark_steps = EmrAddStepsOperator(
        task_id="perform_spark_steps",
        job_flow_id="j-3FZBSJOF4P1EI", # Replace with your EMR cluster ID
        aws_conn_id="aws_default",
        steps=SPARK_STEPS,
        params={
            "BUCKET_NAME": "final-deliverable-bucket2-dsnicolas", # Replace with your bucket name
            "s3_script": "final_spark_script.py"
        }
    )

    # Get index of last step
    last_step = len(SPARK_STEPS) - 1
    check_steps_finished = EmrStepSensor(
        task_id="check_steps_finished",
        job_flow_id="j-3FZBSJOF4P1EI",  # Replace with your EMR cluster ID
        step_id="{{ task_instance.xcom_pull(task_ids='perform_spark_steps', key='return_value')["
        + str(last_step)
        + "] }}",
        aws_conn_id="aws_default",
    )

    spark_job_finished = DummyOperator(task_id="spark_job_finished")

    run_emr_spark = LatestOnlyOperator(task_id='run_emr_spark')

    run_emr_spark >> perform_spark_steps >> check_steps_finished >> spark_job_finished

