
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  select 'dim_date' as model_name, order_date
from "simulation"."main"."dim_date"
where typeof(order_date) <> 'DATE'

union all

select 'fact_order' as model_name, order_date
from "simulation"."main"."fact_order"
where typeof(order_date) <> 'DATE'

union all

select 'fact_sales_line' as model_name, order_date
from "simulation"."main"."fact_sales_line"
where typeof(order_date) <> 'DATE'
  
  
      
    ) dbt_internal_test