
    

    create  table
      "simulation"."main"."dim_payment_method__dbt_tmp"
  
    
    as (
      select distinct payment_method
from "simulation"."main"."stg_store_orders"
    );
    
  