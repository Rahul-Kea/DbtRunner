
    

    create  table
      "simulation"."main"."dim_customer__dbt_tmp"
  
    
    as (
      select distinct
    customer_id,
    customer_name,
    customer_city
from "simulation"."main"."stg_store_orders"
    );
    
  