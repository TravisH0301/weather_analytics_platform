{{
    config(
        materialized='incremental'
    )
}}

{{
    generate_year_partition_model(
        "RAIN, ", 2012
    )
}}