with line_totals as (
    select
        order_id,
        sum(line_amount) as line_total
    from "simulation"."main"."fact_sales_line"
    group by order_id
)

select
    coalesce(orders.order_id, lines.order_id) as order_id,
    orders.order_total,
    lines.line_total
from "simulation"."main"."fact_order" as orders
full outer join line_totals as lines
    on orders.order_id = lines.order_id
where orders.order_id is null
   or lines.order_id is null
   or orders.order_total <> lines.line_total