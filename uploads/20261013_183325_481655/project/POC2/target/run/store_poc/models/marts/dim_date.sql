
    

    create  table
      "simulation"."main"."dim_date__dbt_tmp"
  
    
    as (
      select distinct order_date
from "simulation"."main"."stg_store_orders"
    );
    
  