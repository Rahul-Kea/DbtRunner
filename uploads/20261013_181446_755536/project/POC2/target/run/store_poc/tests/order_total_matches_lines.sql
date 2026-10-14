
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  select
    o.order_id,
    o.order_total,
    sum(l.line_amount) as line_total
from "simulation"."main"."fact_order" as o
join "simulation"."main"."fact_sales_line" as l
    on o.order_id = l.order_id
group by o.order_id, o.order_total
having abs(o.order_total - sum(l.line_amount)) > 0.00
  
  
      
    ) dbt_internal_test