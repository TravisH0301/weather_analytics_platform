###############################################################################
# Name: stage_data.py
# Description: 
#              
# Author: Travis Hong
# Repository: https://github.com/TravisH0301/weather_analysis
###############################################################################
import os
import io
import tarfile
import logging
from datetime import datetime
import pytz
import pandas as pd
import numpy as np

import boto3
import snowflake.connector
from snowflake.connector.pandas_tools import write_pandas


def find_latest_file(s3_client, bucket_name):
    """
    This function looks up the object storage
    bucket to find the latest file.

    Parameters
    ----------
    s3_client: object
        boto3 S3 client.
    bucket_name: str
        Name of source bucket.
    
    Returns
    -------
    latest_obj_name: str
        Name of the latest compressed BOM dataset file.
    latest_file_date: str
        Latest date of compressed BOM dataset file retrieval.
    """
    obj_name_date_dict = dict()
    response = s3_client.list_objects(Bucket=bucket_name)
    for obj in response["Contents"]:
        obj_name = obj["Key"]
        obj_date = obj_name[-14:-4]  #YYYY-MM-DD
        obj_name_date_dict[obj_name] = obj_date

    latest_obj_name = max(
        obj_name_date_dict, 
        key=lambda k: datetime.strptime(obj_name_date_dict[k], "%Y-%m-%d")
    )
    latest_file_date = obj_name_date_dict[latest_obj_name]
    
    return latest_obj_name, latest_file_date


def pre_process_csv(file_obj, state, file_date):
    """
    This function pre-processes CSV file object
    to refine columns with additional attributes.

    Parameters
    ----------
    file_obj: object
        CSV file object in Byte.
    state: str
        State the CSV dataset is from.
    file_date: str
        Date when the compressed BOM dataset file was extracted.

    Returns
    -------
    df: pd.DataFrame
        Pre-processed dataset.
    """
    columns = [
        'STATION_NAME',
        'DATE',
        'EVAPO_TRANSPIRATION',
        'RAIN',
        'PAN_EVAPORATION',
        'MAXIMUM_TEMPERATURE',
        'MINIMUM_TEMPERATURE',
        'MAXIMUM_RELATIVE_HUMIDITY',
        'MINIMUM_RELATIVE_HUMIDITY',
        'AVERAGE_10M_WIND_SPEED',
        'SOLAR_RADIATION'
    ]

    df = pd.read_csv(
        file_obj,
        encoding="ISO-8859-1",
        engine="python",
        skiprows=12,
        skipfooter=1,
        skip_blank_lines=True
    )
    df.columns = columns
    for float_col in columns[2:]:
        df[float_col] = df[float_col].astype(np.float64)
    df['STATE'] = state
    df['LOAD_DATE'] = date_today
    df['SOURCE_AS_OF'] = pd.to_datetime(file_date).date()

    return df


def main():
    logging.info("Process has started")

    # Load latest compressed file as byte stream object
    latest_file_name, latest_file_date = find_latest_file(s3, bucket_name)
    latest_file = io.BytesIO()
    s3.download_fileobj(
        Bucket=bucket_name,
        Key=latest_file_name,
        Fileobj=latest_file
    )

    # Create Snowflake tables if not existing
    cur.execute(query_create_tgt_table)
    cur.execute(query_create_temp_table)

    # Explore byte stream object to process and load datasets into Snowflake
    latest_file.seek(0)
    with tarfile.open(fileobj=latest_file) as tar_file:
        for member in tar_file.getmembers():
            # Process and load csv datasets
            if member.isfile() and member.name.endswith(".csv"):
                # Convert csv file object to dataframe
                state = member.name.split("/")[1].upper()
                csv_obj = tar_file.extractfile(member)
                df = pre_process_csv(csv_obj, state, latest_file_date)
                
                # Load dataframe to temporary table
                write_pandas(conn, df, table_temp)

                # Merge from temporary table to target table
                cur.execute(query_merge)

                exit()




    

    logging.info("Process has completed")


