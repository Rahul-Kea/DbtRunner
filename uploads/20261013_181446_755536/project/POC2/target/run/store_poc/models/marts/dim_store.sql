
    

    create  table
      "simulation"."main"."dim_store__dbt_tmp"
  
    
    as (
      select distinct
    store_id,
    store_name
from "simulation"."main"."stg_store_orders"
    );
    
  