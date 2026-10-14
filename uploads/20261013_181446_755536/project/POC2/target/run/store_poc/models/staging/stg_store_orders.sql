
    

    create  table
      "simulation"."main"."stg_store_orders__dbt_tmp"
  
    
    as (
      select
    cast(order_id as integer) as order_id,
    cast(order_date as date) as order_date,
    customer_id,
    customer_name,
    customer_city,
    product_id,
    product_name,
    product_category,
    cast(unit_price as decimal(10, 2)) as unit_price,
    cast(quantity as integer) as quantity,
    store_id,
    store_name,
    payment_method,
    cast(unit_price * quantity as decimal(10, 2)) as line_amount
from "simulation"."main"."store_orders"
    );
    
  