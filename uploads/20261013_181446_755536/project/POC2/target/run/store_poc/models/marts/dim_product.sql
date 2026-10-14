
    

    create  table
      "simulation"."main"."dim_product__dbt_tmp"
  
    
    as (
      select distinct
    product_id,
    product_name,
    product_category
from "simulation"."main"."stg_store_orders"
    );
    
  