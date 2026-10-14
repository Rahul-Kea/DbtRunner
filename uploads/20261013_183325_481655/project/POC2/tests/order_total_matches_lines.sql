select
    o.order_id,
    o.order_total,
    sum(l.line_amount) as line_total
from {{ ref('fact_order') }} as o
join {{ ref('fact_sales_line') }} as l
    on o.order_id = l.order_id
group by o.order_id, o.order_total
having abs(o.order_total - sum(l.line_amount)) > 0.00