if __name__ == "__main__":
    # Define variables
    ## Logger
    logging.basicConfig(
        filename = "./log/stage_data_log.txt",
        filemode="w",
        level=logging.INFO,
        format = "%(asctime)s; %(levelname)s; %(message)s",
        datefmt="%m/%d/%Y %I:%M:%S %p %Z"
    )
    ## Date
    melb_tz = pytz.timezone('Australia/Melbourne')
    datetime_now = datetime.now(melb_tz)
    date_today = datetime_now.date().strftime("%Y-%m-%d")
    ## S3-compatible object storage via MinIO
    minio_endpoint = os.environ["MINIO_ENDPOINT"]
    minio_access_key = os.environ["MINIO_ACCESS_KEY"]
    minio_secret_key = os.environ["MINIO_SECRET_KEY"]
    bucket_name = "bom-landing"
    s3 = boto3.client(
        "s3",
        endpoint_url=minio_endpoint,
        aws_access_key_id=minio_access_key,
        aws_secret_access_key=minio_secret_key
    )
    ## Snowflake
    snowflake_user = os.environ["SNOWFLAKE_USER"]
    snowflake_pwd = os.environ["SNOWFLAKE_PWD"]
    snowflake_acct = os.environ["SNOWFLAKE_ACCT"]
    snowflake_wh = "COMPUTE_WH"
    snowflake_db = "WEATHER_ANALYSIS"
    snowflake_schema = "STAGING"
    conn = snowflake.connector.connect(
        user=snowflake_user,
        password=snowflake_pwd,
        account=snowflake_acct,
        warehouse=snowflake_wh,
        database=snowflake_db,
        schema=snowflake_schema
    )
    cur = conn.cursor()
    table_tgt = "WEATHER_PREPROCESSED"
    table_temp = "WEATHER_PREPROCESSED_TEMP"
    query_create_tgt_table = f"""
        CREATE TABLE IF NOT EXISTS {table_tgt} (
            STATION_NAME VARCHAR(100),
            DATE DATE,
            EVAPO_TRANSPIRATION FLOAT,
            RAIN FLOAT,
            PAN_EVAPORATION FLOAT,
            MAXIMUM_TEMPERATURE FLOAT,
            MINIMUM_TEMPERATURE FLOAT,
            MAXIMUM_RELATIVE_HUMIDITY FLOAT,
            MINIMUM_RELATIVE_HUMIDITY FLOAT,
            AVERAGE_10M_WIND_SPEED FLOAT,
            SOLAR_RADIATION FLOAT,
            STATE VARCHAR(100),
            LOAD_DATE DATE,
            SOURCE_AS_OF DATE
        );
    """
    query_create_temp_table = f"""
        CREATE TEMPORARY TABLE {table_temp} LIKE {table_tgt};
    """
    query_delete_temp_table = f"""
        DELETE FROM {table_temp};
    """
    query_merge = f"""
        MERGE INTO {table_tgt} AS TARGET 
        USING {table_temp} AS SOURCE
            ON TARGET.STATION_NAME = SOURCE.STATION_NAME
                AND TARGET.DATE = SOURCE.DATE
            WHEN NOT MATCHED THEN INSERT (
                STATION_NAME,
                DATE,
                EVAPO_TRANSPIRATION,
                RAIN,
                PAN_EVAPORATION,
                MAXIMUM_TEMPERATURE,
                MINIMUM_TEMPERATURE,
                MAXIMUM_RELATIVE_HUMIDITY,
                MINIMUM_RELATIVE_HUMIDITY,
                AVERAGE_10M_WIND_SPEED,
                SOLAR_RADIATION,
                STATE,
                LOAD_DATE,
                SOURCE_AS_OF
            ) VALUES (
                SOURCE.STATION_NAME,
                SOURCE.DATE,
                SOURCE.EVAPO_TRANSPIRATION,
                SOURCE.RAIN,
                SOURCE.PAN_EVAPORATION,
                SOURCE.MAXIMUM_TEMPERATURE,
                SOURCE.MINIMUM_TEMPERATURE,
                SOURCE.MAXIMUM_RELATIVE_HUMIDITY,
                SOURCE.MINIMUM_RELATIVE_HUMIDITY,
                SOURCE.AVERAGE_10M_WIND_SPEED,
                SOURCE.SOLAR_RADIATION,
                SOURCE.STATE,
                SOURCE.LOAD_DATE,
                SOURCE.SOURCE_AS_OF
            );
    """

    try:
        main()
    except Exception:
        logging.error("Process has failed:", exc_info=True)
        raise