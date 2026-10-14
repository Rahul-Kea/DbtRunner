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